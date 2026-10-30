// Failure injection — POST /failure/inject {sat_id, mode}.
// Syncs with selectedSatelliteId when a satellite is clicked in the 3D view or
// fleet list so the operator can target and inject a fault in one click.
// In Simplified mode, injects DEAD (which triggers autonomous 3-heartbeat
// detection and Hungarian slot reassignment). In Advanced mode, allows choosing
// DEAD or THRUSTER_OUT with an honest explanation of heartbeat behavior.
import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import chrome from "../../styles/chrome.module.css";
import styles from "./FailureInjectionPanel.module.css";

const MODE_DESCRIPTIONS: Record<"DEAD" | "THRUSTER_OUT" | "EPS_DEGRADE", string> = {
  DEAD: "Stops heartbeats and thrust — triggers autonomous detection (4 s) and Hungarian slot recovery.",
  THRUSTER_OUT: "Keeps sending heartbeats but cannot maneuver (reactive heartbeat detector does not replan).",
  EPS_DEGRADE: "Gradual power degradation — triggers proactive role handoff before complete failure.",
};

export default function FailureInjectionPanel() {
  const mode = useSimStore((s) => s.mode);
  const satellites = useSimStore((s) => s.satellites);
  const selectedSatelliteId = useUiStore((s) => s.selectedSatelliteId);
  const viewMode = useUiStore((s) => s.viewMode);
  const [satId, setSatId] = useState("");
  const [failureMode, setFailureMode] = useState<"DEAD" | "THRUSTER_OUT" | "EPS_DEGRADE">("DEAD");
  const [degradeS, setDegradeS] = useState(600.0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Sync target dropdown when the operator clicks a satellite in the 3D scene
  useEffect(() => {
    if (selectedSatelliteId !== null && satellites.some((s) => s.id === selectedSatelliteId)) {
      setSatId(selectedSatelliteId);
    } else if (satId === "" && satellites.length > 0) {
      const firstHealthy = satellites.find((s) => s.status !== "failed") ?? satellites[0];
      setSatId(firstHealthy.id);
    }
  }, [selectedSatelliteId, satellites, satId]);

  const effectiveMode = viewMode === "simplified" ? "DEAD" : failureMode;
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
        <h2 className={chrome.panelTitle}>Live fault injection</h2>
      </div>

      <div className={styles.row}>
        <label className={chrome.fieldLabel} htmlFor="inject-sat">
          Target satellite (or click in 3D view)
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
              {s.id} ({s.role} · {s.status})
            </option>
          ))}
        </select>
      </div>

      {viewMode === "advanced" && (
        <>
          <div className={styles.row}>
            <label className={chrome.fieldLabel} htmlFor="inject-mode">
              Failure mode
            </label>
            <select
              id="inject-mode"
              className={chrome.select}
              value={failureMode}
              disabled={!live || busy}
              onChange={(e) =>
                setFailureMode(e.target.value as "DEAD" | "THRUSTER_OUT" | "EPS_DEGRADE")
              }
            >
              <option value="DEAD">DEAD (triggers autonomous replanning)</option>
              <option value="THRUSTER_OUT">THRUSTER_OUT (no thrust, keeps heartbeats)</option>
              <option value="EPS_DEGRADE">EPS_DEGRADE (gradual power death)</option>
            </select>
          </div>
          {failureMode === "EPS_DEGRADE" && (
            <div className={styles.row}>
              <label className={chrome.fieldLabel} htmlFor="inject-degrade-s">
                Fade horizon (seconds)
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
        {busy
          ? "Injecting fault…"
          : satId !== ""
            ? `Inject ${effectiveMode} fault on ${satId}`
            : "Inject fault"}
      </button>

      <p className={styles.modeHint}>{MODE_DESCRIPTIONS[effectiveMode]}</p>
      {!live && <p className={chrome.hint}>Start a live simulation above to inject faults in real time.</p>}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </div>
  );
}
