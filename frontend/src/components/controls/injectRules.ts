// Which satellites the backend will accept a failure on (cubesat/session.py
// inject_failure). Copying its checks here means the panel offers only what
// works instead of letting the server refuse it.
import type { Satellite } from "../../types/satellite";

export const V1_MODES = ["DEAD", "THRUSTER_OUT", "EPS_DEGRADE"] as const;
export const V2_MODES = [...V1_MODES, "PAYLOAD_FAIL", "PARTIAL_THRUST", "THRUSTER_STUCK_OPEN", "RADIO_FAIL"] as const;
export type InjectMode = (typeof V2_MODES)[number];

/** v2 frames carry per-satellite fuel; v1 frames never do. */
export const isV2 = (sats: Satellite[]) => sats.some((s) => s.fuelMpsLeft !== undefined);

/** Why the backend would refuse a failure on this satellite, or null if it accepts.
 * v1: any satellite that has already failed (409 "already failed").
 * v2: only dead or re-entered ones; a satellite that lost a part can fail again. */
export function injectBlock(sat: Satellite, v2: boolean): string | null {
  if (sat.status === "failed")
    return sat.failureType === "REENTERED" ? "re-entered" : sat.failureType === "THRUSTER_OUT" ? "thruster out" : "lost";
  if (!v2 && sat.failureType !== undefined) return "already failed";
  return null;
}
