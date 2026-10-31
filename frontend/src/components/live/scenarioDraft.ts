// Scenario draft -> POST /scenarios/upload body + committed scenario presets.
// Pure mapping, no React. Field-for-field cubesat/scenario.py (the schema
// authority — its pydantic validation runs server-side on upload,
// cubesat/api.py scenarios_upload); defaults and presets are exact copies of
// the committed data/scenarios/*.json files, never invented numbers (repo
// invariant 1).

export const ROLES = ["leader", "imager", "downlink"] as const;
export type Role = (typeof ROLES)[number];

export const FAILURE_MODES = ["DEAD", "THRUSTER_OUT", "EPS_DEGRADE"] as const;
export type FailureMode = (typeof FAILURE_MODES)[number];

/** One-line descriptions (cubesat/scenario.py FailureMode docstring). */
export const MODE_DESCRIPTION: Record<string, string> = {
  DEAD: "goes silent and drifts",
  THRUSTER_OUT: "can't move any more; it reports the fault and the swarm replans",
  EPS_DEGRADE: "power fades, then it goes silent",
};

/** Recovery policies sent as `policy` on /simulation/start (cubesat/wire.py). */
export const POLICIES = [
  {
    id: "hungarian",
    label: "Best-fit reassignment (default)",
  },
  {
    id: "even_split",
    label: "Even spacing (comparison)",
  },
  {
    id: "hungarian_keepout",
    label: "Best-fit, avoiding the dead satellite (comparison)",
  },
] as const;
export type PolicyId = (typeof POLICIES)[number]["id"];

/** Supported satellite counts in the builder (2–8 standard + 12–50 larger-swarm
 * roadmap seats, §4). */
export const SAT_COUNT_OPTIONS = [2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 32, 50] as const;
export const MAX_SATS = 50;

export interface FailureRow {
  /** React list identity only — never serialized. */
  key: number;
  /** 0-based seat index (cubesat/scenario.py Failure.sat_id; the log renders
   * it as SAT-{i + 1}, cubesat/wire.py display_sat_id). */
  satId: number;
  /** Failure time, sim seconds (Failure.t, ge=0). */
  t: number;
  mode: FailureMode;
  degrade_s?: number;
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
 * satisfies the pydantic model in cubesat/scenario.py WITH margin. */
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

/** Clamp one builder number into its validated range (BOUNDS). */
export function clampNumber(key: keyof NumberValues, v: number): number {
  const b = BOUNDS[key];
  if (!Number.isFinite(v)) return b.min ?? 0;
  let out = v;
  if (b.min !== undefined) out = Math.max(b.min, out);
  if (b.max !== undefined) out = Math.min(b.max, out);
  return b.int === true ? Math.round(out) : out;
}

/** Default role pattern for n seats: 1 leader, imagers in between, 1 downlink. */
export function defaultRoles(n: number): Role[] {
  return [
    "leader",
    ...Array<Role>(Math.max(0, n - 2)).fill("imager"),
    "downlink",
  ];
}

/** Big-swarm sizing (measured with two DEAD failures, seed 42, see the
 * frontend commit): the 2:1 ellipse must grow with N or 24+ satellites sit
 * inside the 2 km keep-out, and the recovery planner needs nearby ring sizes
 * to clear the coasting dead satellites. Tested radial amplitudes, km. */
const BIG_SWARM_AMP_KM: Record<number, number> = { 24: 9, 32: 11.5, 50: 18.5 };
const BIG_SWARM_MIN = 12;

function bigSwarmAmpKm(n: number): number {
  return BIG_SWARM_AMP_KM[n] ?? Math.round(0.37 * n * 2) / 2;
}

/** Draft -> the scenario object. */
export function buildScenario(
  n: BuilderNumbers,
  roles: Role[],
  failures: FailureRow[],
): Record<string, unknown> {
  return {
    name: n.name,
    seed: clampNumber("seed", n.seed),
    // 40+ satellites: the live server precomputes the run under a 60 s limit
    // (cubesat/session.py); 7000 s (> 1 orbit) computes in ~30 s at N = 50.
    duration_s:
      roles.length >= 40
        ? Math.min(clampNumber("durationS", n.durationS), 7000)
        : clampNumber("durationS", n.durationS),
    dt_s: clampNumber("dtS", n.dtS),
    chief: { altitude_km: clampNumber("altitudeKm", n.altitudeKm) },
    formation: {
      n_slots: roles.length,
      radial_amp_km:
        roles.length >= BIG_SWARM_MIN
          ? Math.max(clampNumber("radialAmpKm", n.radialAmpKm), bigSwarmAmpKm(roles.length))
          : clampNumber("radialAmpKm", n.radialAmpKm),
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
    ...(roles.length >= BIG_SWARM_MIN
      ? {
          allocation: {
            amp_sweep: [1.0, 1.12, 0.9, 1.25, 0.8, 1.4],
            phase_sweep_deg: [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330],
          },
          safety: { evade_radius_m: 2000.0 },
        }
      : {}),
    failures: failures
      .filter((f) => Number.isInteger(f.satId) && f.satId >= 0 && f.satId < roles.length)
      .map((f) => {
        const row: Record<string, unknown> = {
          t: Math.max(0, Number.isFinite(f.t) ? f.t : 0),
          sat_id: f.satId,
          mode: f.mode,
        };
        if (f.mode === "EPS_DEGRADE") {
          row.degrade_s =
            f.degrade_s !== undefined && Number.isFinite(f.degrade_s)
              ? Math.max(0, f.degrade_s)
              : 600.0;
        }
        return row;
      }),
  };
}

/** Mirrors cubesat/api.py _sanitize_scenario_name ([A-Za-z0-9_-], <= 64). */
export function sanitizeName(raw: string): string {
  return raw
    .replace(/[^A-Za-z0-9_-]/g, "")
    .slice(0, 64);
}
