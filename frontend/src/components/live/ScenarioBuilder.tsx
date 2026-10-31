// Scenario builder — the #/live unscripted sandbox control seat.
// Starts with zero pre-scheduled failures (failures: []) so the swarm flies
// nominal until the operator injects faults live in real time.
// Adapts to Simplified vs Advanced view mode:
// - Simplified: Satellite count (2-50), Orbit altitude (km), Formation radius (km),
//   Recovery policy, and Start / Pause / Resume / Reset controls.
// - Advanced: Adds per-satellite role customization, phase offset, PD controller
//   gains, sensor FOV/grid settings, AI risk overlay toggle, and optional
//   scheduled failures.
import { useRef, useState } from "react";
import { uploadScenario, type ScenarioUploadResult } from "../../api/scenarios";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import { useRecoveryStore } from "../../stores/recoveryStore";
import { useRoleHistoryStore } from "../../stores/roleHistoryStore";
import { useUiStore } from "../../stores/uiStore";
import chrome from "../../styles/chrome.module.css";
import { backend } from "../../api/backend";
import FailureRowView from "./FailureRow";
import NumberField from "./NumberField";
import PhysicsSection from "./PhysicsSection";
import SwarmSection from "./SwarmSection";
import { postStart, type StartError, type StartResponse } from "./runApi";
import {
  MAX_SATS,
  POLICIES,
  SAT_COUNT_OPTIONS,
  buildScenario,
  clampNumber,
  defaultRoles,
  sanitizeName,
  type FailureRow,
  type NumberValues,
  type PolicyId,
  type Role,
} from "./scenarioDraft";
import styles from "./LivePage.module.css";

const DEFAULT_FAILURE_T = 1200;
type RunPhase = "idle" | "building" | "running" | "error";

const DEFAULT_SANDBOX_NUMS: NumberValues = {
  seed: 42,
  durationS: 17028,
  dtS: 2,
  altitudeKm: 500,
  radialAmpKm: 8,
  phaseOffsetDeg: 0,
  aMax: 0.1,
  wn: 0.01,
  zeta: 1,
  fovHalfAngleDeg: 1.5,
  gridStepKm: 2,
  gridExtentKm: 30,
  speed: 20,
};

