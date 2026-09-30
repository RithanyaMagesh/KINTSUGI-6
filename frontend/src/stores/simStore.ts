// Simulation store — FRONTEND_SPEC §15.1. One deserializer serves live WS,
// replay, and logs. Every field starts unmeasured; the UI renders the string
// "unmeasured" for null values (repo invariant 1) until real frames arrive.
import { create } from "zustand";
import type {
  ConnectionState,
  Metrics,
  SimMode,
} from "../types/telemetry";
import type { MissionState, Satellite } from "../types/satellite";
import type { SimEvent } from "../types/events";
import type {
  EventMessage,
  RoleReassignmentMessage,
  SimStateMessage,
  WireMessage,
} from "../types/events";

const MAX_EVENTS = 200; // drop-oldest, matching the backend hub's bounding

interface SimStore {
  mode: SimMode;
  connection: ConnectionState;
  simTime: number | null;
  missionState: MissionState | null;
  scenario: string | null;
  seed: number | null;
  satellites: Satellite[];
  metrics: Partial<Metrics>;
  events: SimEvent[];
  lastReassignment: RoleReassignmentMessage | null;

  setConnection(connection: ConnectionState): void;
  setMode(mode: SimMode): void;
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
  satellites: [] as Satellite[],
  metrics: {} as Partial<Metrics>,
  events: [] as SimEvent[],
  lastReassignment: null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function toSatellite(raw: Record<string, unknown>): Satellite | null {
  if (
    typeof raw.id !== "string" ||
    !Array.isArray(raw.r) ||
    raw.r.length !== 3 ||
    !Array.isArray(raw.v) ||
    raw.v.length !== 3
  ) {
    return null;
  }
  return {
    id: raw.id,
    role: typeof raw.role === "string" ? raw.role : "unknown",
    status: (typeof raw.status === "string" ? raw.status : "inactive") as Satellite["status"],
    r: [Number(raw.r[0]), Number(raw.r[1]), Number(raw.r[2])],
    v: [Number(raw.v[0]), Number(raw.v[1]), Number(raw.v[2])],
    dv_used: typeof raw.dv_used === "number" ? raw.dv_used : 0,
    targetSlot: typeof raw.target_slot === "string" ? raw.target_slot : undefined,
    failureType: typeof raw.failure_type === "string" ? raw.failure_type : undefined,
    risk: typeof raw.risk === "number" ? raw.risk : undefined,
  };
}

function applySimState(msg: SimStateMessage): Partial<SimStore> {
  const satellites = msg.sats
    .map((s) => toSatellite(s as unknown as Record<string, unknown>))
    .filter((s): s is Satellite => s !== null);
  const metrics: Partial<Metrics> = {};
  if (typeof msg.coverage === "number") metrics.coverage = msg.coverage;
  if (typeof msg.min_sep === "number") metrics.minSep = msg.min_sep;
  const m = isRecord(msg.metrics) ? msg.metrics : {};
  if (typeof m.detection_latency_s === "number")
    metrics.detectionLatencyS = m.detection_latency_s;
  if (typeof m.replanning_latency_ms === "number")
    metrics.replanningLatencyMs = m.replanning_latency_ms;
  return {
    simTime: typeof msg.sim_time === "number" ? msg.sim_time : null,
    missionState: (typeof msg.state === "string" ? msg.state : null) as MissionState | null,
    scenario: typeof msg.scenario === "string" ? msg.scenario : null,
    seed: typeof msg.seed === "number" ? msg.seed : null,
    satellites,
    metrics,
  };
}

export const useSimStore = create<SimStore>((set) => ({
  ...initial,

  setConnection: (connection) => set({ connection }),
  setMode: (mode) => set({ mode }),

  applyMessage: (raw) =>
    set((state) => {
      if (!isRecord(raw) || typeof raw.type !== "string") return {};
      const msg = raw as unknown as WireMessage;
      switch (msg.type) {
        case "hello": {
          // Session greeting (cubesat/session.py): tells the UI which mode the
          // backend session is already in (live | replay) so the Replay badge
          // is correct even when the console joins mid-session.
          const mode = typeof raw.mode === "string" ? raw.mode : null;
          return {
            mode:
              mode === "live" || mode === "replay" ? mode : state.mode,
            scenario: typeof raw.scenario === "string" ? raw.scenario : state.scenario,
            seed: typeof raw.seed === "number" ? raw.seed : state.seed,
          };
        }
        case "sim_state": {
          const patch = applySimState(msg as SimStateMessage);
          return { ...patch, mode: state.mode === "stopped" ? "live" : state.mode };
        }
        case "event": {
          const e = msg as EventMessage;
          if (typeof e.message !== "string") return {};
          const event: SimEvent = {
            simTime: typeof e.sim_time === "number" ? e.sim_time : 0,
            level: (["info", "warning", "critical"].includes(e.level)
              ? e.level
              : "info") as SimEvent["level"],
            message: e.message,
          };
          return { events: [...state.events, event].slice(-MAX_EVENTS) };
        }
        case "role_reassignment": {
          const r = msg as RoleReassignmentMessage;
          return {
            lastReassignment: r,
            // target_slot per satellite already arrives on the next sim_state;
            // nothing is invented here for rows the log does not carry.
          };
        }
        default:
          return {};
      }
    }),

  reset: () => set({ ...initial }),
}));
