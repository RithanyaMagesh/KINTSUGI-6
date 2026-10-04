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

/** Default role pattern for n seats: 1 leader, imagers in between, 1 downlink
 * (cubesat/cluster_import.py:145 builds the same shape; nominal.json roles). */
export function defaultRoles(n: number): Role[] {
  return [
    "leader",
    ...Array<Role>(Math.max(0, n - 2)).fill("imager"),
    "downlink",
  ];
}

/** Draft -> the scenario object. n_slots is roles.length by construction —
 * the validator requires formation.n_slots == len(roles) (scenario.py
 * _slots_match_roles), so the builder exposes one satellite count, not two
 * fields that can drift. Failure rows referencing removed seats are dropped
 * (sat_id >= n_sats would 422, scenario.py _failures_reference_existing_sats).
 * Schema defaults (recovery_enabled, detection, allocation, oracle) are
 * omitted so the backend defaults apply — no copied half-truths. */
export function buildScenario(
  n: BuilderNumbers,
  roles: Role[],
  failures: FailureRow[],
): Record<string, unknown> {
  return {
    name: n.name,
    seed: Math.max(0, Math.round(n.seed)),
    duration_s: n.durationS,
    dt_s: n.dtS,
    chief: { altitude_km: n.altitudeKm },
    formation: {
      n_slots: roles.length,
      radial_amp_km: n.radialAmpKm,
      phase_offset_deg: n.phaseOffsetDeg,
    },
    a_max_mps2: n.aMax,
    gains: { wn: n.wn, zeta: n.zeta },
    sensor: {
      fov_half_angle_deg: n.fovHalfAngleDeg,
      grid_step_km: n.gridStepKm,
      grid_extent_km: n.gridExtentKm,
    },
    roles: [...roles],
    failures: failures
      .filter((f) => Number.isInteger(f.satId) && f.satId >= 0 && f.satId < roles.length)
      .map((f) => ({ t: Math.max(0, f.t), sat_id: f.satId, mode: f.mode })),
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
