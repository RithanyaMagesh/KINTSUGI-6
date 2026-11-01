// Satellite types — FRONTEND_SPEC §15.1, mirrored on the backend wire
// (cubesat/wire.py to_sim_state/_sat_to_wire; units are SI at this boundary).

export type MissionState =
  | "NOMINAL"
  | "FAILURE_DETECTED"
  | "REPLANNING"
  | "RECONFIGURING"
  | "RECOVERED"
  | "DEGRADED";

export type SatelliteStatus =
  | "healthy"
  | "failed"
  | "reconfiguring"
  | "recovered"
  | "inactive"
  | "degraded";

export interface Satellite {
  id: string;
  role: string;
  status: SatelliteStatus;
  r: [number, number, number]; // LVLH position [m]: x radial, y along-track, z cross-track
  v: [number, number, number]; // velocity [m/s]
  dv_used: number; // Δv consumed [m/s]
  targetSlot?: string;
  failureType?: string; // "DEAD" | "THRUSTER_OUT" | "EPS_DEGRADE"
  risk?: number; // 0-1 failure-risk score — predictor-family frames only; omit when absent
  // Engine v2 only (absent on v1 runs): docs/frontend-requests.md "Roles" / "v2 statuses".
  roles?: string[]; // every role held, [] = none, ["spare"] = capable but idle
  originalRole?: string; // scenario label ("was imager")
  oldRole?: string; // previous frame's role, only on the tick it changed
  fuelKg?: number; // propellant left [kg]
  fuelMpsLeft?: number; // delta-v left [m/s]
  thrust?: number; // thrust health k: 1 full, 0.5 half, 0 none
  payloadOk?: boolean; // camera works
  radioOk?: boolean; // heartbeat works
  stuck?: boolean;
  /** Laser runs: leader functions this sat holds (decentral authority). */
  functions?: string[];
  /** Laser runs: alive but outside the main talking group (derived from `components`). */
  cutOff?: boolean; // thruster stuck open
}

/** The three mission states in the timeline-spine order (§13.5). */
export const STATE_SPINE: readonly MissionState[] = [
  "NOMINAL",
  "FAILURE_DETECTED",
  "REPLANNING",
  "RECONFIGURING",
  "RECOVERED",
] as const;

export function isMissionState(value: string): value is MissionState {
  return [
    "NOMINAL",
    "FAILURE_DETECTED",
    "REPLANNING",
    "RECONFIGURING",
    "RECOVERED",
    "DEGRADED",
  ].includes(value);
}
