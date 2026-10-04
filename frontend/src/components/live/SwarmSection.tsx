// Swarm fieldset for the builder (extracted to keep ScenarioBuilder under the
// ~300-line style rule): satellite count, per-seat role assignment, and the
// formation numbers. The count IS n_slots — the validator requires
// formation.n_slots == len(roles) (cubesat/scenario.py _slots_match_roles), so
// the builder exposes one control, not two that can drift. Roles are the
// engine's vocabulary (cubesat/sim.py: "imager" carries coverage; "leader" /
// "downlink" are the critical seats, MASTER_PROMPT 3.3).
import chrome from "../../styles/chrome.module.css";
import NumberField from "./NumberField";
import { ROLES, type NumberValues, type Role } from "./scenarioDraft";
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
          {[2, 3, 4, 5, 6, 7, 8].map((n) => (
            <option key={n} value={n}>
              {n}
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
          Role per seat
        </span>
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
          min="160"
          max="2000"
          tip="Circular chief altitude above Earth, km; 160 < h < 2000 (cubesat/scenario.py)."
          disabled={building}
        />
        <NumberField
          id="builder-radial"
          label="Radial amplitude (km)"
          value={nums.radialAmpKm}
          onCommit={(v) => onNumber("radialAmpKm", v)}
          step="1"
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
