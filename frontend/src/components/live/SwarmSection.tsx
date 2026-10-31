// Swarm fieldset for the builder: per-seat roles and phase offset (count,
// altitude and radius live in ScenarioBuilder's core fields).
import chrome from "../../styles/chrome.module.css";
import NumberField from "./NumberField";
import { ROLES, type NumberValues, type Role } from "./scenarioDraft";
import { roleLabel } from "./hudFormat";
import styles from "./LivePage.module.css";

interface Props {
  nSats: number;
  roles: Role[];
  building: boolean;
  nums: NumberValues;
  onRole: (seat: number, role: Role) => void;
  onNumber: (key: keyof NumberValues, v: number) => void;
}

export default function SwarmSection({
  nSats,
  roles,
  building,
  nums,
  onRole,
  onNumber,
}: Props) {
  const leaderCount = roles.filter((r) => r === "leader").length;
  const imagerCount = roles.filter((r) => r === "imager").length;
  const downlinkCount = roles.filter((r) => r === "downlink").length;

  const roleGrid = (
    <div className={styles.roleGrid} role="group" aria-labelledby="builder-roles-label">
      {roles.map((role, i) => (
        <div key={i} className={styles.roleCell}>
          <label className={styles.roleSeat} htmlFor={`builder-role-${i}`}>
            {`SAT-${i + 1}`}
          </label>
          <select
            id={`builder-role-${i}`}
            className={chrome.select}
            value={role}
            onChange={(e) => onRole(i, e.target.value as Role)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
        </div>
      ))}
    </div>
  );

  return (
    <fieldset className={styles.group} disabled={building}>
      <legend className={chrome.panelTitle}>Swarm</legend>
      <div className={styles.field}>
        <span className={chrome.fieldLabel} id="builder-roles-label">
          {`Role per satellite (${leaderCount} leader${leaderCount === 1 ? "" : "s"}, ${imagerCount} imager${imagerCount === 1 ? "" : "s"}, ${downlinkCount} downlink${downlinkCount === 1 ? "" : "s"})`}
        </span>
        {nSats <= 8 ? (
          roleGrid
        ) : (
          <details className={styles.advanced}>
            <summary className={styles.advancedSummary}>
              Set each satellite's role ({nSats} satellites)
            </summary>
            <div className={styles.roleScroll}>{roleGrid}</div>
          </details>
        )}
        <p className={chrome.hint}>
          The leader and downlink are the critical roles; imagers provide the coverage.
        </p>
      </div>
      <div className={styles.fieldGrid}>
        <NumberField
          id="builder-phase"
          label="Phase offset (deg)"
          value={nums.phaseOffsetDeg}
          onCommit={(v) => onNumber("phaseOffsetDeg", v)}
          step="15"
          tip="Rotates every slot around the formation by the same angle."
          disabled={building}
        />
      </div>
    </fieldset>
  );
}
