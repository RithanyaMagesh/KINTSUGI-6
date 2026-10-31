// Telemetry drawer — every satellite, every field the stream carries, one
// row each. Positions/velocities are LVLH relative to the chief (x radial,
// y along-track, z cross-track), converted from SI only here at the edge.
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { satelliteStatusColor } from "../../utils/colors";
import { km, rolesLabel, satLabel, slotLabel } from "./hudFormat";
import { FuelBar, SatFlags } from "./SatBits";
import styles from "./ImmersiveLive.module.css";

export default function FleetTable() {
  const sats = useSimStore((s) => s.satellites);
  const selected = useUiStore((s) => s.selectedSatelliteId);
  const select = useUiStore((s) => s.selectSatellite);

  if (sats.length === 0) {
    return <p className={styles.empty}>No satellites yet. Start a run from Setup.</p>;
  }
  const hasRisk = sats.some((s) => s.risk !== undefined);
  const v2 = sats.some((s) => s.fuelMpsLeft !== undefined);

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className={styles.srOnly}>Per-satellite state, relative to the chief</caption>
        <thead>
          <tr>
            <th scope="col">Satellite</th>
            <th scope="col">Status</th>
            <th scope="col">{v2 ? "Fuel left m/s" : "Fuel spent m/s"}</th>
            <th scope="col" className={styles.num}>Range km</th>
            <th scope="col" className={styles.num}>Radial</th>
            <th scope="col" className={styles.num}>Along</th>
            <th scope="col" className={styles.num}>Cross</th>
            <th scope="col" className={styles.num}>Speed m/s</th>
            <th scope="col">Slot</th>
            {hasRisk && <th scope="col" className={styles.num}>Risk</th>}
          </tr>
        </thead>
        <tbody>
          {sats.map((s) => {
            const range = Math.hypot(s.r[0], s.r[1], s.r[2]);
            const speed = Math.hypot(s.v[0], s.v[1], s.v[2]);
            return (
              <tr
                key={s.id}
                data-selected={s.id === selected || undefined}
                onClick={() => select(s.id === selected ? null : s.id)}
              >
                <th scope="row">
                  <span className={styles.satId}>{s.id}</span>
                  <span className={styles.satRole}>{rolesLabel(s)}</span>
                </th>
                <td>
                  <span className={styles.statusPip} style={{ background: satelliteStatusColor(s.status) }} aria-hidden="true" />
                  {satLabel(s)}
                  <SatFlags sat={s} />
                  {s.failureType === "THRUSTER_OUT" && s.status !== "failed" && <span className={styles.fault}>Thruster out</span>}
                </td>
                <td><FuelBar sat={s} compact /></td>
                <td className={styles.num}>{km(range)}</td>
                <td className={styles.num}>{km(s.r[0])}</td>
                <td className={styles.num}>{km(s.r[1])}</td>
                <td className={styles.num}>{km(s.r[2])}</td>
                <td className={styles.num}>{speed.toFixed(2)}</td>
                <td>{slotLabel(s.targetSlot)}</td>
                {hasRisk && <td className={styles.num}>{s.risk === undefined ? "–" : s.risk.toFixed(2)}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
