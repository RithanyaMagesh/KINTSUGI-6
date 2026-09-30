// Failure injection — POST /failure/inject {sat_id, mode}. The satellite id
// is the wire display id ("SAT-3"); the mode is the backend enum, sent as-is.
import { useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import chrome from "../../styles/chrome.module.css";
import styles from "./FailureInjectionPanel.module.css";

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
      </div>
      <button className={chrome.btn} disabled={!canInject} onClick={inject}>
        Inject failure
      </button>
      {!live && (
        <p className={chrome.hint}>Start a simulation to enable failure injection.</p>
      )}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </div>
  );
}
