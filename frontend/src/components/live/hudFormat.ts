// Plain-language labels for the full-screen live HUD. The wire speaks in enum
// literals (cubesat/wire.py); people on the screen read these instead.
import type { MissionState, Satellite } from "../../types/satellite";

export const STATE_LABEL: Record<MissionState, string> = {
  NOMINAL: "Nominal",
  FAILURE_DETECTED: "Failure detected",
  REPLANNING: "Replanning",
  RECONFIGURING: "Moving to new slots",
  RECOVERED: "Recovered",
  DEGRADED: "Degraded",
};

/** The recovery sequence the phase rail walks through, in order. */
export const PHASES: ReadonlyArray<{ state: MissionState; label: string }> = [
  { state: "NOMINAL", label: "Nominal" },
  { state: "FAILURE_DETECTED", label: "Failure detected" },
  { state: "REPLANNING", label: "Replanning" },
  { state: "RECONFIGURING", label: "Moving to new slots" },
  { state: "RECOVERED", label: "Recovered" },
];

export function stateLabel(state: string | null): string {
  if (state === null) return "Standby";
  return (STATE_LABEL as Record<string, string>)[state] ?? state;
}

export function roleLabel(role: string): string {
  if (role === "leader") return "Leader";
  if (role === "downlink") return "Downlink";
  if (role === "none") return "No role";
  if (role.startsWith("sensor") || role.startsWith("imager")) return "Imager";
  return role.charAt(0).toUpperCase() + role.slice(1).replace(/_/g, " ");
}

export function statusLabel(status: string): string {
  switch (status) {
    case "failed":
      return "Lost";
    case "reconfiguring":
      return "Moving";
    case "recovered":
      return "Recovered";
    case "degraded":
      return "Battery fading";
    case "inactive":
      return "Inactive";
    default:
      return "Healthy";
  }
}

/** Every role a satellite holds (v2 stacks them), e.g. "Leader and imager". */
export function rolesLabel(sat: Satellite): string {
  const rs = sat.roles ?? [sat.role];
  if (rs.length === 0) return "No role";
  const words = rs.map(roleLabel);
  return [words[0], ...words.slice(1).map((w) => w.toLowerCase())].join(" and ");
}

/** One satellite's status in plain words. The v2 engine reports why a flying
 * satellite is degraded (failure_type); the wire status alone can't say. */
export function satLabel(sat: Satellite): string {
  switch (sat.failureType) {
    case "REENTERED":
      return "Re-entered";
    case "FUEL_DEPLETED":
      return "Out of fuel";
    case "PAYLOAD_FAILED":
      return "Camera failed";
    case "RADIO_SILENT":
      return "Radio silent";
  }
  if (sat.cutOff === true) return "Cut off"; // alive, but no laser link reaches it
  if (sat.stuck === true) return "Thruster stuck open";
  if (sat.thrust !== undefined && sat.thrust < 1 && sat.status !== "failed")
    return `${Math.round(sat.thrust * 100)}% thrust`;
  return statusLabel(sat.status);
}

export function faultLabel(f: string | undefined): string {
  if (f === undefined) return "";
  if (f === "PAYLOAD_FAIL" || f === "PAYLOAD_FAILED") return "Camera failure";
  if (f === "PARTIAL_THRUST") return "Partial thrust";
  if (f === "THRUSTER_STUCK_OPEN") return "Thruster stuck open";
  if (f === "RADIO_FAIL" || f === "RADIO_SILENT") return "Radio failure";
  if (f === "FUEL_DEPLETED") return "Out of fuel";
  if (f === "REENTERED") return "Re-entered";
  if (f === "DEAD") return "Dead";
  if (f === "THRUSTER_OUT") return "Thruster out";
  if (f === "EPS_DEGRADE" || f === "DEGRADED") return "Battery fade"; // wire sends the status
  return f;
}

/** Wire slot id "slot_2" -> "Slot 3" (slots are 0-based on the wire). */
export function slotLabel(slot: string | undefined | null): string {
  if (slot === undefined || slot === null) return "–";
  const n = Number(slot.replace("slot_", ""));
  return Number.isFinite(n) ? `Slot ${n + 1}` : slot;
}

/** Sim clock as h:mm:ss (or m:ss under an hour). */
export function clock(t: number | null): string {
  if (t === null) return "–";
  const s = Math.max(0, Math.floor(t));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

export function km(m: number, digits = 2): string {
  return (m / 1000).toFixed(digits);
}

/** Wire event text in plain words: "State A -> B" becomes "Now: <B>", and
 * fault/role enum words read as English. The meaning is unchanged. */
export function eventText(msg: string): string {
  const m = /^State\s+([A-Z_]+)\s*->\s*([A-Z_]+)/.exec(msg);
  if (m !== null) return `Now ${stateLabel(m[2]).toLowerCase()} (was ${stateLabel(m[1]).toLowerCase()})`;
  return msg
    .replace(/\bDEAD\b/g, "dead")
    .replace(/\bTHRUSTER_OUT\b/g, "thruster-out")
    .replace(/\bEPS_DEGRADE\b/g, "battery-fade")
    .replace(/\b(PAYLOAD_FAIL|PARTIAL_THRUST|THRUSTER_STUCK_OPEN|RADIO_FAIL|FUEL_DEPLETED|REENTERED|PAYLOAD_FAILED|RADIO_SILENT)\b/g, (w) =>
      faultLabel(w).toLowerCase(),
    );
}

/** Leader functions held by the consensus auction (decentral laser runs). */
export const FUNCTIONS = [
  "failure_detection",
  "time_sync",
  "formation_reference",
  "collision_arbitration",
  "task_scheduling",
  "ground_relay",
] as const;

const FUNCTION_LABEL: Record<string, string> = {
  failure_detection: "Detection",
  time_sync: "Time sync",
  formation_reference: "Formation reference",
  collision_arbitration: "Collision arbitration",
  task_scheduling: "Scheduling",
  ground_relay: "Ground relay",
};

export function functionLabel(f: string): string {
  return FUNCTION_LABEL[f] ?? f.charAt(0).toUpperCase() + f.slice(1).replace(/_/g, " ");
}

/** Plain words for a laser link state. */
export function linkLabel(state: string): string {
  return state === "LOCKED" ? "Locked" : state === "ACQUIRING" ? "Acquiring" : "Down";
}
