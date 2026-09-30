// Selected satellite detail panel — FRONTEND_SPEC §7.7. Every value comes
// from the live stream; "distance to target" is derived from measured
// positions vs the fitted seat reference (utils/geometry.ts) and renders
// "unmeasured" when the fit is not possible (repo invariant 1).
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { distanceToSeat, fitFormation } from "../../utils/geometry";
import { satelliteStatusColor } from "../../utils/colors";
import { formatMsPerS } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import styles from "./SelectedSatellitePanel.module.css";

function Vec({ label, v, unit }: { label: string; v: [number, number, number]; unit: string }) {
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <span className={styles.mono}>
        [{v.map((c) => c.toFixed(1)).join(", ")}] {unit}
      </span>
    </div>
  );
}

export default function SelectedSatellitePanel() {
  const satellites = useSimStore((s) => s.satellites);
  const selectedId = useUiStore((s) => s.selectedSatelliteId);
  const sat = satellites.find((s) => s.id === selectedId) ?? null;

  if (sat === null) {
    return (
      <p className={chrome.hint}>
        Select a satellite in the swarm view or the satellite list to see its
        details.
      </p>
    );
  }

  const fit = fitFormation(satellites, Math.max(satellites.length, 1));
  const dist = distanceToSeat(sat, fit);

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.id}>{sat.id}</span>
        <span className={styles.status} style={{ color: satelliteStatusColor(sat.status) }}>
          {sat.status.toUpperCase()}
          {sat.failureType !== undefined ? ` · ${sat.failureType}` : ""}
        </span>
      </div>
      <div className={styles.row}>
        <span className={styles.label}>Role</span>
        <span className={styles.mono}>{sat.role}</span>
      </div>
      <Vec label="Position r (radial, along-track, cross-track)" v={sat.r} unit="m" />
      <Vec label="Velocity v" v={sat.v} unit="m/s" />
      <div className={styles.row}>
        <span className={styles.label}>Δv used</span>
        <span className={styles.mono}>{formatMsPerS(sat.dv_used)}</span>
      </div>
      <div className={styles.row}>
        <span className={styles.label}>Assigned target slot</span>
        <span className={styles.mono}>{sat.targetSlot ?? "unassigned"}</span>
      </div>
      <div className={styles.row}>
        <span className={styles.label}>Distance to target</span>
        <span className={styles.mono}>
          {dist === null ? "unmeasured" : `${dist.toFixed(1)} m`}
        </span>
      </div>
      {sat.risk !== undefined && (
        <div className={styles.row}>
          <span className={styles.label}>Risk</span>
          <span className={styles.mono}>{sat.risk.toFixed(2)}</span>
        </div>
      )}
    </div>
  );
}
