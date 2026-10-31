// Simulation store — FRONTEND_SPEC §15.1. Parsing itself lives in the ONE
// shared deserializer (src/api/deserializer.ts, §18) that also serves replay:
// the backend drives replay through the same /ws/state socket, so live and
// replay frames cannot drift apart (§21.9). Every field starts unmeasured;
// the UI renders the string "unmeasured" for null values (repo invariant 1)
// until real frames arrive.
import { create } from "zustand";
import type { ConnectionState, Metrics, SimMode } from "../types/telemetry";
import type { MissionState, Satellite } from "../types/satellite";
import type { SimEvent } from "../types/events";
import { deserializeMessage } from "../api/deserializer";

const MAX_EVENTS = 200; // drop-oldest, matching the backend hub's bounding

interface SimStore {
  mode: SimMode;
  connection: ConnectionState;
  simTime: number | null;
  missionState: MissionState | null;
  scenario: string | null;
  seed: number | null;
  /** Active recovery policy as the session reports it — hello.policy (carried
   * on every live run, cubesat/session.py hello()); sim_state echoes it only
   * when it deviates from "hungarian" (cubesat/wire.py _policy_field). null =
   * unmeasured: the Recovery-mode readout renders "unmeasured", never a
   * guessed default (repo invariant 1). */
  policy: string | null;
  /** Keep-out floor of the running scenario [m] (hello / start response);
   * null = unknown, the UI then shows no floor rather than a guessed 2 km. */
  minSepM: number | null;
  satellites: Satellite[];
  metrics: Partial<Metrics>;
  events: SimEvent[];
  /** §8.1 role reallocation table — the latest role_reassignment message with
   * oldRole derived from the previous frame's roles (a measured diff; the wire
   * does not carry old_role, cubesat/wire.py _role_reassignment). */
  lastReassignment: {
    simTime: number;
    rows: Array<{
      satelliteId: string;
      oldRole: string | null;
      newRole: string | null;
      targetSlot: string | null;
    }>;
    costTotal: number | null;
  } | null;
  /** Roles from the LAST frame, keyed by sat id — lets the next role_reassignment
   * message show what each satellite did before the replan. */
  priorRoles: Record<string, string>;

  setConnection(connection: ConnectionState): void;
  setMode(mode: SimMode): void;
  setSessionMeta(meta: {
    scenario?: string | null;
    seed?: number | null;
    policy?: string | null;
    minSepM?: number | null;
  }): void;
  applyMessage(raw: unknown): void;
  reset(): void;
}

const initial = {
  mode: "stopped" as SimMode,
  connection: "disconnected" as ConnectionState,
  simTime: null,
  missionState: null,
  scenario: null,
  seed: null,
  policy: null as string | null,
  minSepM: null as number | null,
  satellites: [] as Satellite[],
  metrics: {} as Partial<Metrics>,
  events: [] as SimEvent[],
  lastReassignment: null,
  priorRoles: {} as Record<string, string>,
};

export const useSimStore = create<SimStore>((set, get) => ({
  ...initial,

  setConnection: (connection) => set({ connection }),
  setMode: (mode) => set({ mode }),
  setSessionMeta: (meta) =>
    set((state) => ({
      scenario: meta.scenario !== undefined ? meta.scenario : state.scenario,
      seed: meta.seed !== undefined ? meta.seed : state.seed,
      policy: meta.policy !== undefined ? meta.policy : state.policy,
      minSepM: meta.minSepM !== undefined ? meta.minSepM : state.minSepM,
    })),

  applyMessage: (raw) => {
    const msg = deserializeMessage(raw);
    if (msg === null) return; // malformed / unknown: dropped, never fatal (§18)
    set((state) => {
      switch (msg.kind) {
        case "hello":
          // Session greeting (cubesat/session.py): tells the UI which mode the
          // backend session is already in (live | replay) so the Replay badge
          // is correct even when the console joins mid-session. Live hellos
          // always carry the active policy; stopped/replay omit it (unknown),
          // so absence keeps whatever was measured rather than clobbering.
          return {
            mode: msg.mode,
            scenario: msg.scenario ?? state.scenario,
            seed: msg.seed ?? state.seed,
            policy: msg.policy ?? state.policy,
            minSepM: msg.minSepM ?? state.minSepM,
          };
        case "frame": {
          // INIT-derived empty state (cubesat/wire.py to_sim_state): resets the
          // console to the §24.3 "no satellites" state instead of faking a
          // NOMINAL badge with zero satellites on screen. Keep state.policy
          // when msg.frame.policy is absent because wire.py _policy_field omits
          // "hungarian" by design and hello is connect-only; replay loads call
          // reset() beforehand so stale live policies never leak into replay.
          if (msg.frame.satellites.length === 0 && msg.frame.simTime === 0) {
            return {
              simTime: 0,
              scenario: msg.frame.scenario ?? state.scenario,
              seed: msg.frame.seed ?? state.seed,
              policy: msg.frame.policy ?? state.policy,
              satellites: [],
              metrics: {},
              events: [],
              lastReassignment: null,
              priorRoles: {},
              missionState: null,
            };
          }
          // priorRoles keeps the PRE-tick role for any satellite whose role
          // changed on this frame (cubesat/sim.py updates roles[] on the same
          // tick it emits ASSIGNMENT, and wire.py sends sim_state first) —
          // so the §8.1 table can show old role without the backend
          // inventing an old_role field it does not have. Unchanged ids keep
          // their role; index iteration, no map-order dependence.
          const priorRoles: Record<string, string> = {};
          for (const sat of msg.frame.satellites) {
            const prev = state.satellites.find((p) => p.id === sat.id);
            priorRoles[sat.id] = prev !== undefined ? prev.role : sat.role;
          }
          return {
            simTime: msg.frame.simTime,
            missionState: msg.frame.missionState as MissionState,
            scenario: msg.frame.scenario ?? state.scenario,
            seed: msg.frame.seed ?? state.seed,
            // Frames echo policy only when it deviates from "hungarian"
            // (cubesat/wire.py _policy_field) — absence must not clobber the
            // hello's value (a hungarian run's frames never mention it).
            policy: msg.frame.policy ?? state.policy,
            satellites: msg.frame.satellites,
            metrics: msg.frame.metrics,
            priorRoles,
            mode: state.mode === "stopped" ? "live" : state.mode,
          };
        }
        case "event":
          return {
            events: [...state.events, msg.event].slice(-MAX_EVENTS),
          };
        case "reassignment":
          return {
            lastReassignment: {
              simTime: msg.reassignment.sim_time,
              rows: msg.reassignment.assignments.map((a) => ({
                satelliteId: a.satellite_id,
                oldRole: state.priorRoles[a.satellite_id] ?? null,
                newRole: a.new_role,
                targetSlot: a.target_slot,
              })),
              costTotal:
                typeof msg.reassignment.cost_total === "number"
                  ? msg.reassignment.cost_total
                  : null,
            },
            // target_slot per satellite already arrives on the next sim_state;
            // nothing is invented here for rows the log does not carry.
          };
      }
    });
  },

  // Reset session data but keep the LIVE connection state: the socket is still
  // open when a replay/scenario switch lands, and clobbering `connection` here
  // left the badge and the §20.1 overlay lying while frames streamed
  // (found in the 2026-09-30 live run).
  reset: () => set({ ...initial, connection: get().connection }),
}));
