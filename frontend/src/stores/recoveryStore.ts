// Recovery story store — accumulates the mission's recovery narrative.
// Every value here is measured (repo invariant 1). Shared deserializer intake.
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
  mode: string | null;
  tFail: number;
  detectionLatencyS: number | null;
  vacatedSlot: string | null;
  coverage: { pre: number | null; min: number | null; current: number | null };
  recovered: boolean;
}

export interface AssignmentEvent {
  time: number;
  rows: Array<{ satelliteId: string; targetSlot: string | null; prevSlot: string | null }>;
  costTotal: number | null;
}

interface RecoveryStore {
  phases: RecoveryPhase[];
  failures: FailureRecord[];
  assignments: AssignmentEvent[];
  degradedSats: string[];
  degradedInfo: Record<string, { tDegraded: number; degrade_s?: number }>;
  openPhaseState: string | null;
  failedSeen: Record<string, boolean>;
  lastCoverage: number | null;
  lastSlots: Record<string, string>;
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

function frameUpdate(s: RecoveryStore, f: FrameFacts): Partial<RecoveryStore> {
  const out: Partial<RecoveryStore> = {};
  // INIT-derived empty state (cubesat/wire.py to_sim_state): no story facts.
  if (f.satellites.length === 0 && f.simTime === 0) return out;

  if (f.missionState !== null && f.missionState !== s.openPhaseState) {
    const next = s.phases.slice();
    if (next.length > 0 && next[next.length - 1].tEnd === null) {
      next[next.length - 1] = { ...next[next.length - 1], tEnd: f.simTime };
    }
    next.push({ state: f.missionState, tStart: f.simTime, tEnd: null });
    if (next.length > MAX_PHASES) next.splice(0, next.length - MAX_PHASES);
    out.phases = next;
    out.openPhaseState = f.missionState;
  }

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
        ].slice(-MAX_FAILURES);
        failuresChanged = true;
      }
    } else if (failedSeen[sat.id]) {
      delete failedSeen[sat.id];
      seenChanged = true;
      if (sat.status === "healthy" || sat.status === "recovered") {
        for (let i = nextFailures.length - 1; i >= 0; i--) {
          if (nextFailures[i].satId === sat.id && !nextFailures[i].recovered) {
            const copy = nextFailures.slice();
            copy[i] = { ...copy[i], recovered: true };
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
      const min = f.coverage !== null ? (rec.coverage.min === null ? f.coverage : Math.min(rec.coverage.min, f.coverage)) : rec.coverage.min;
      const current = f.coverage !== null ? f.coverage : rec.coverage.current;
      if (min !== rec.coverage.min || current !== rec.coverage.current) changed = true;
      const isLast = i === copy.length - 1;
      if (isLast && rec.detectionLatencyS === null && f.detectionLatencyS !== null && rec.tFail < f.simTime) {
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

  // Track satellites in "degraded" status
  const degradedSats: string[] = [];
  const nextDegradedInfo = { ...s.degradedInfo };
  let degradedChanged = false;
  for (const sat of f.satellites) {
    if (sat.status === "degraded") {
      degradedSats.push(sat.id);
      if (!nextDegradedInfo[sat.id]) {
        nextDegradedInfo[sat.id] = { tDegraded: f.simTime, degrade_s: 600 };
        degradedChanged = true;
      }
    } else if (nextDegradedInfo[sat.id]) {
      delete nextDegradedInfo[sat.id];
      degradedChanged = true;
    }
  }
  if (degradedSats.length !== s.degradedSats.length || degradedSats.some((id, i) => id !== s.degradedSats[i])) {
    out.degradedSats = degradedSats;
  }
  if (degradedChanged) out.degradedInfo = nextDegradedInfo;

  out.prevSlots = s.lastSlots;
  let nextSlots = s.lastSlots;
  let slotsChanged = false;
  for (const sat of f.satellites) {
    if (sat.targetSlot !== undefined && nextSlots[sat.id] !== sat.targetSlot) {
      if (!slotsChanged) { nextSlots = { ...nextSlots }; slotsChanged = true; }
      nextSlots[sat.id] = sat.targetSlot;
    }
  }
  if (slotsChanged) out.lastSlots = nextSlots;
  if (f.coverage !== null && f.coverage !== s.lastCoverage) out.lastCoverage = f.coverage;
  return out;
}

function pushAssignment(s: RecoveryStore, event: AssignmentEvent): Partial<RecoveryStore> {
  return { assignments: [...s.assignments, event].slice(-MAX_ASSIGNMENTS) };
}

const initialInternal = {
  degradedSats: [] as string[],
  degradedInfo: {} as Record<string, { tDegraded: number; degrade_s?: number }>,
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
    if (typeof raw === "object" && raw !== null) {
      const rec = raw as Record<string, unknown>;
      const isSwap = rec.type === "ORACLE_SWAP" || (rec.type === "event" && typeof rec.message === "string" && rec.message.includes("ORACLE_SWAP"));
      if (isSwap) {
        const payload = typeof rec.payload === "object" && rec.payload !== null ? (rec.payload as Record<string, unknown>) : null;
        if (payload && typeof payload.from_sat === "number") {
          const satId = `SAT-${payload.from_sat + 1}`;
          const current = get();
          if (!current.degradedSats.includes(satId)) {
            set({
              degradedSats: [...current.degradedSats, satId],
              degradedInfo: { ...current.degradedInfo, [satId]: { tDegraded: typeof payload.t === "number" ? payload.t : 0, degrade_s: 600 } },
            });
          }
        }
      }
    }
    const msg = deserializeMessage(raw);
    if (msg === null) return; // malformed / unknown: dropped, never fatal (§18)
    if (msg.kind === "frame") {
      // INIT-derived empty state (cubesat/wire.py to_sim_state): a new run started
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
            prevSlot: s.prevSlots[a.satellite_id] ?? null,
          })),
          costTotal: msg.reassignment.cost_total ?? null,
        }),
      );
    }
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
let bridgeUnsubscribe: (() => void) | null = null;
function attachBridge(): void {
  if (bridgeUnsubscribe !== null) return;
  bridgeUnsubscribe = useSimStore.subscribe((s, prev) => {
    if (rawSeen) return;
    const st = useRecoveryStore.getState();
    if (
      s.satellites.length === 0 && s.missionState === null &&
      (st.phases.length > 0 || st.failures.length > 0 || st.assignments.length > 0)
    ) {
      st.resetForNewRun();
      return;
    }
    if (s.simTime === null) return;
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
            prevSlot: null,
          })),
          costTotal: reassignment.costTotal,
        }),
      );
    }
  });
}
attachBridge();

export const selectCurrentPhase = (s: RecoveryStore): RecoveryPhase | null =>
  s.phases.length > 0 ? s.phases[s.phases.length - 1] : null;
export const selectLatestFailure = (s: RecoveryStore): FailureRecord | null =>
  s.failures.length > 0 ? s.failures[s.failures.length - 1] : null;
export const selectLatestAssignment = (s: RecoveryStore): AssignmentEvent | null =>
  s.assignments.length > 0 ? s.assignments[s.assignments.length - 1] : null;

const phaseStartsCache = { src: [] as RecoveryPhase[], starts: {} as Record<string, number> };
export const selectPhaseStarts = (s: RecoveryStore): Record<string, number> => {
  if (phaseStartsCache.src !== s.phases) {
    const starts: Record<string, number> = {};
    for (const p of s.phases) starts[p.state] = p.tStart;
    phaseStartsCache.src = s.phases;
    phaseStartsCache.starts = starts;
  }
  return phaseStartsCache.starts;
};
export const selectDegradedSats = (s: RecoveryStore): string[] => s.degradedSats;
export const selectDegradedInfo = (
  s: RecoveryStore,
): Record<string, { tDegraded: number; degrade_s?: number }> => s.degradedInfo;
