// Satellite list — status as color AND text (§22 accessibility rule). The
// leader role renders in the leader token, always paired with the text label
// (§13.1). Rows come only from the live stream — none, no rows.
// The optional per-satellite risk field renders only when a frame actually
// carries it (the Risk column exists for that frame — nothing is invented).
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { faultLabel, rolesLabel, satLabel, statusLabel } from "../live/hudFormat";
import { satelliteStatusColor } from "../../utils/colors";
import { formatMsPerS } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import styles from "./SatelliteList.module.css";
import type { Satellite } from "../../types/satellite";

export default function SatelliteList() {
  const satellites = useSimStore((s) => s.satellites);
  const selectedSatelliteId = useUiStore((s) => s.selectedSatelliteId);
  const selectSatellite = useUiStore((s) => s.selectSatellite);

  // Appendix D: the risk column renders only while the current frame carries
  // risk values (predictor-family frames); absent — the column does not exist.
  const riskOnWire = satellites.some((sat) => sat.risk !== undefined);

  if (satellites.length === 0) {
    return <p className={chrome.hint}>No satellite data received.</p>; // §24.3 verbatim
  }

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col" className={styles.th}>Satellite</th>
          <th scope="col" className={styles.th}>Role</th>
          <th scope="col" className={styles.th}>Status</th>
          {riskOnWire && <th scope="col" className={styles.thRight}>AI risk</th>}
          <th scope="col" className={styles.thRight}>Fuel spent</th>
        </tr>
      </thead>
      <tbody>
        {satellites.map((sat) => (
          <SatelliteRow
            key={sat.id}
            sat={sat}
            selected={sat.id === selectedSatelliteId}
            showRisk={riskOnWire}
            onSelect={selectSatellite}
          />
        ))}
      </tbody>
    </table>
  );
}

/** One selectable row. */
function SatelliteRow(props: {
  sat: Satellite;
  selected: boolean;
  showRisk: boolean;
  onSelect: (id: string) => void;
}) {
  const sat = props.sat;

  return (
    <tr
      className={`${styles.row} ${props.selected ? styles.selected : ""}`}
      tabIndex={0}
      // aria-selected is only valid inside role=grid/treegrid; aria-current is
      // the supported selection signal for a plain table row.
      aria-current={props.selected ? "true" : undefined}
      onClick={() => props.onSelect(sat.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          props.onSelect(sat.id);
        }
      }}
    >
      <td className={styles.id}>{sat.id}</td>
      <td className={sat.role === "leader" ? styles.leader : styles.role}>{rolesLabel(sat)}</td>
      <td className={styles.status}>
        <span className={styles.dot} style={{ background: satelliteStatusColor(sat.status) }} />
        {satLabel(sat)}
        {sat.failureType !== undefined && satLabel(sat) === statusLabel(sat.status) && (
          <span className={styles.failureType}> ({faultLabel(sat.failureType)})</span>
        )}
      </td>
      {props.showRisk && (
        // Column alignment: an empty cell keeps the row's columns aligned when
        // this satellite's frame row carries no risk (nothing is rendered).
        <td className={styles.numRight}>
          {sat.risk !== undefined ? sat.risk.toFixed(2) : ""}
        </td>
      )}
      <td className={styles.numRight}>{formatMsPerS(sat.dv_used)}</td>
    </tr>
  );
}
