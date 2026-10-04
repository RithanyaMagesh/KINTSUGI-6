// Recovery story store — accumulates the mission's recovery narrative
// (mission-state phase history, failure records, role-reassignment events,
// per-failure coverage) so the UI can EXPLAIN what is happening (user demand:
// "each failure is not explained… I need to show actual recovery").
//
// Every value here is measured (repo invariant 1). Two intake paths, both
// fed by the ONE shared parser (src/api/deserializer.ts §18/§21.9):
//  1. ingest(raw) — runs deserializeMessage on the raw wire message. Wire it
//     next to simStore.applyMessage in the WS handler (src/hooks/useWebSocket.ts).
//  2. A simStore bridge (below) — derives the same facts from state that
//     simStore already parsed through deserializeMessage. It exists so the
//     story works before the integrator wires path 1, and it RETIRES ITSELF
//     the moment ingest() is called (no double-counting).
// A fact the wire does not carry stays null (detection latency, cost_total,
// pre-failure coverage before the first measured frame) and the narration
// drops that clause — never guessed.
import { create } from "zustand";
import { deserializeMessage } from "../api/deserializer";
import { useSimStore } from "./simStore";
import type { Satellite } from "../types/satellite";

export interface RecoveryPhase {
  state: string; // backend mission-state literal (cubesat/wire.py)
  tStart: number; // sim time the state was first observed [s]
  tEnd: number | null; // sim time it ended; null while current
}

export interface FailureRecord {
  satId: string;
  mode: string | null; // wire failure_type ("DEAD" | "THRUSTER_OUT") when carried
  tFail: number; // sim time of the first frame observing the failure [s]
  detectionLatencyS: number | null; // frame metrics.detection_latency_s when present
  vacatedSlot: string | null; // last measured target_slot of the failed satellite
  coverage: {
    pre: number | null; // last measured coverage before the failure [0-1]
    min: number | null; // minimum measured coverage since the failure
    current: number | null; // latest measured coverage
  };
  recovered: boolean; // satellite later observed healthy/recovered on a frame
}

export interface AssignmentEvent {
  time: number; // sim time of the role_reassignment message [s]
  rows: Array<{
    satelliteId: string;
    targetSlot: string | null;
    /** Slot the satellite held on the frame BEFORE this reassignment, as
     * measured off the wire. The same-tick sim_state already carries the NEW
     * slot (cubesat/wire.py to_messages applies the assignment to
     * enrich.assignment_map before building sim_state), so "unchanged" can
     * only be proven against the previous frame. null = no earlier frame
     * carried a slot for this satellite (e.g. the run's first ASSIGNMENT —
     * wire.py emits target_slot only after the first assignment_map fill):
     * movement cannot be proven either way. */
    prevSlot: string | null;
  }>;
  costTotal: number | null; // wire cost_total when carried — never invented
}

interface RecoveryStore {
  phases: RecoveryPhase[];
  failures: FailureRecord[];
  assignments: AssignmentEvent[];
  /** @internal state the phase currently open (null = none yet) */
  openPhaseState: string | null;
  /** @internal satellite ids currently observed failed */
  failedSeen: Record<string, boolean>;
  /** @internal last measured coverage seen on a frame [0-1] */
  lastCoverage: number | null;
  /** @internal last measured target_slot per satellite id */
  lastSlots: Record<string, string>;
  /** @internal lastSlots as of BEFORE the most recent frame — the pre-tick
   * snapshot a role_reassignment (which arrives after its same-tick sim_state)
   * must diff against to know who actually moved. */
  prevSlots: Record<string, string>;

  ingest(raw: unknown): void;
  resetForNewRun(): void;
}

const MAX_PHASES = 48;
const MAX_FAILURES = 24;
const MAX_ASSIGNMENTS = 24;

/** True once ingest() has been called — the simStore bridge retires itself. */
let rawSeen = false;

type FrameFacts = {
  simTime: number;
  missionState: string | null;
  satellites: Satellite[];
  coverage: number | null;
  detectionLatencyS: number | null;
};

/** Fold one frame's measured facts into the story. Copy-on-write: unchanged
 * collections keep their reference so zustand selectors stay stable. */
