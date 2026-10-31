// Plain-language labels for the full-screen live HUD. The wire speaks in enum
// literals (cubesat/wire.py); people on the screen read these instead.
import type { MissionState } from "../../types/satellite";

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

export function faultLabel(f: string | undefined): string {
  if (f === undefined) return "";
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
    .replace(/\bEPS_DEGRADE\b/g, "battery-fade");
}
