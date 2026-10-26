// Scenario builder — the #/live control seat.
// Allows loading any committed scenario preset into the builder as an editable
// template (or running it directly if unmodified), customising every parameter
// the engine reads (cubesat/scenario.py), and starting the live simulation
// with per-option 422 fallback for policy vs predictor (§3.2 #4) and immediate
// policy readout sync (§3.2 #5). When a run starts, the parameter setup
// collapses into an expandable section so Live Failure Injection, AI Early
// Warning, and Recovery Log right below stay in view without tab hunting.
import { useRef, useState } from "react";
import { uploadScenario, type ScenarioUploadResult } from "../../api/scenarios";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import { useRecoveryStore } from "../../stores/recoveryStore";
import { useRoleHistoryStore } from "../../stores/roleHistoryStore";
import { UNMEASURED } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import { backend } from "../../api/backend";
import FailureRowView from "./FailureRow";
import PhysicsSection from "./PhysicsSection";
import SwarmSection from "./SwarmSection";
import { postStart, type StartError, type StartResponse } from "./runApi";
import {
  COMMITTED_PRESETS,
  MAX_SATS,
  POLICIES,
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

const INITIAL_PRESET = COMMITTED_PRESETS[0]; // two_failure.json

export default function ScenarioBuilder() {
  const [presetFile, setPresetFile] = useState<string>(INITIAL_PRESET.filename);
  const [dirtyPreset, setDirtyPreset] = useState(false);
  const [nums, setNums] = useState<NumberValues>(INITIAL_PRESET.nums);
  const [nSats, setNSats] = useState<number>(INITIAL_PRESET.nSats);
  const [roles, setRoles] = useState<Role[]>([...INITIAL_PRESET.roles]);
  const [policy, setPolicy] = useState<PolicyId>("hungarian");
  const [runName, setRunName] = useState("");
  const [failures, setFailures] = useState<FailureRow[]>(
    INITIAL_PRESET.failures.map((f, idx) => ({ ...f, key: idx + 1 })),
  );
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [policyNote, setPolicyNote] = useState<string | null>(null);
  const [predictorNote, setPredictorNote] = useState<string | null>(null);
  const [predictor, setPredictor] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [setupOpen, setSetupOpen] = useState(true);
  const nextFailureKey = useRef(INITIAL_PRESET.failures.length + 1);

  const wireScenario = useSimStore((s) => s.scenario);
  const wireSeed = useSimStore((s) => s.seed);
  const wirePolicy = useSimStore((s) => s.policy);
  const mode = useSimStore((s) => s.mode);

  const building = phase === "building";
  const live = mode === "live";

  function applyPreset(filename: string): void {
    setPresetFile(filename);
    setError(null);
    const found = COMMITTED_PRESETS.find((p) => p.filename === filename);
    if (!found) {
      setDirtyPreset(true);
      return;
    }
    setDirtyPreset(false);
    setNSats(found.nSats);
    setRoles([...found.roles]);
    setNums({ ...found.nums });
    setFailures(
      found.failures.map((f) => ({
        key: nextFailureKey.current++,
        satId: f.satId,
        t: f.t,
        mode: f.mode,
      })),
    );
  }

  function setNumber(key: keyof NumberValues, v: number): void {
    const clamped = clampNumber(key, v);
    if (key !== "seed" && key !== "speed") {
      setDirtyPreset(true);
    }
    setNums((prev) => ({ ...prev, [key]: clamped }));
  }

  function changeSats(n: number): void {
    if (!Number.isInteger(n) || n < 2 || n > MAX_SATS) return;
    setDirtyPreset(true);
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
    setDirtyPreset(true);
    setFailures((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function addFailure(): void {
    setDirtyPreset(true);
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
    // Probe policy vs predictor individually so only the unsupported field is
    // dropped and reported (§3.2 #4).
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
      let filename = presetFile;
      const customTypedName = sanitizeName(runName);
      if (dirtyPreset || presetFile === "custom" || customTypedName !== "") {
        const auto = customTypedName === "";
        const base = auto ? "live_custom" : customTypedName;
        const scenario = buildScenario({ ...nums, name: base }, roles, failures);
        let name = base;
        let saved: ScenarioUploadResult | null = null;
        for (let attempt = 1; ; attempt++) {
          try {
            saved = await uploadScenario(name, scenario);
            break;
          } catch (err) {
            if (!auto || (err as StartError).status !== 409 || attempt >= 16) throw err;
            name = `${base}_${attempt + 1}`;
          }
        }
        filename = saved.filename ?? `${name}.json`;
      }

      useRecoveryStore.getState().resetForNewRun();
      useRoleHistoryStore.getState().resetForNewRun();
      const started = await startWithFallback(filename);
      useSimStore.getState().setSessionMeta({
        scenario: started.scenario ?? filename,
        seed: started.seed ?? nums.seed,
        policy: started.policy ?? policy,
      });
      useSimStore.getState().setMode("live");
      useReplayStore.getState().setActiveFile(null);
      setPhase("running");
      setSetupOpen(false);
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
      setSetupOpen(true);
    });
  }

  const activePreset = COMMITTED_PRESETS.find((p) => p.filename === presetFile);
  const statusText =
    phase === "building"
      ? "Starting simulation on physics engine…"
      : phase === "running"
        ? "Live simulation streaming — inject failures or inspect recovery below."
        : dirtyPreset
          ? "Custom parameters edited — saves scenario to backend and starts run."
          : `Ready to run committed preset ${presetFile}.`;

  return (
    <section className={styles.panel} aria-label="Scenario builder">
      <div className={styles.panelHead}>
        <h2 className={chrome.panelTitle}>Live mission control</h2>
      </div>

      {/* Mission readout — wire truth; "Recovery mode" always reflects the
          active policy from /simulation/start or the WS stream (§3.2 #5). */}
      <div className={styles.rows} aria-label="Mission">
        <div className={styles.row}>
          <span className={styles.rowLabel}>Scenario</span>
          <span className={styles.rowValue}>{wireScenario ?? UNMEASURED}</span>
        </div>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Seed</span>
          <span className={styles.rowValue}>
            {wireSeed === null ? UNMEASURED : String(wireSeed)}
          </span>
        </div>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Recovery mode</span>
          <span className={styles.rowValue}>{wirePolicy ?? UNMEASURED}</span>
        </div>
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

      {/* Primary Run & Lifecycle Bar — always visible at the top of the seat */}
      <div className={styles.group}>
        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="builder-preset">
            Scenario preset (editable template)
          </label>
          <select
            id="builder-preset"
            className={chrome.select}
            value={dirtyPreset ? "custom" : presetFile}
            disabled={building}
            onChange={(e) => applyPreset(e.target.value)}
          >
            {COMMITTED_PRESETS.map((p) => (
              <option key={p.filename} value={p.filename}>
                {p.label}
              </option>
            ))}
            <option value="custom">Custom (edited in builder)</option>
          </select>
          {activePreset !== undefined && !dirtyPreset && (
            <p className={chrome.hint}>{activePreset.summary}</p>
          )}
        </div>

        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="builder-policy">
            Recovery policy
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

        <button
          type="button"
          className={`${chrome.btn} ${styles.runBtn}`}
          onClick={() => void run()}
          disabled={building}
        >
          {building
            ? "Starting simulation…"
            : live
              ? "Restart simulation with builder settings"
              : "Run simulation"}
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
          <button
            type="button"
            className={chrome.btn}
            onClick={() => {
              window.location.hash = "#/replay";
            }}
          >
            Switch to replay
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

      {/* Collapsible Scenario Setup — open before start, folds automatically on
          run so Live Failure Injection and Recovery Log below stay in view. */}
      <details
        className={styles.setupAccordion}
        open={setupOpen}
        onToggle={(e) => setSetupOpen(e.currentTarget.open)}
      >
        <summary className={styles.setupSummary}>
          <span>
            Configure swarm, failures &amp; physics ({nSats} sats · {failures.length} scheduled{" "}
            {failures.length === 1 ? "failure" : "failures"})
          </span>
          <span className={styles.setupBadge}>{setupOpen ? "Hide" : "Edit"}</span>
        </summary>
        <div className={styles.setupBody}>
          <SwarmSection
            nSats={nSats}
            roles={roles}
            building={building}
            nums={nums}
            onSats={changeSats}
            onRole={(seat, role) => {
              setDirtyPreset(true);
              setRoles((prev) => prev.map((r, j) => (j === seat ? role : r)));
            }}
            onNumber={setNumber}
          />

          <fieldset className={styles.group} disabled={building}>
            <legend className={chrome.panelTitle}>Scheduled failures</legend>
            {failures.length === 0 ? (
              <p className={chrome.hint}>
                No scheduled failures — swarm flies nominal unless you inject a live failure
                below.
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
                        setDirtyPreset(true);
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
            <p className={chrome.hint}>
              Letters, digits, - and _ only. Used when saving edited parameters.
            </p>
          </div>
        </div>
      </details>
    </section>
  );
}