function frameUpdate(
  s: RecoveryStore,
  f: FrameFacts,
): Partial<RecoveryStore> {
  const out: Partial<RecoveryStore> = {};
  // INIT-derived empty state (cubesat/wire.py to_sim_state): no story facts.
  if (f.satellites.length === 0 && f.simTime === 0) return out;

  // Phase history: close the open phase and open the new one on state change.
  if (f.missionState !== null && f.missionState !== s.openPhaseState) {
    const next = s.phases.slice();
    if (next.length > 0) {
      const last = next[next.length - 1];
      if (last.tEnd === null) next[next.length - 1] = { ...last, tEnd: f.simTime };
    }
    next.push({ state: f.missionState, tStart: f.simTime, tEnd: null });
    if (next.length > MAX_PHASES) next.splice(0, next.length - MAX_PHASES);
    out.phases = next;
    out.openPhaseState = f.missionState;
  }

  // Failures: enter failed / leave failed, tracked by id so re-failures and
  // recoveries both register. vacatedSlot prefers the slot still carried on
  // the failure frame, else the last slot measured on earlier frames.
  let nextFailures = s.failures;
  let failuresChanged = false;
  const failedSeen = { ...s.failedSeen };
  let seenChanged = false;
  for (const sat of f.satellites) {
    if (sat.status === "failed") {
      if (!failedSeen[sat.id]) {
        failedSeen[sat.id] = true;
        seenChanged = true;
        nextFailures = [
          ...nextFailures,
          {
            satId: sat.id,
            mode: sat.failureType ?? null,
            tFail: f.simTime,
            detectionLatencyS: f.detectionLatencyS,
            vacatedSlot: sat.targetSlot ?? s.lastSlots[sat.id] ?? null,
            coverage: { pre: s.lastCoverage, min: f.coverage, current: f.coverage },
            recovered: false,
          },
        ];
        if (nextFailures.length > MAX_FAILURES) {
          nextFailures = nextFailures.slice(-MAX_FAILURES);
        }
        failuresChanged = true;
      }
    } else if (failedSeen[sat.id]) {
      delete failedSeen[sat.id];
      seenChanged = true;
      if (sat.status === "healthy" || sat.status === "recovered") {
        for (let i = nextFailures.length - 1; i >= 0; i--) {
          const rec = nextFailures[i];
          if (rec.satId === sat.id && !rec.recovered) {
            const copy = nextFailures.slice();
            copy[i] = { ...rec, recovered: true };
            nextFailures = copy;
            failuresChanged = true;
            break;
          }
        }
      }
    }
  }

  // Coverage + detection latency stream in on frames after the failure.
  if (nextFailures.length > 0 && (f.coverage !== null || f.detectionLatencyS !== null)) {
    const copy = nextFailures.slice();
    for (let i = 0; i < copy.length; i++) {
      const rec = copy[i];
      let changed = false;
      let min = rec.coverage.min;
      let current = rec.coverage.current;
      if (f.coverage !== null) {
        min = min === null ? f.coverage : Math.min(min, f.coverage);
        current = f.coverage;
        if (min !== rec.coverage.min || current !== rec.coverage.current) changed = true;
      }
      const isLast = i === copy.length - 1;
      const latency = rec.detectionLatencyS;
      if (
        isLast && latency === null && f.detectionLatencyS !== null &&
        rec.tFail < f.simTime
      ) {
        copy[i] = { ...rec, detectionLatencyS: f.detectionLatencyS, coverage: { pre: rec.coverage.pre, min, current } };
        changed = true;
      } else if (changed) {
        copy[i] = { ...rec, coverage: { pre: rec.coverage.pre, min, current } };
      }
      if (changed) failuresChanged = true;
    }
    nextFailures = copy;
  }
  if (failuresChanged) out.failures = nextFailures;
  if (seenChanged) out.failedSeen = failedSeen;

  // lastSlots AFTER failure processing: the vacated slot must come from
  // strictly earlier frames (or the failure frame's own carried slot).
  // prevSlots snapshots the pre-frame slots FIRST: the role_reassignment
  // message that follows this frame diffs against it (the same-tick sim_state
  // already carries the NEW slots — cubesat/wire.py to_messages).
  out.prevSlots = s.lastSlots;
  let nextSlots = s.lastSlots;
  let slotsChanged = false;
  for (const sat of f.satellites) {
    if (sat.targetSlot !== undefined && nextSlots[sat.id] !== sat.targetSlot) {
      if (!slotsChanged) {
        nextSlots = { ...nextSlots };
        slotsChanged = true;
      }
      nextSlots[sat.id] = sat.targetSlot;
    }
  }
  if (slotsChanged) out.lastSlots = nextSlots;

  if (f.coverage !== null && f.coverage !== s.lastCoverage) {
    out.lastCoverage = f.coverage;
  }
  return out;
}

function pushAssignment(
  s: RecoveryStore,
  event: AssignmentEvent,
): Partial<RecoveryStore> {
  return { assignments: [...s.assignments, event].slice(-MAX_ASSIGNMENTS) };
}

const initialInternal = {
  openPhaseState: null as string | null,
  failedSeen: {} as Record<string, boolean>,
  lastCoverage: null as number | null,
  lastSlots: {} as Record<string, string>,
  prevSlots: {} as Record<string, string>,
};

