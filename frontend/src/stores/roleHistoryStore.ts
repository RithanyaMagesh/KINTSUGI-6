// Per-satellite role & task history — the store behind the
// SelectedSatellitePanel "role and task history" timeline.
//
// Parsing uses the ONE shared deserializer (src/api/deserializer.ts) that also
// serves simStore — live and replay parse identical bytes, schema drift is
// impossible by construction (§21.9). Every recorded value is measured:
//   - reassignment entries come from role_reassignment messages (cubesat/wire.py
//     _role_reassignment); the OLD role/slot is diffed from the previous frame's
//     satellites (the wire does not carry old_role/old_slot — same measured-diff
//     approach as simStore.priorRoles), and dv_used is snapshotted from the
//     same-tick sim_state (wire order: sim_state first, then role_reassignment).
//   - the triggering failure note is the most recent critical event message
//     (wire.py renders FAILURE_DETECTED as "SAT-n MODE failure detected") —
//     only attached when one has actually been seen.
//   - failed entries: the frame where the satellite's status flips to "failed"
//     (wire.py _STATUS_TO_WIRE flips at t_fail), carrying the role and slot it
//     was holding at that moment.
//   - recovered entries: the mission-state flip to RECOVERED on a frame
//     (per-satellite recovered status is frontend-derived upstream; the
//     mission state is the measured swarm-level recovery signal).
//
// ingest() must be called for every raw socket message, alongside
// simStore.applyMessage() (see useWebSocket). Wire to it once:
//   const ingest = useRoleHistoryStore((s) => s.ingest);  // then ingest(msg)

import { create } from "zustand";
import { deserializeMessage } from "../api/deserializer";
import type { Satellite } from "../types/satellite";

/** One timeline entry for one satellite. role/targetSlot describe the state
 * AFTER the entry; oldRole/oldTargetSlot the measured state BEFORE (null when
 * no previous frame carried the satellite — e.g. a mid-session join). */
export interface RoleHistoryEntry {
  t: number;
  kind: "reassignment" | "failed" | "recovered";
  role: string | null;
  targetSlot: string | null;
  oldRole: string | null;
  oldTargetSlot: string | null;
  /** dv_used snapshot [m/s] at this entry; null when no frame carried it yet. */
  dvUsed: number | null;
  /** Measured note: for reassignments the triggering critical event message;
   * for failures the wire failure_type; for recovery the spec's wording. */
  note: string | null;
}

const EMPTY_HISTORY: RoleHistoryEntry[] = [];

interface RoleHistoryState {
  /** Per-satellite append-only history, keyed by satellite id. */
  history: Record<string, RoleHistoryEntry[]>;
  ingest(raw: unknown): void;
  resetForNewRun(): void;

  // Internal fold state — not part of the UI contract. Kept in the store so
  // resetForNewRun() and INIT frames clear it in one place.
  _lastFrameSats: Record<string, Satellite>;
  _prevFrameSats: Record<string, Satellite>;
  _lastSimTime: number | null;
  _missionState: string | null;
  _lastCritical: { simTime: number; message: string } | null;
}

const initialInternal = {
  _lastFrameSats: {},
  _prevFrameSats: {},
  _lastSimTime: null,
  _missionState: null,
  _lastCritical: null,
};

function satMap(sats: Satellite[]): Record<string, Satellite> {
  const out: Record<string, Satellite> = {};
  for (const sat of sats) out[sat.id] = sat;
  return out;
}

/** True when the satellite's history already carries this entry (replay seek
 * re-delivers frames; dedupe keeps the timeline append-only and stable). */
function alreadyRecorded(
  entries: RoleHistoryEntry[],
  kind: RoleHistoryEntry["kind"],
  t: number,
): boolean {
  return entries.some((e) => e.kind === kind && e.t === t);
}

/** Drop-oldest cap per satellite. Only real state transitions (failed,
 * recovered, or a reassignment where the satellite's role or targetSlot
 * actually changed) are appended, so 250 entries preserves full mission
 * histories even across long multi-failure or large-swarm runs (§3.2 #8). */
export const MAX_HISTORY_PER_SAT = 250;

function appendEntry(
  history: Record<string, RoleHistoryEntry[]>,
  satId: string,
  entry: RoleHistoryEntry,
): Record<string, RoleHistoryEntry[]> {
  const existing = history[satId] ?? [];
  if (alreadyRecorded(existing, entry.kind, entry.t)) return history;
  const next = [...existing, entry].slice(-MAX_HISTORY_PER_SAT);
  return { ...history, [satId]: next };
}

