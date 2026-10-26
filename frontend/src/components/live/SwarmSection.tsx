// Swarm fieldset for the builder: satellite count (2–8 standard + 12–50
// roadmap swarms), per-seat role assignment, and formation geometry.
import chrome from "../../styles/chrome.module.css";
import NumberField from "./NumberField";
import {
  ROLES,
  SAT_COUNT_OPTIONS,
  type NumberValues,
  type Role,
} from "./scenarioDraft";
import styles from "./LivePage.module.css";

interface Props {
  nSats: number;
  roles: Role[];
  building: boolean;
  nums: NumberValues;
  onSats: (n: number) => void;
  onRole: (seat: number, role: Role) => void;
  onNumber: (key: keyof NumberValues, v: number) => void;
}

export default function SwarmSection({
  nSats,
  roles,
  building,
  nums,
  onSats,
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
                {r}
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
        <label className={chrome.fieldLabel} htmlFor="builder-sats">
          Satellites (slot count)
        </label>
        <select
          id="builder-sats"
          className={chrome.select}
          value={nSats}
          onChange={(e) => onSats(Number(e.target.value))}
        >
          {SAT_COUNT_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n <= 8 ? `${n} satellites` : `${n} satellites (large swarm)`}
            </option>
          ))}
        </select>
        <p className={chrome.hint}>
          n_slots equals the satellite count — the validator requires
          formation.n_slots == len(roles).
        </p>
      </div>
      <div className={styles.field}>
        <span className={chrome.fieldLabel} id="builder-roles-label">
          Role per seat ({leaderCount} leader · {imagerCount} imager · {downlinkCount} downlink)
        </span>
        {nSats <= 8 ? (
          roleGrid
        ) : (
          <details className={styles.advanced}>
            <summary className={styles.advancedSummary}>
              Customize individual seat roles ({nSats} seats)
            </summary>
            <div className={styles.roleScroll}>{roleGrid}</div>
          </details>
        )}
        <p className={chrome.hint}>
          leader and downlink are the critical seats; imagers carry the
          coverage (MASTER_PROMPT 3.3).
        </p>
      </div>
      <div className={styles.fieldGrid}>
        <NumberField
          id="builder-altitude"
          label="Chief altitude (km)"
          value={nums.altitudeKm}
          onCommit={(v) => onNumber("altitudeKm", v)}
          step="10"
          min="200"
          max="1999"
          tip="Circular chief altitude above Earth, km; 200 <= h <= 1999 (cubesat/scenario.py)."
          disabled={building}
        />
        <NumberField
          id="builder-radial"
          label="Radial amplitude (km)"
          value={nums.radialAmpKm}
          onCommit={(v) => onNumber("radialAmpKm", v)}
          step="0.5"
          min="0.1"
          tip="Radial amplitude of each drift-free 2:1 ellipse, km (cubesat/scenario.py Formation)."
          disabled={building}
        />
        <NumberField
          id="builder-phase"
          label="Phase offset (deg)"
          value={nums.phaseOffsetDeg}
          onCommit={(v) => onNumber("phaseOffsetDeg", v)}
          step="15"
          tip="Common phase offset of all slots, degrees (cubesat/scenario.py Formation)."
          disabled={building}
        />
      </div>
    </fieldset>
  );
}
