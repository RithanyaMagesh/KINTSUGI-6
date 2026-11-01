// Failure injection — POST /failure/inject {sat_id, mode, degrade_s}.
// Offers only what the backend accepts (injectRules.ts): satellites it would
// refuse are shown but disabled, v2-only faults appear only on v2 runs, and
// nothing can be injected once the run has finished. Follows a satellite click
// in the 3D view or fleet table. The fault picker always shows: what you pick
// is what is sent (it used to hide with the builder's More options and fall
// back to DEAD without saying so).
import { useEffect, useMemo, useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { faultLabel, rolesLabel, satLabel } from "../live/hudFormat";
import { injectBlock, isV2, V1_MODES, V2_MODES, type InjectMode } from "./injectRules";
import chrome from "../../styles/chrome.module.css";
import styles from "./FailureInjectionPanel.module.css";

// The engine's own descriptions (cubesat/scenario_models.py FailureMode).
const MODE_DESC: Record<InjectMode, string> = {
  DEAD: "Goes silent and drifts. The swarm notices within seconds and moves the survivors into new slots.",
  THRUSTER_OUT: "Can't move any more; it reports the fault and the swarm replans.",
  EPS_DEGRADE: "Power fades over the time you set, then it goes silent.",
  PAYLOAD_FAIL: "Keeps flying but can no longer image.",
  PARTIAL_THRUST: "Thrusters drop to half strength. No alarm is raised.",
  THRUSTER_STUCK_OPEN: "A thruster fires nonstop until the tank is empty. No alarm is raised.",
  RADIO_FAIL: "Keeps flying but goes silent.",
};

interface Option {
  id: string;
  text: string;
  block: string | null;
}

export default function FailureInjectionPanel() {
  const mode = useSimStore((s) => s.mode);
  const finished = useSimStore((s) => s.runSummary !== null);
  const v2 = useSimStore((s) => isV2(s.satellites));
  // One string per satellite, so this panel re-renders only when a label or
  // eligibility changes, not on every frame (an open dropdown whose options
  // are rewritten ten times a second flickers and loses the pick).
  const optionKey = useSimStore((s) => {
    const v = isV2(s.satellites);
    return s.satellites
      .map((x) => `${x.id}\t${x.id}, ${rolesLabel(x)}, ${satLabel(x)}\t${injectBlock(x, v) ?? ""}`)
      .join("\n");
  });
  const options = useMemo<Option[]>(
    () =>
      optionKey === ""
        ? []
        : optionKey.split("\n").map((line) => {
            const [id, text, block] = line.split("\t");
            return { id, text, block: block === "" ? null : block };
          }),
    [optionKey],
  );
  const selectedSatelliteId = useUiStore((s) => s.selectedSatelliteId);
  const [satId, setSatId] = useState("");
  const [failureMode, setFailureMode] = useState<InjectMode>("DEAD");
  const [degradeS, setDegradeS] = useState(600.0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const modes: readonly InjectMode[] = v2 ? V2_MODES : V1_MODES;
  const effectiveMode: InjectMode = modes.includes(failureMode) ? failureMode : "DEAD";
  const eligible = (id: string) => options.some((o) => o.id === id && o.block === null);

  // A click in the 3D view or fleet table picks the target, if it can fail.
  useEffect(() => {
    if (selectedSatelliteId !== null && eligible(selectedSatelliteId)) setSatId(selectedSatelliteId);
    // deps: follow the click only, not every frame
  }, [selectedSatelliteId]);

  // Keep the target valid: a new run, or the target just failed.
  useEffect(() => {
    if (satId !== "" && eligible(satId)) return;
    setSatId(options.find((o) => o.block === null)?.id ?? "");
  }, [options, satId]);

  // A stale refusal no longer applies once the pick changes.
  useEffect(() => setError(null), [satId, effectiveMode]);

  const live = mode === "live";
  const canInject = live && !finished && satId !== "" && eligible(satId) && !busy;

  async function inject() {
    setBusy(true);
    setError(null);
    try {
      await backend.failureInject(satId, effectiveMode, effectiveMode === "EPS_DEGRADE" ? degradeS : 0.0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Injection failed");
    } finally {
      setBusy(false);
    }
  }

  const controlsOff = !live || finished || busy;

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
          disabled={controlsOff || options.length === 0}
          onChange={(e) => setSatId(e.target.value)}
        >
          {satId === "" && <option value="">No satellite can fail</option>}
          {options.map((o) => (
            <option key={o.id} value={o.id} disabled={o.block !== null}>
              {o.block === null ? o.text : `${o.id}, ${o.block}`}
            </option>
          ))}
        </select>
      </div>

          <div className={styles.row}>
            <label className={chrome.fieldLabel} htmlFor="inject-mode">
              Fault
            </label>
            <select
              id="inject-mode"
              className={chrome.select}
              value={effectiveMode}
              disabled={controlsOff}
              onChange={(e) => setFailureMode(e.target.value as InjectMode)}
            >
              {modes.map((m) => (
                <option key={m} value={m}>
                  {faultLabel(m)}
                </option>
              ))}
            </select>
          </div>
          {effectiveMode === "EPS_DEGRADE" && (
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
                disabled={controlsOff}
                onChange={(e) => setDegradeS(Math.max(0, Number(e.target.value)))}
              />
            </div>
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
        {faultLabel(effectiveMode)}: {MODE_DESC[effectiveMode]}
      </p>
      {!v2 && live && (
        <p className={chrome.hint}>Camera, radio and thruster faults need a v2 scenario.</p>
      )}
      {!live && <p className={chrome.hint}>Start a live simulation above to fail satellites.</p>}
      {live && finished && <p className={chrome.hint}>This run has finished. Start a new one to fail satellites.</p>}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </div>
  );
}
