// Telemetry types — FRONTEND_SPEC §15.1 / §16.1. SI at the wire; conversion
// to display units happens only in the view layer.

export interface Metrics {
  coverage: number; // instantaneous, 0-1 (null before first tick — render unmeasured)
  coverageAvg: number; // rolling orbit average
  formationDeviation: number; // [m]
  minSep: number; // [m]
  detectionLatencyS?: number; // t_detect − t_fail
  replanningLatencyMs?: number;
  missionHealthScore?: number; // derived, only from measured inputs
}

/** One deserialized simulation frame — serves live WS, replay, and logs alike. */
export interface SimFrame {
  simTime: number;
  missionState: string;
  scenario: string | null;
  seed: number | null;
  satellites: import("./satellite").Satellite[];
  coverage: number | null;
  minSep: number | null;
  metrics: Partial<Metrics>;
  /** Recovery policy the backend session reports on hello/sim_state (`policy`,
   * additive wire field). null/absent until the wire carries it — never
   * guessed (repo invariant 1); the UI renders "unmeasured" meanwhile. */
  policy?: string | null;
}

export type SimMode = "live" | "replay" | "stopped";

export type ConnectionState = "connected" | "reconnecting" | "disconnected";
