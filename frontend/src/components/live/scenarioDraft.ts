// Scenario draft -> POST /scenarios/upload body. Pure mapping, no React.
// Field-for-field cubesat/scenario.py (the schema authority — its pydantic
// validation runs server-side on upload, cubesat/api.py scenarios_upload);
// defaults are the committed reference scenario data/scenarios/nominal.json,
// never invented numbers (repo invariant 1).

export const ROLES = ["leader", "imager", "downlink"] as const;
export type Role = (typeof ROLES)[number];

export const FAILURE_MODES = ["DEAD", "THRUSTER_OUT"] as const;
export type FailureMode = (typeof FAILURE_MODES)[number];

/** One-line descriptions (cubesat/scenario.py FailureMode docstring). */
export const MODE_DESCRIPTION: Record<FailureMode, string> = {
  DEAD: "goes silent and coasts",
  THRUSTER_OUT: "keeps reporting but cannot maneuver",
};

/** Recovery policies sent as `policy` on /simulation/start. The backend field
 * is landing separately (cubesat/wire.py StartRequest has scenario/seed/speed
 * only today) — a 422 there falls back to starting without it (honest note in
 * the UI). Copy verbatim from the recovery-benchmark policy set. */
export const POLICIES = [
  {
    id: "hungarian",
    label: "Hungarian two-step assignment - the engine allocator",
  },
  {
    id: "even_split",
    label: "Even redistribution - benchmark policy, adapted from the RL paper baseline",
  },
  {
    id: "hungarian_keepout",
    label: "Hungarian + dead-sat keep-out - benchmark policy",
  },
] as const;
export type PolicyId = (typeof POLICIES)[number]["id"];

export interface FailureRow {
  /** React list identity only — never serialized. */
  key: number;
  /** 0-based seat index (cubesat/scenario.py Failure.sat_id; the log renders
   * it as SAT-{i + 1}, cubesat/wire.py display_sat_id). */
  satId: number;
  /** Failure time, sim seconds (Failure.t, ge=0). */
  t: number;
  mode: FailureMode;
}

export interface BuilderNumbers {
  name: string;
  seed: number;
  durationS: number;
  dtS: number;
  altitudeKm: number;
  radialAmpKm: number;
  phaseOffsetDeg: number;
  aMax: number;
  wn: number;
  zeta: number;
  fovHalfAngleDeg: number;
  gridStepKm: number;
  gridExtentKm: number;
}

/** The builder form's number state: BuilderNumbers minus name (chosen per
 * run) plus the start-time speed multiplier (cubesat/wire.py StartRequest,
 * default 100). */
export type NumberValues = Omit<BuilderNumbers, "name"> & { speed: number };

/** Per-field clamp ranges, one entry per NumberValues key. Every range
 * satisfies the pydantic model in cubesat/scenario.py WITH margin — a `gt`
 * bound gets a min strictly above the limit, an `lt` bound a max strictly
 * below — so a scenario built through buildScenario passes Scenario
 * validation by construction. Field-by-field against the model:
 *   seed        ge=0, int            -> min 0, rounded
 *   durationS   duration_s gt=0      -> min 1
 *   dtS         dt_s gt=0 le=10      -> min 0.1, max 10
 *   altitudeKm  altitude_km gt=160 lt=2000 -> min 200, max 1999 (the reported
 *               demo-blocker: the builder let 160 through; gt=160 rejects it)
 *   radialAmpKm radial_amp_km gt=0   -> min 0.1
 *   phaseOffsetDeg unconstrained (Formation default 0.0) -> no clamp
 *   aMax        a_max_mps2 gt=0      -> min 0.0001
 *   wn / zeta   Gains gt=0           -> min 0.0001 / 0.1
 *   fovHalfAngleDeg gt=0 le=45       -> min 0.1, max 45
 *   gridStepKm / gridExtentKm gt=0 -> min 0.1 / 1
 *   speed       StartRequest.speed gt=0 (cubesat/wire.py:48) -> min 1
 */
export const BOUNDS: Record<
  keyof NumberValues,
  { min?: number; max?: number; int?: boolean }
