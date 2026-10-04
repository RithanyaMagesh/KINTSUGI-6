// Deterministic, rule-based degradation detector over MEASURED frame history —
// the endgame plan's sanctioned "baseline detectors" fallback after the learned
// predictor was cut (docs/ENDGAME_PLAN.md P4, "ship the baseline" recipe fork).
//
// Physical motivation: a THRUSTER_OUT satellite keeps reporting heartbeats but
// cannot maneuver (cubesat/sim.py), so heartbeat failure detection never sees
// it — the only measured channel left is its MOTION: it coasts ballistically
// while the controlled swarm holds its seats, so its distance from the
// formation centroid grows frame over frame.
//
// The rule (every parameter measured, none invented):
//   1. Centroid of the HEALTHY satellites (>= 2 required) is the formation
//      reference; per-satellite centroid distance is measured each frame.
//   2. calmJitter = median |frame-over-frame delta| over healthy satellites —
//      the swarm's own per-frame motion scale. Measured on
//      data/logs/cascading_n8.jsonl (uv run python -m cubesat.run --scenario
//      data/scenarios/cascading_n8.json --seed 42): calm median 7.59 m/frame.
//   3. A satellite is ALARMED when its outward delta exceeds K x calmJitter.
//   4. SUSPECT requires M consecutive alarmed frames (the endgame plan's
//      M = 5-tick debounce for baseline detectors, ENDGAME_PLAN.md:168).
//   5. Gates, both measured: the satellite must still read healthy (suspect is
//      an annotation for pre-failure degradation, Appendix D), and the mission
//      must be holding formation (NOMINAL or RECOVERED) — during
//      FAILURE_DETECTED/REPLANNING/RECONFIGURING healthy satellites maneuver
//      hard on command (max healthy delta 4204 m/frame in cascading_n8.jsonl)
//      and outward motion is the recovery, not an anomaly.
// Validated on three committed logs (same command, seeds/scenarios as
// data/logs/*.jsonl): 0 false-alarm healthy satellite-frames on nominal.jsonl,
// single_failure_n4.jsonl and cascading_n8.jsonl.
//
// Pure functions: no RNG, no wall clock, no set/dict iteration order
// dependence (index/key iteration only). The caller (roleHistoryStore) folds
// frame -> SuspectTrackerState -> SuspectTrackerState through assessSuspects.

import type { Satellite } from "../types/satellite";

/** Rule parameters. K and M are pinned against the measured logs above — see
 * the validation note in the file header before touching them. */
export const SUSPECT_RULE = {
  /** Alarm threshold multiple of the calm per-frame jitter. */
  K: 2.5,
  /** Consecutive alarmed frames required (endgame plan M = 5 debounce). */
  M: 5,
  /** Frames of sustained alarm that score 1.0 (2 x M). */
  SCORE_FRAMES: 10,
  /** Delta multiple of the alarm threshold that scores 1.0. */
  SCORE_MAGNITUDE: 3,
} as const;

/** Mission states in which satellites hold their seats (uncommanded motion is
 * anomalous). Measured: the sim stays RECOVERED after a recovery — it never
 * returns to NOMINAL (data/logs/cascading_n8.jsonl mission sequence). */
const HOLDING_STATES: ReadonlySet<string> = new Set(["NOMINAL", "RECOVERED"]);

export interface SuspectVerdict {
  suspect: boolean;
  /** 0-1 evidence strength: magnitude and duration of the outward drift. */
  score: number;
  /** Explainable, measured reason; "" when not suspect. */
  reason: string;
}

/** Fold state — plain data the caller stores and feeds back verbatim. */
export interface SuspectTrackerState {
  lastSimTime: number | null;
  prevDist: Record<string, number> | null;
  /** Consecutive alarmed frames per satellite id. */
  streaks: Record<string, number>;
}

export interface SuspectResult {
  /** Verdict per satellite id present in the current frame. */
  verdicts: Record<string, SuspectVerdict>;
  state: SuspectTrackerState;
}

const NOT_SUSPECT: SuspectVerdict = { suspect: false, score: 0, reason: "" };

/** Sim-time jump (seek, stall) beyond which the frame pair is not a valid
 * frame-over-frame sample. Committed logs tick at dt = 2 s (measured in
 * data/logs/*.jsonl); 3 ticks of discontinuity restarts the tracker. */
