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
import { useSimStore } from "../../stores/simStore";
import { roleLabel } from "../live/hudFormat";
import { slotLabel } from "../recovery/RecoveryLog";
import { fitFormation, distanceToSeat } from "../../utils/geometry";
import chrome from "../../styles/chrome.module.css";
import styles from "./RoleTable.module.css";

export default function RoleTable() {
  const reassignment = useSimStore((s) => s.lastReassignment);
  const satellites = useSimStore((s) => s.satellites);

  if (reassignment === null) {
    return (
      <p className={chrome.hint}>
        No role changes yet. Roles are reassigned when a failure triggers a replan.
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
          <th scope="col" className={styles.th}>New slot</th>
          <th scope="col" className={styles.thRight}>Distance to slot</th>
        </tr>
      </thead>
      <tbody>
        {reassignment.rows.map((row) => {
          const sat = satellites.find((s) => s.id === row.satelliteId) ?? null;
          const dist = sat !== null ? distanceToSeat(sat, fit) : null;
          return (
            <tr key={row.satelliteId}>
              <td className={styles.cell}>{row.satelliteId}</td>
              <td className={styles.cell}>
                {row.oldRole !== null ? roleLabel(row.oldRole) : "unmeasured"}
                {row.newRole !== null && row.oldRole !== null && row.oldRole !== row.newRole && (
                  <span className={styles.changed}> changed</span>
                )}
              </td>
              <td className={styles.cell}>{row.newRole !== null ? roleLabel(row.newRole) : "unmeasured"}</td>
              <td className={styles.cell}>{row.targetSlot !== null ? slotLabel(row.targetSlot) : "unassigned"}</td>
              <td className={styles.numRight}>
                {dist === null ? "unmeasured" : `${dist.toFixed(1)} m`}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
