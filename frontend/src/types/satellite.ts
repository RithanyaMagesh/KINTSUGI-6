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