export default function ScenarioBuilder() {
  const viewMode = useUiStore((s) => s.viewMode);
  const [nums, setNums] = useState<NumberValues>({ ...DEFAULT_SANDBOX_NUMS });
  const [nSats, setNSats] = useState<number>(6);
  const [roles, setRoles] = useState<Role[]>(defaultRoles(6));
  const [policy, setPolicy] = useState<PolicyId>("hungarian");
  const [runName, setRunName] = useState("");
  // Unscripted live sandbox by default: zero pre-scheduled failures
  const [failures, setFailures] = useState<FailureRow[]>([]);
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [policyNote, setPolicyNote] = useState<string | null>(null);
  const [predictorNote, setPredictorNote] = useState<string | null>(null);
  const [predictor, setPredictor] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const nextFailureKey = useRef(1);

  const wirePolicy = useSimStore((s) => s.policy);
  const mode = useSimStore((s) => s.mode);

  const building = phase === "building";
  const live = mode === "live";

  function setNumber(key: keyof NumberValues, v: number): void {
    const clamped = clampNumber(key, v);
    setNums((prev) => ({ ...prev, [key]: clamped }));
  }

  function changeSats(n: number): void {
    if (!Number.isInteger(n) || n < 2 || n > MAX_SATS) return;
    setNSats(n);
    setRoles((prev) =>
      prev.length === n
        ? prev
        : prev.length < n
          ? [...prev, ...defaultRoles(n).slice(prev.length)]
          : prev.slice(0, n),
    );
    setFailures((rows) => rows.filter((f) => f.satId < n));
  }

  function updateFailure(key: number, patch: Partial<FailureRow>): void {
    setFailures((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function addFailure(): void {
    setFailures((rows) => [
      ...rows,
      { key: nextFailureKey.current++, satId: 0, t: DEFAULT_FAILURE_T, mode: "DEAD" },
    ]);
  }

  async function startWithFallback(filename: string): Promise<StartResponse> {
    const baseReq = { scenario: filename, seed: nums.seed, speed: nums.speed };
    try {
      return await postStart({ ...baseReq, policy, predictor });
    } catch (err) {
      if ((err as StartError).status !== 422) throw err;
    }
    try {
      const res = await postStart({ ...baseReq, policy });
      if (predictor) {
        setPredictorNote(
          "AI-risk option not accepted by this backend — started without predictor overlay.",
        );
      }
      return res;
    } catch (errPolicyOnly) {
      if ((errPolicyOnly as StartError).status !== 422) throw errPolicyOnly;
    }
    try {
      const res = await postStart({ ...baseReq, predictor });
      setPolicyNote(
        `Policy "${policy}" not accepted by this backend — started with default allocator.`,
      );
      return res;
    } catch (errPredOnly) {
      if ((errPredOnly as StartError).status !== 422) throw errPredOnly;
    }
    const res = await postStart(baseReq);
    setPolicyNote("Policy option not accepted by this backend — started with default allocator.");
    if (predictor) {
      setPredictorNote("AI-risk option not accepted by this backend — started without overlay.");
    }
    return res;
  }

  async function run(): Promise<void> {
    setError(null);
    setPolicyNote(null);
    setPredictorNote(null);
    setPhase("building");
    try {
      const customTypedName = sanitizeName(runName);
      const auto = customTypedName === "";
      const base = auto ? `live_${nSats}sat` : customTypedName;
      const scenario = buildScenario({ ...nums, name: base }, roles, failures);
      let name = base;
      let saved: ScenarioUploadResult | null = null;
      for (let attempt = 1; ; attempt++) {
        try {
          saved = await uploadScenario(name, scenario);
          break;
        } catch (err) {
          if (!auto || (err as StartError).status !== 409 || attempt >= 32) throw err;
          name = `${base}_${attempt + 1}`;
        }
      }
      const filename = saved.filename ?? `${name}.json`;

      useRecoveryStore.getState().resetForNewRun();
      useRoleHistoryStore.getState().resetForNewRun();
      const started = await startWithFallback(filename);
      useUiStore.getState().setRunSpeed(started.speed ?? nums.speed);
      useSimStore.getState().setSessionMeta({
        scenario: started.scenario ?? filename,
        seed: started.seed ?? nums.seed,
        policy: started.policy ?? policy,
      });
      useSimStore.getState().setMode("live");
      useReplayStore.getState().setActiveFile(null);
      setPhase("running");
      setAdvancedOpen(false);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Run failed");
    }
  }

  async function control(action: () => Promise<unknown>): Promise<void> {
    setControlling(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Command failed");
    } finally {
      setControlling(false);
    }
  }

  function resetRun(): void {
    void control(async () => {
      await backend.simulationReset();
      useSimStore.getState().reset();
      useRecoveryStore.getState().resetForNewRun();
      useRoleHistoryStore.getState().resetForNewRun();
      setPhase("idle");
    });
  }

  const statusText =
    phase === "building"
      ? "Initializing physics engine…"
      : live
        ? `Live swarm active (${nSats} satellites, ${wirePolicy ?? policy}). Inject faults below.`
        : `Ready: ${nSats} satellites at ${nums.altitudeKm} km altitude (${nums.radialAmpKm} km formation radius).`;

  return (
    <section className={styles.panel} aria-label="Live sandbox setup">
      <div className={styles.panelHead}>
        <h2 className={chrome.panelTitle}>Live swarm sandbox</h2>
      </div>

      {policyNote !== null && (
        <p className={styles.cautionNote} role="status">
          {policyNote}
        </p>
      )}
      {predictorNote !== null && (
        <p className={styles.cautionNote} role="status">
          {predictorNote}
        </p>
      )}

      {/* Core Sandbox Setup — always clear and direct */}
      <div className={styles.group}>
        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="builder-nsats">
            Satellite count (N)
          </label>
          <select
            id="builder-nsats"
            className={chrome.select}
            value={nSats}
            disabled={building}
            onChange={(e) => changeSats(Number(e.target.value))}
          >
            {SAT_COUNT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} satellites ({n - 2} imagers, 1 leader, 1 downlink)
              </option>
            ))}
          </select>
        </div>

        <div className={styles.fieldGrid}>
          <NumberField
            id="builder-alt-quick"
            label="Altitude (km)"
            value={nums.altitudeKm}
            min="200"
            max="1999"
            step="10"
            disabled={building}
            onCommit={(v) => setNumber("altitudeKm", v)}
          />
          <NumberField
            id="builder-amp-quick"
            label="Array radius (km)"
            value={nums.radialAmpKm}
            min="0.5"
            step="0.5"
            disabled={building}
            onCommit={(v) => setNumber("radialAmpKm", v)}
          />
        </div>

        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="builder-policy">
            Recovery algorithm
          </label>
          <select
            id="builder-policy"
            className={chrome.select}
            value={policy}
            disabled={building}
            onChange={(e) => setPolicy(e.target.value as PolicyId)}
          >
            {POLICIES.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          className={`${chrome.btn} ${styles.runBtn}`}
          onClick={() => void run()}
          disabled={building}
        >
          {building
            ? "Starting simulation…"
            : live
              ? "Apply & restart live simulation"
              : "Start live simulation"}
        </button>

        <div className={chrome.btnRow}>
          <button
            type="button"
            className={chrome.btn}
            disabled={!live || controlling}
            onClick={() => void control(backend.simulationPause)}
          >
            Pause
          </button>
          <button
            type="button"
            className={chrome.btn}
            disabled={!live || controlling}
            onClick={() => void control(backend.simulationResume)}
          >
            Resume
          </button>
          <button
            type="button"
            className={chrome.btn}
            disabled={mode === "stopped" || controlling}
            onClick={resetRun}
          >
            Reset
          </button>
        </div>

        <p className={styles.runStatus} aria-live="polite">
          {error !== null ? (
            <span className={chrome.errorText} role="alert">
              {error}
            </span>
          ) : (
            <span className={chrome.hint}>{statusText}</span>
          )}
        </p>
      </div>

      {/* Advanced Engineering Parameters — shown only in Advanced View */}
      {viewMode === "advanced" && (
        <details
          className={styles.setupAccordion}
          open={advancedOpen}
          onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}
        >
          <summary className={styles.setupSummary}>
            <span>Advanced roles, physics &amp; scheduled faults</span>
            <span className={styles.setupBadge}>{advancedOpen ? "Hide" : "Expand"}</span>
          </summary>
          <div className={styles.setupBody}>
            <div className={styles.field}>
              <label className={styles.toggle} htmlFor="builder-predictor">
                <input
                  id="builder-predictor"
                  type="checkbox"
                  checked={predictor}
                  disabled={building}
                  onChange={(e) => setPredictor(e.target.checked)}
                />
                AI risk overlay (display-only LightGBM precursor score)
              </label>
            </div>

            <SwarmSection
              nSats={nSats}
              roles={roles}
              building={building}
              nums={nums}
              onSats={changeSats}
              onRole={(seat, role) => {
                setRoles((prev) => prev.map((r, j) => (j === seat ? role : r)));
              }}
              onNumber={setNumber}
            />

            <fieldset className={styles.group} disabled={building}>
              <legend className={chrome.panelTitle}>Optional scheduled failures</legend>
              {failures.length === 0 ? (
                <p className={chrome.hint}>
                  None scheduled — swarm flies nominal until you inject a fault live below.
                </p>
              ) : (
                <table className={styles.failTable}>
                  <thead>
                    <tr>
                      <th scope="col">Satellite</th>
                      <th scope="col">Time (s)</th>
                      <th scope="col">Mode</th>
                      <th scope="col">
                        <span className={styles.visuallyHidden}>Remove</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {failures.map((f) => (
                      <FailureRowView
                        key={f.key}
                        row={f}
                        maxSat={nSats}
                        disabled={building}
                        onChange={(patch) => updateFailure(f.key, patch)}
                        onRemove={() => {
                          setFailures((rows) => rows.filter((r) => r.key !== f.key));
                        }}
                      />
                    ))}
                  </tbody>
                </table>
              )}
              <button
                type="button"
                className={chrome.btn}
                onClick={addFailure}
                disabled={building}
              >
                Add scheduled failure
              </button>
            </fieldset>

            <PhysicsSection values={nums} onNumber={setNumber} disabled={building} />

            <div className={styles.field}>
              <label className={chrome.fieldLabel} htmlFor="builder-name">
                Custom scenario name (optional)
              </label>
              <input
                id="builder-name"
                className={chrome.input}
                type="text"
                value={runName}
                placeholder="live_custom"
                spellCheck={false}
                disabled={building}
                onChange={(e) => setRunName(e.target.value)}
              />
            </div>
          </div>
        </details>
      )}
    </section>
  );
}