> = {
  seed: { min: 0, int: true },
  durationS: { min: 1 },
  dtS: { min: 0.1, max: 10 },
  altitudeKm: { min: 200, max: 1999 },
  radialAmpKm: { min: 0.1 },
  phaseOffsetDeg: {},
  aMax: { min: 0.0001 },
  wn: { min: 0.0001 },
  zeta: { min: 0.1 },
  fovHalfAngleDeg: { min: 0.1, max: 45 },
  gridStepKm: { min: 0.1 },
  gridExtentKm: { min: 1 },
  speed: { min: 1 },
};

/** Clamp one builder number into its validated range (BOUNDS). Non-finite
 * input falls to the min (or 0) so a NaN commit can never reach the wire. */
export function clampNumber(key: keyof NumberValues, v: number): number {
  const b = BOUNDS[key];
  if (!Number.isFinite(v)) return b.min ?? 0;
  let out = v;
  if (b.min !== undefined) out = Math.max(b.min, out);
  if (b.max !== undefined) out = Math.min(b.max, out);
  return b.int === true ? Math.round(out) : out;
}

/** Default role pattern for n seats: 1 leader, imagers in between, 1 downlink
 * (cubesat/cluster_import.py:145 builds the same shape; nominal.json roles). */
export function defaultRoles(n: number): Role[] {
  return [
    "leader",
    ...Array<Role>(Math.max(0, n - 2)).fill("imager"),
    "downlink",
  ];
}

/** Draft -> the scenario object. Every number passes through clampNumber
 * (BOUNDS), so the generated scenario satisfies cubesat/scenario.py's pydantic
 * constraints by construction — whatever the inputs allowed (the reported
 * demo-blocker was altitude_km=160 passing the form while gt=160 rejects it).
 * n_slots is roles.length by construction — the validator requires
 * formation.n_slots == len(roles) (scenario.py _slots_match_roles), so the
 * builder exposes one satellite count, not two fields that can drift. Failure
 * rows referencing removed seats are dropped (sat_id >= n_sats would 422,
 * scenario.py _failures_reference_existing_sats). Schema defaults
 * (recovery_enabled, detection, allocation, oracle) are omitted so the
 * backend defaults apply — no copied half-truths. */
export function buildScenario(
  n: BuilderNumbers,
  roles: Role[],
  failures: FailureRow[],
): Record<string, unknown> {
  return {
    name: n.name,
    seed: clampNumber("seed", n.seed),
    duration_s: clampNumber("durationS", n.durationS),
    dt_s: clampNumber("dtS", n.dtS),
    chief: { altitude_km: clampNumber("altitudeKm", n.altitudeKm) },
    formation: {
      n_slots: roles.length,
      radial_amp_km: clampNumber("radialAmpKm", n.radialAmpKm),
      phase_offset_deg: clampNumber("phaseOffsetDeg", n.phaseOffsetDeg),
    },
    a_max_mps2: clampNumber("aMax", n.aMax),
    gains: { wn: clampNumber("wn", n.wn), zeta: clampNumber("zeta", n.zeta) },
    sensor: {
      fov_half_angle_deg: clampNumber("fovHalfAngleDeg", n.fovHalfAngleDeg),
      grid_step_km: clampNumber("gridStepKm", n.gridStepKm),
      grid_extent_km: clampNumber("gridExtentKm", n.gridExtentKm),
    },
    roles: [...roles],
    failures: failures
      .filter((f) => Number.isInteger(f.satId) && f.satId >= 0 && f.satId < roles.length)
      .map((f) => ({
        t: Math.max(0, Number.isFinite(f.t) ? f.t : 0), // Failure.t ge=0
        sat_id: f.satId,
        mode: f.mode,
      })),
  };
}

/** Mirrors cubesat/api.py _sanitize_scenario_name ([A-Za-z0-9_-], <= 64) so
 * the name the UI decides is the name the backend keeps — no 422 round-trip
 * for a character the client could have cleaned. */
export function sanitizeName(raw: string): string {
  return raw
    .replace(/[^A-Za-z0-9_-]/g, "")
    .slice(0, 64);
}
