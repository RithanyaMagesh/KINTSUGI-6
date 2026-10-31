// Failure injection — POST /failure/inject {sat_id, mode}.
// Syncs with selectedSatelliteId when a satellite is clicked in the 3D view or
// fleet list so the operator can target and inject a fault in one click.
// Simplified view always injects DEAD; "More options" (Advanced view) adds the
// fault type choice.
import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { faultLabel, rolesLabel, satLabel } from "../live/hudFormat";
import chrome from "../../styles/chrome.module.css";
import styles from "./FailureInjectionPanel.module.css";

// Descriptions follow the engine's own (FailureMode docstrings). The last four
// exist only in the v2 engine; on a v1 run the server refuses them and its
// message is shown as is.
const MODES = [
  { id: "DEAD", desc: "Goes silent and drifts. The swarm notices within seconds and moves the survivors into new slots." },
  { id: "THRUSTER_OUT", desc: "Can't move any more; it reports the fault and the swarm replans." },
  { id: "EPS_DEGRADE", desc: "Power fades over the time you set, then it goes silent." },
  { id: "PAYLOAD_FAIL", desc: "Keeps flying but can no longer image. Needs the v2 engine." },
  { id: "PARTIAL_THRUST", desc: "Thrusters drop to half strength. No alarm is raised. Needs the v2 engine." },
  { id: "THRUSTER_STUCK_OPEN", desc: "A thruster fires nonstop until the tank is empty. No alarm is raised. Needs the v2 engine." },
  { id: "RADIO_FAIL", desc: "Keeps flying but goes silent. Needs the v2 engine." },
] as const;
type InjectMode = (typeof MODES)[number]["id"];

export default function FailureInjectionPanel() {
  const mode = useSimStore((s) => s.mode);
  const satellites = useSimStore((s) => s.satellites);
  const selectedSatelliteId = useUiStore((s) => s.selectedSatelliteId);
  const viewMode = useUiStore((s) => s.viewMode);
  const [satId, setSatId] = useState("");
  const [failureMode, setFailureMode] = useState<InjectMode>("DEAD");
  const [degradeS, setDegradeS] = useState(600.0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Follow a click in the 3D scene only when the selection changes, so a pick
  // made in the dropdown is not overwritten by the next frame.
  useEffect(() => {
    if (selectedSatelliteId !== null) setSatId(selectedSatelliteId);
  }, [selectedSatelliteId]);

  // Drop a target the current run no longer has (e.g. SAT-11 after a 6-sat restart),
  // then fall back to the first healthy satellite.
  useEffect(() => {
    if (satId !== "" && !satellites.some((s) => s.id === satId)) setSatId("");
    else if (satId === "" && satellites.length > 0) {
      const firstHealthy = satellites.find((s) => s.status !== "failed") ?? satellites[0];
      setSatId(firstHealthy.id);
    }
  }, [satellites, satId]);

  const effectiveMode: InjectMode = viewMode === "simplified" ? "DEAD" : failureMode;
  const live = mode === "live";
  const canInject = live && satellites.length > 0 && satId !== "" && !busy;

  async function inject() {
    setBusy(true);
    setError(null);
    try {
      await backend.failureInject(
        satId,
        effectiveMode,
        effectiveMode === "EPS_DEGRADE" ? degradeS : 0.0,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Injection failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.group}>
      <div className={styles.headRow}>
        <h2 className={chrome.panelTitle}>Fail a satellite</h2>
      </div>

      <div className={styles.row}>
        <label className={chrome.fieldLabel} htmlFor="inject-sat">
          Satellite (or click one in the 3D view)
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
              {`${s.id}, ${rolesLabel(s)}, ${satLabel(s)}`}
            </option>
          ))}
        </select>
      </div>

      {viewMode === "advanced" && (
        <>
          <div className={styles.row}>
            <label className={chrome.fieldLabel} htmlFor="inject-mode">
              Fault
            </label>
            <select
              id="inject-mode"
              className={chrome.select}
              value={failureMode}
              disabled={!live || busy}
              onChange={(e) => setFailureMode(e.target.value as InjectMode)}
            >
              {MODES.map((m) => (
                <option key={m.id} value={m.id}>
                  {faultLabel(m.id)}
                </option>
              ))}
            </select>
          </div>
          {failureMode === "EPS_DEGRADE" && (
            <div className={styles.row}>
              <label className={chrome.fieldLabel} htmlFor="inject-degrade-s">
                Fade time (s)
              </label>
              <input
                id="inject-degrade-s"
                className={chrome.input}
                type="number"
                min="0"
                step="10"
                value={degradeS}
                disabled={!live || busy}
                onChange={(e) => setDegradeS(Math.max(0, Number(e.target.value)))}
              />
            </div>
          )}
        </>
      )}

      <button
        type="button"
        className={`${chrome.btn} ${styles.injectBtn}`}
        disabled={!canInject}
        onClick={() => void inject()}
      >
        {busy ? "Failing…" : satId !== "" ? `Fail ${satId}` : "Fail a satellite"}
      </button>

      <p className={styles.modeHint}>
        {faultLabel(effectiveMode)}: {MODES.find((m) => m.id === effectiveMode)!.desc}
      </p>
      {!live && <p className={chrome.hint}>Start a live simulation above to fail satellites.</p>}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </div>
  );
}
