// Satellite list — status as color AND text (§22 accessibility rule). The
// leader role renders in the leader token, always paired with the text label
// (§13.1). Rows come only from the live stream — none, no rows.
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { satelliteStatusColor } from "../../utils/colors";
import { formatMsPerS } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import styles from "./SatelliteList.module.css";

export default function SatelliteList() {
  const satellites = useSimStore((s) => s.satellites);
  const selectedSatelliteId = useUiStore((s) => s.selectedSatelliteId);
  const selectSatellite = useUiStore((s) => s.selectSatellite);

  if (satellites.length === 0) {
    return (
      <p className={chrome.hint}>
        No satellites — start a simulation or load a replay to see the swarm.
      </p>
    );
  }

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col" className={styles.th}>ID</th>
          <th scope="col" className={styles.th}>Role</th>
          <th scope="col" className={styles.th}>Status</th>
          <th scope="col" className={styles.thRight}>Δv used</th>
        </tr>
      </thead>
      <tbody>
        {satellites.map((sat) => (
          <tr
            key={sat.id}
            className={`${styles.row} ${sat.id === selectedSatelliteId ? styles.selected : ""}`}
            onClick={() => selectSatellite(sat.id)}
          >
            <td className={styles.mono}>{sat.id}</td>
            <td className={sat.role === "leader" ? styles.leader : styles.role}>{sat.role}</td>
            <td className={styles.status}>
              <span className={styles.dot} style={{ background: satelliteStatusColor(sat.status) }} />
              {sat.status}
              {sat.failureType !== undefined && (
                <span className={styles.failureType}> {sat.failureType}</span>
              )}
            </td>
            <td className={styles.monoRight}>{formatMsPerS(sat.dv_used)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
