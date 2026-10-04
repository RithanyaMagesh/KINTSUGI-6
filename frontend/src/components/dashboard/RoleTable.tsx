// Role reallocation table — FRONTEND_SPEC §8.1: how roles changed after a
// failure. A real <table> with ordinary product styling (§13.3), fed by the
// role_reassignment wire message (cubesat/wire.py _role_reassignment).
// Column honesty (repo invariant 1):
//   old role      — derived from the previous frame's roles (simStore diff);
//                   the wire carries no old_role and none is invented
//   new role      — measured (message field)
//   target slot   — measured (message field)
//   distance      — derived from measured position vs the fitted seat
//                   (utils/geometry.ts); "unmeasured" when the fit is not
//                   possible
//   cost total    — measured only when the log carried cost_total; per-sat
//                   cost is not on the wire, so there is no per-row cost
//                   column rather than a column of invented numbers.
import { useSimStore } from "../../stores/simStore";
import { fitFormation, distanceToSeat } from "../../utils/geometry";
import chrome from "../../styles/chrome.module.css";
import styles from "./RoleTable.module.css";

export default function RoleTable() {
  const reassignment = useSimStore((s) => s.lastReassignment);
  const satellites = useSimStore((s) => s.satellites);

  if (reassignment === null) {
    return (
      <p className={chrome.hint}>
        No role changes yet — roles reassign when a failure triggers replanning.
      </p>
    );
  }

  // Distances are derived from the CURRENT frame's positions; rows whose
  // satellite is gone (or the fit failed) render unmeasured.
  const fit = fitFormation(satellites, Math.max(satellites.length, 1));

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col" className={styles.th}>Satellite</th>
          <th scope="col" className={styles.th}>Old role</th>
          <th scope="col" className={styles.th}>New role</th>
          <th scope="col" className={styles.th}>Target slot</th>
          <th scope="col" className={styles.thRight}>Distance to target</th>
        </tr>
      </thead>
      <tbody>
        {reassignment.rows.map((row) => {
          const sat = satellites.find((s) => s.id === row.satelliteId) ?? null;
          const dist = sat !== null ? distanceToSeat(sat, fit) : null;
          return (
            <tr key={row.satelliteId}>
              <td className={styles.mono}>{row.satelliteId}</td>
              <td className={styles.cell}>
                {row.oldRole ?? "unmeasured"}
                {row.newRole !== null && row.oldRole !== null && row.oldRole !== row.newRole && (
                  <span className={styles.changed}> changed</span>
                )}
              </td>
              <td className={styles.cell}>{row.newRole ?? "unmeasured"}</td>
              <td className={styles.mono}>{row.targetSlot ?? "unassigned"}</td>
              <td className={styles.monoRight}>
                {dist === null ? "unmeasured" : `${dist.toFixed(1)} m`}
              </td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={4} className={styles.footLabel}>Assignment cost total (t + {reassignment.simTime.toFixed(1)} s)</td>
          <td className={styles.footValue}>
            {reassignment.costTotal === null ? "unmeasured" : reassignment.costTotal.toFixed(2)}
          </td>
        </tr>
      </tfoot>
    </table>
  );
}
