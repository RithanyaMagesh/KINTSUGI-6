// Mission health score — FRONTEND_SPEC §8.7:
//   health = 0.5 * coverage + 0.3 * formation_quality + 0.2 * safety
// Computed ONLY from measured inputs (the wire stream + the geometry fit in
// geometry.ts); when a term has no data the whole score is null and the UI
// renders "unmeasured" (repo invariant 1). No scenario constants are used —
// normalizers come from the swarm's own measured geometry:
//   formation_quality = 1 - min(1, deviation / (2A))
//     (deviation normalised by the measured formation extent 2A: a satellite
//     displaced by the full formation size = zero formation quality)
//   safety = min(1, minSep / minSepRef)
//     (minSepRef = the first measured min_sep of the session — the swarm's own
//     healthy clearance, not an invented threshold)

export interface HealthInputs {
  coverage: number | null;
  deviation: number | null; // mean seat deviation [m] (geometry.ts fit)
  amplitude: number; // fit ellipse amplitude A [m]
  minSep: number | null; // [m]
  minSepRef: number | null; // first measured min_sep of the session [m]
}

export function missionHealthScore(inputs: HealthInputs): number | null {
  const { coverage, deviation, amplitude, minSep, minSepRef } = inputs;
  if (coverage === null || deviation === null || minSep === null || minSepRef === null) {
    return null;
  }
  if (amplitude <= 0 || minSepRef <= 0) return null;

  const formationQuality = 1 - Math.min(1, deviation / (2 * amplitude));
  const safety = Math.min(1, minSep / minSepRef);
  const score = 0.5 * coverage + 0.3 * formationQuality + 0.2 * safety;
  if (!Number.isFinite(score)) return null;
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

/** §8.7 colour bands mapped onto §13.1 tokens (the palette defines no orange,
 * so §8.7's 40-59 orange band collapses into --status-caution; §13.1 wins). */
export function healthBand(score: number): "nominal" | "caution" | "failed" {
  if (score >= 80) return "nominal";
  if (score >= 40) return "caution";
  return "failed";
}