export const useRecoveryStore = create<RecoveryStore>((set, get) => ({
  phases: [],
  failures: [],
  assignments: [],
  ...initialInternal,

  ingest: (raw) => {
    rawSeen = true; // integrator wired the direct path — retire the bridge
    const msg = deserializeMessage(raw);
    if (msg === null) return; // malformed / unknown: dropped, never fatal (§18)
    if (msg.kind === "frame") {
      // INIT-derived empty state (cubesat/wire.py to_sim_state): a new run
      // started — clear the story with it. The simStore bridge used to do
      // this before the direct path was wired; now ingest owns the reset
      // (scenario switch / replay load must not inherit stale story data).
      if (msg.frame.satellites.length === 0 && msg.frame.simTime === 0) {
        get().resetForNewRun();
        return;
      }
      set((s) =>
        frameUpdate(s, {
          simTime: msg.frame.simTime,
          missionState: msg.frame.missionState,
          satellites: msg.frame.satellites,
          coverage: msg.frame.coverage,
          detectionLatencyS: msg.frame.metrics.detectionLatencyS ?? null,
        }),
      );
    } else if (msg.kind === "reassignment") {
      set((s) =>
        pushAssignment(s, {
          time: msg.reassignment.sim_time,
          rows: msg.reassignment.assignments.map((a) => ({
            satelliteId: a.satellite_id,
            targetSlot: a.target_slot ?? null,
            // Pre-tick slot (measured): the sim_state that just preceded this
            // message on the wire already carries the NEW slots, so the diff
            // source is the snapshot frameUpdate saved one frame earlier.
            prevSlot: s.prevSlots[a.satellite_id] ?? null,
          })),
          costTotal: msg.reassignment.cost_total ?? null,
        }),
      );
    }
    // hello / event carry no recovery facts (events live in simStore).
  },

  resetForNewRun: () =>
    set({
      phases: [],
      failures: [],
      assignments: [],
      ...initialInternal,
    }),
}));

// ---- simStore bridge -------------------------------------------------------
// Mirrors ingest() from state simStore already parsed via deserializeMessage
// (the ONE parser). Retires itself the first time ingest() is called.
let bridgeUnsubscribe: (() => void) | null = null;

function attachBridge(): void {
  if (bridgeUnsubscribe !== null) return;
  bridgeUnsubscribe = useSimStore.subscribe((s, prev) => {
    if (rawSeen) return;
    const st = useRecoveryStore.getState();
    // A fresh session (INIT-derived empty state / reset, cf. historyStore's
    // reset watch) clears the story with the rest of the console.
    if (
      s.satellites.length === 0 && s.missionState === null &&
      (st.phases.length > 0 || st.failures.length > 0 || st.assignments.length > 0)
    ) {
      st.resetForNewRun();
      return;
    }
    if (s.simTime === null) return; // nothing measured yet
    useRecoveryStore.setState(
      frameUpdate(st, {
        simTime: s.simTime,
        missionState: s.missionState,
        satellites: s.satellites,
        coverage: s.metrics.coverage ?? null,
        detectionLatencyS: s.metrics.detectionLatencyS ?? null,
      }),
    );
    const reassignment = s.lastReassignment;
    if (reassignment !== null && reassignment !== prev.lastReassignment) {
      useRecoveryStore.setState(
        pushAssignment(useRecoveryStore.getState(), {
          time: reassignment.simTime,
          rows: reassignment.rows.map((r) => ({
            satelliteId: r.satelliteId,
            targetSlot: r.targetSlot,
            // Bridge path cannot diff slots (simStore tracks roles only) and
            // is retired anyway once ingest() is wired — null is honest: no
            // measured pre-slot, so narration will not claim movement.
            prevSlot: null,
          })),
          costTotal: reassignment.costTotal,
        }),
      );
    }
  });
}
attachBridge();

// ---- selectors (plain readable snapshot; stable refs for zustand v5) -------

export const selectCurrentPhase = (s: RecoveryStore): RecoveryPhase | null =>
  s.phases.length > 0 ? s.phases[s.phases.length - 1] : null;

export const selectLatestFailure = (s: RecoveryStore): FailureRecord | null =>
  s.failures.length > 0 ? s.failures[s.failures.length - 1] : null;

export const selectLatestAssignment = (s: RecoveryStore): AssignmentEvent | null =>
  s.assignments.length > 0 ? s.assignments[s.assignments.length - 1] : null;

/** Latest tStart per mission state — seek targets for the §13.5 spine.
 * Memoized on the phases reference so the returned object is stable. */
const phaseStartsCache: { src: RecoveryPhase[]; starts: Record<string, number> } = {
  src: [],
  starts: {},
};
export const selectPhaseStarts = (s: RecoveryStore): Record<string, number> => {
  if (phaseStartsCache.src !== s.phases) {
    const starts: Record<string, number> = {};
    for (const p of s.phases) starts[p.state] = p.tStart; // later occurrences win
    phaseStartsCache.src = s.phases;
    phaseStartsCache.starts = starts;
  }
  return phaseStartsCache.starts;
};