const GAP_RESET_S = 6.0;

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function median(values: number[]): number {
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Centroid of the healthy satellites and per-satellite distances. null when
 * fewer than 2 healthy satellites — no formation reference exists. */
function measureDistances(
  sats: Satellite[],
): { dist: Record<string, number>; centroid: [number, number, number] } | null {
  const healthy = sats.filter((s) => s.status === "healthy");
  if (healthy.length < 2) return null;
  const centroid: [number, number, number] = [0, 0, 0];
  for (const sat of healthy) {
    centroid[0] += sat.r[0];
    centroid[1] += sat.r[1];
    centroid[2] += sat.r[2];
  }
  centroid[0] /= healthy.length;
  centroid[1] /= healthy.length;
  centroid[2] /= healthy.length;
  const dist: Record<string, number> = {};
  for (const sat of sats) {
    dist[sat.id] = Math.hypot(
      sat.r[0] - centroid[0],
      sat.r[1] - centroid[1],
      sat.r[2] - centroid[2],
    );
  }
  return { dist, centroid };
}

/** One pure fold step: current frame + previous fold state -> verdicts and the
 * next state. A rewind (sim time moved backwards, e.g. a replay seek) restarts
 * the tracker from the new cursor instead of folding a stale delta. */
export function assessSuspects(
  sats: Satellite[],
  missionState: string | null,
  simTime: number,
  prev: SuspectTrackerState | null,
): SuspectResult {
  const rewound =
    prev !== null &&
    prev.lastSimTime !== null &&
    (simTime < prev.lastSimTime || simTime - prev.lastSimTime > GAP_RESET_S);
  const state: SuspectTrackerState =
    prev === null || rewound ? { lastSimTime: null, prevDist: null, streaks: {} } : prev;

  if (sats.length === 0) {
    return { verdicts: {}, state: { lastSimTime: simTime, prevDist: null, streaks: {} } };
  }

  const measured = measureDistances(sats);
  const verdicts: Record<string, SuspectVerdict> = {};
  const nextStreaks: Record<string, number> = {};

  if (measured === null) {
    // No formation reference (mass failure): no alarm evidence this frame.
    return { verdicts: {}, state: { lastSimTime: simTime, prevDist: null, streaks: {} } };
  }

  // Calm scale: the healthy satellites' own frame-over-frame motion. Requires
  // >= 2 healthy satellites with a valid previous distance.
  const healthyDeltas: number[] = [];
  for (const sat of sats) {
    if (sat.status !== "healthy") continue;
    const prevDist = state.prevDist?.[sat.id];
    if (prevDist === undefined) continue;
    healthyDeltas.push(Math.abs(measured.dist[sat.id] - prevDist));
  }
  const calmJitter = healthyDeltas.length >= 2 ? median(healthyDeltas) : null;
  const holding = missionState !== null && HOLDING_STATES.has(missionState);

  for (const sat of sats) {
    const prevDist = state.prevDist?.[sat.id];
    const streak = state.streaks[sat.id] ?? 0;
    const delta = prevDist === undefined ? null : measured.dist[sat.id] - prevDist;

    let verdict = NOT_SUSPECT;
    if (delta !== null && calmJitter !== null && calmJitter > 0) {
      const alarmed = delta > SUSPECT_RULE.K * calmJitter;
      const nextStreak = alarmed ? streak + 1 : 0;
      nextStreaks[sat.id] = nextStreak;
      if (alarmed && holding && sat.status === "healthy" && nextStreak >= SUSPECT_RULE.M) {
        const threshold = SUSPECT_RULE.K * calmJitter;
        const magScore = clamp01(
          (delta / threshold - 1) / (SUSPECT_RULE.SCORE_MAGNITUDE - 1),
        );
        const durScore = clamp01(nextStreak / SUSPECT_RULE.SCORE_FRAMES);
        verdict = {
          suspect: true,
          score: clamp01(Math.max(magScore, durScore)),
          reason:
            `Distance from the formation centroid grew ${delta.toFixed(1)} m ` +
            `over one frame against calm swarm motion of ${calmJitter.toFixed(1)} m ` +
            `(> ${SUSPECT_RULE.K}x, ${nextStreak} consecutive frames) while the ` +
            `satellite still reports healthy`,
        };
      }
    } else {
      nextStreaks[sat.id] = 0;
    }
    verdicts[sat.id] = verdict;
  }

  return {
    verdicts,
    state: { lastSimTime: simTime, prevDist: measured.dist, streaks: nextStreaks },
  };
}
