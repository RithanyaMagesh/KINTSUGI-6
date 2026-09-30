// Color-as-state mapping (§13.1): saturated color appears ONLY as semantics.
// Returns var() references — raw hex lives only in tokens.css (§13.1).
import type { MissionState } from "../types/satellite";

export function missionStateColor(state: MissionState | null): string {
  switch (state) {
    case "NOMINAL":
      return "var(--status-nominal)";
    case "FAILURE_DETECTED":
      return "var(--status-failed)";
    case "REPLANNING":
    case "RECONFIGURING":
      return "var(--status-caution)";
    case "RECOVERED":
      return "var(--status-info)";
    case "DEGRADED":
      return "var(--status-caution)";
    default:
      return "var(--ink-muted)";
  }
}

export function satelliteStatusColor(status: string): string {
  switch (status) {
    case "healthy":
      return "var(--status-nominal)";
    case "failed":
      return "var(--status-failed)";
    case "reconfiguring":
      return "var(--status-caution)";
    case "recovered":
      return "var(--status-info)";
    default:
      return "var(--ink-faint)";
  }
}

export function eventLevelColor(level: string): string {
  switch (level) {
    case "critical":
      return "var(--status-failed)";
    case "warning":
      return "var(--status-caution)";
    default:
      return "var(--status-info)";
  }
}
