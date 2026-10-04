// Failure injection — POST /failure/inject {sat_id, mode}. The satellite id
// is the wire display id ("SAT-3"); the mode is the backend enum, sent as-is.
// Mode descriptions follow docs/MASTER_PROMPT.md 3.3 (DEAD: no comms, no
// thrust, coasts ballistically; THRUSTER_OUT: reports, cannot maneuver). The
// Inject button carries caution (amber) semantics; no confirmation dialog —
// demo speed — but the label names the action and the object (§13.3).
import { useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import chrome from "../../styles/chrome.module.css";
import styles from "./FailureInjectionPanel.module.css";

const MODE_DESCRIPTIONS: Record<"DEAD" | "THRUSTER_OUT", string> = {
  DEAD: "Goes silent and coasts.",
  THRUSTER_OUT: "Keeps reporting but cannot maneuver.",
};

export default function FailureInjectionPanel() {
  const mode = useSimStore((s) => s.mode);
  const satellites = useSimStore((s) => s.satellites);
  const [satId, setSatId] = useState("");
  const [failureMode, setFailureMode] = useState<"DEAD" | "THRUSTER_OUT">("DEAD");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const live = mode === "live";
  const canInject = live && satellites.length > 0 && satId !== "" && !busy;

  async function inject() {
    setBusy(true);
    setError(null);
    try {
      await backend.failureInject(satId, failureMode);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Injection failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.group}>
      <h3 className={styles.subTitle}>Failure injection</h3>
      <div className={styles.row}>
        <label className={chrome.fieldLabel} htmlFor="inject-sat">
          Satellite
        </label>
        <select
          id="inject-sat"
          className={chrome.select}
          value={satId}
          disabled={!live || satellites.length === 0 || busy}
          onChange={(e) => setSatId(e.target.value)}
        >
          <option value="">Select satellite…</option>
          {satellites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.row}>
        <label className={chrome.fieldLabel} htmlFor="inject-mode">
          Mode
        </label>
        <select
          id="inject-mode"
          className={chrome.select}
          value={failureMode}
          disabled={!live || busy}
          onChange={(e) => setFailureMode(e.target.value as "DEAD" | "THRUSTER_OUT")}
        >
          <option value="DEAD">DEAD</option>
          <option value="THRUSTER_OUT">THRUSTER_OUT</option>
        </select>
        <p className={styles.modeHint}>{MODE_DESCRIPTIONS[failureMode]}</p>
      </div>
      <button className={`${chrome.btn} ${styles.injectBtn}`} disabled={!canInject} onClick={inject}>
        Inject failure
      </button>
      {!live && <p className={chrome.hint}>Start a simulation to enable failure injection.</p>}
      {live && satellites.length === 0 && (
        <p className={chrome.hint}>Waiting for the first live frame.</p>
      )}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </div>
  );
}