export const useRoleHistoryStore = create<RoleHistoryState>((set) => ({
  history: {},
  ...initialInternal,

  ingest: (raw) => {
    const msg = deserializeMessage(raw);
    if (msg === null) return; // malformed / unknown: dropped, never fatal (§18)
    set((state) => {
      switch (msg.kind) {
        case "frame": {
          const frame = msg.frame;
          // INIT-derived empty state: a new run started — reset everything
          // (mirrors simStore's INIT handling).
          if (frame.satellites.length === 0 && frame.simTime === 0) {
            return { history: {}, ...initialInternal };
          }

          let history = state.history;
          // Failure snapshot: the frame where this satellite flips to "failed"
          // (wire.py flips at t_fail), carrying what it was doing at death.
          for (const sat of frame.satellites) {
            const prev = state._lastFrameSats[sat.id];
            if (
              prev !== undefined &&
              prev.status !== "failed" &&
              sat.status === "failed" &&
              !alreadyRecorded(history[sat.id] ?? [], "failed", frame.simTime)
            ) {
              history = appendEntry(history, sat.id, {
                t: frame.simTime,
                kind: "failed",
                role: sat.role,
                targetSlot: sat.targetSlot ?? null,
                oldRole: prev.role,
                oldTargetSlot: prev.targetSlot ?? null,
                dvUsed: sat.dv_used,
                note: sat.failureType ?? null,
              });
            }
          }

          // Swarm recovery: the mission-state flip to RECOVERED on a frame.
          // Never fires for a satellite that is still failed — dead satellites
          // coast (invariant 5); the note is the spec's own wording (§7.3).
          if (
            state._missionState !== null &&
            state._missionState !== "RECOVERED" &&
            frame.missionState === "RECOVERED"
          ) {
            for (const sat of frame.satellites) {
              if (sat.status === "failed") continue;
              history = appendEntry(history, sat.id, {
                t: frame.simTime,
                kind: "recovered",
                role: null,
                targetSlot: null,
                oldRole: null,
                oldTargetSlot: null,
                dvUsed: null,
                note: "formation recovered",
              });
            }
          }

          return {
            history,
            _lastFrameSats: satMap(frame.satellites),
            _prevFrameSats: state._lastFrameSats,
            _lastSimTime: frame.simTime,
            _missionState: frame.missionState,
            _lastCritical: state._lastCritical,
          };
        }
        case "event": {
          // The triggering-failure note source: the most recent critical event
          // (wire.py _failure_event). Non-critical events carry no history here.
          if (msg.event.level !== "critical") return state;
          return {
            _lastCritical: { simTime: msg.event.simTime, message: msg.event.message },
          };
        }
        case "reassignment": {
          // Record only rows where the satellite's role or target slot actually
          // changed (§3.2 #8) — unchanged survivor rows are skipped at ingest
          // so they never evict real movements from the per-satellite history.
          let history = state.history;
          for (const a of msg.reassignment.assignments) {
            const current = state._lastFrameSats[a.satellite_id];
            const prev = state._prevFrameSats[a.satellite_id];
            const oldRole = prev?.role ?? null;
            const oldTargetSlot = prev?.targetSlot ?? null;
            const slotChanged =
              a.target_slot !== null &&
              oldTargetSlot !== null &&
              a.target_slot !== oldTargetSlot;
            const roleChanged =
              a.new_role !== null && oldRole !== null && a.new_role !== oldRole;
            if (!slotChanged && !roleChanged) continue;
            history = appendEntry(history, a.satellite_id, {
              t: msg.reassignment.sim_time,
              kind: "reassignment",
              role: a.new_role,
              targetSlot: a.target_slot,
              oldRole,
              oldTargetSlot,
              dvUsed: current?.dv_used ?? null,
              note: state._lastCritical?.message ?? null,
            });
          }
          return { ...state, history };
        }
        case "hello":
          return state;
      }
    });
  },

  resetForNewRun: () => set({ history: {}, ...initialInternal }),
}));

/** Reactive selector: this satellite's role/task history, oldest first.
 * Hook — call inside a component. Returns a stable empty array when the
 * satellite has no recorded history yet. */
export function historyFor(satId: string | null): RoleHistoryEntry[] {
  return useRoleHistoryStore((s) =>
    satId === null ? EMPTY_HISTORY : (s.history[satId] ?? EMPTY_HISTORY),
  );
}
