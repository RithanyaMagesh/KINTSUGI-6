// Scenario builder — the #/live control seat (the live sidebar's first and
// default tab). Customises everything the engine reads (cubesat/scenario.py
// Scenario) and runs it against the real backend: POST /scenarios/upload then
// POST /simulation/start (cubesat/api.py:155, :218). Every default is the
// committed reference scenario data/scenarios/nominal.json or a documented
// engine value — no invented numbers (repo invariant 1). Schema ranges stay
// the server's authority: its 422 detail is surfaced verbatim on the error
// row. The Run group also carries the run lifecycle (pause/resume/reset,
// spec 7.1) and the "Switch to replay" navigation — playback itself lives on
// #/replay only. Standalone, wrap in chrome.panel.
import { useRef, useState } from "react";
import { uploadScenario, type ScenarioUploadResult } from "../../api/scenarios";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import { UNMEASURED } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import { backend } from "../../api/backend";
import FailureRowView from "./FailureRow";
import PhysicsSection from "./PhysicsSection";
import SwarmSection from "./SwarmSection";
import { postStart, type StartError } from "./runApi";
import {
  POLICIES,
  buildScenario,
  defaultRoles,
  sanitizeName,
  type FailureRow,
  type NumberValues,
  type PolicyId,
  type Role,
} from "./scenarioDraft";
import styles from "./LivePage.module.css";

/** Default failure time: the documented example failure time from
 * data/scenarios/two_failure.json (also CustomScenarioModal's reference). */
const DEFAULT_FAILURE_T = 1200;

type RunPhase = "idle" | "building" | "running" | "error";

/** The integrator's store contract (see BuilderResult integrationNotes):
 * simStore gains `policy: string | null`, set from hello/sim_state. Until
 * that lands the tolerant read renders "unmeasured" — never a guess. */
type SimStoreWithPolicy = { policy?: string | null };

/** Form number defaults: data/scenarios/nominal.json + the backend's
 * StartRequest speed default (cubesat/wire.py:39). */
const NUMBER_DEFAULTS: NumberValues = {
  seed: 42,
  durationS: 5676,
  dtS: 2,
  altitudeKm: 500,
  radialAmpKm: 11,
  phaseOffsetDeg: 0,
  aMax: 0.01,
  wn: 0.01,
  zeta: 1,
  fovHalfAngleDeg: 1.5,
  gridStepKm: 2,
  gridExtentKm: 30,
  speed: 100,
};

export default function ScenarioBuilder() {
  const [nums, setNums] = useState<NumberValues>(NUMBER_DEFAULTS);
  const [nSats, setNSats] = useState(6);
  const [roles, setRoles] = useState<Role[]>(defaultRoles(6));
  const [policy, setPolicy] = useState<PolicyId>("hungarian");
  const [runName, setRunName] = useState("");
  const [failures, setFailures] = useState<FailureRow[]>([]);
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [policyNote, setPolicyNote] = useState<string | null>(null);
  /** AI-risk overlay for THIS run (cubesat/wire.py StartRequest.predictor,
   * default false): the backend scores sats[].risk display-only and the AI
   * early-warning panel below reads it. Off until chosen — no silent cost. */
  const [predictor, setPredictor] = useState(false);
  /** A pause/resume/reset command is in flight (separate from `building`). */
  const [controlling, setControlling] = useState(false);
  const nextFailureKey = useRef(1);

  // Wire truth for the mission readout (§13.3 rows; "unmeasured" until frames).
  const wireScenario = useSimStore((s) => s.scenario);
  const wireSeed = useSimStore((s) => s.seed);
  const wirePolicy = useSimStore((s) => (s as SimStoreWithPolicy).policy ?? null);
  const mode = useSimStore((s) => s.mode);

  const building = phase === "building";
  const live = mode === "live";

  function setNumber(key: keyof NumberValues, v: number): void {
    setNums((prev) => ({ ...prev, [key]: v }));
  }

  function changeSats(n: number): void {
    if (!Number.isInteger(n) || n < 2 || n > 8) return;
    setNSats(n);
    // Preserve per-seat edits: grow with the default pattern's tail, shrink
    // by slicing. Failures on removed seats are dropped (they would 422:
    // scenario.py _failures_reference_existing_sats).
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

  async function run(): Promise<void> {
    setError(null);
    setPolicyNote(null);
    setPhase("building");
    try {
      const chosen = sanitizeName(runName);
      const auto = chosen === "";
      const base = auto ? "live_custom" : chosen;
      const scenario = buildScenario({ ...nums, name: base }, roles, failures);
      // Overwrites are refused: POST /scenarios/upload 409s on an existing
      // name (cubesat/api.py scenarios_upload). An auto-picked default name
      // retries suffixed (live_custom_2, …) so a second run never traps on a
      // name the operator never chose; a typed name is kept and its 409
      // surfaces verbatim — the operator picked it.
      let name = base;
      let saved: ScenarioUploadResult | null = null;
      for (let attempt = 1; ; attempt++) {
        try {
          saved = await uploadScenario(name, scenario);
          break;
        } catch (err) {
          if (!auto || (err as StartError).status !== 409 || attempt >= 8) throw err;
          name = `${base}_${attempt + 1}`;
        }
      }
      // uploadScenario surfaces 404/405 as "upload not available" and 409 as
      // the duplicate-name refusal; filename is candidate.name from
      // cubesat/api.py. The sanitized name is decided here, so the fallback
      // below is the same file the backend would have reported.
      const filename = saved.filename ?? `${name}.json`;
      try {
        await postStart({ scenario: filename, seed: nums.seed, speed: nums.speed, policy, predictor });
      } catch (startErr) {
        if ((startErr as StartError).status === 422) {
          // The backend predates the policy field — start without it and say
          // so honestly instead of silently dropping the selection (§13.6).
          await postStart({ scenario: filename, seed: nums.seed, speed: nums.speed });
          setPolicyNote("Policy selection not active on this backend — started without it.");
        } else {
          throw startErr;
        }
      }
      // A live start supersedes any replay selection — the same clear the
      // console's Start control does — so the replay page never presents this
      // run as its loaded file.
      useReplayStore.getState().setActiveFile(null);
      setPhase("running");
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Run failed");
    }
  }

  /** Run lifecycle (spec 7.1): pause/resume/reset against the real G5 routes.
   * Errors land on the same inline row as the start flow. */
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
      useSimStore.getState().reset(); // same console clear the Start control does
    });
  }

  function switchToReplay(): void {
    // Playback lives on the #/replay page since the round-2 page split —
    // navigation, never a mode lie: the mode only flips when a replay is
    // actually loaded there.
    window.location.hash = "#/replay";
  }

  const statusText =
    phase === "building"
      ? "Uploading scenario and starting the run…"
      : phase === "running"
        ? "Simulation started — live frames stream into the swarm view."
        : "Saves the scenario to the backend, then starts the run.";

  return (
    <section className={styles.panel} aria-label="Scenario builder">
      <h2 className={chrome.panelTitle}>Scenario builder</h2>

      {/* Mission readout — wire truth; "Recovery mode" always visible so the
          active policy is never a mystery (the complaint that motivated it). */}
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

      <SwarmSection
        nSats={nSats}
        roles={roles}
        building={building}
        nums={nums}
        onSats={changeSats}
        onRole={(seat, role) =>
          setRoles((prev) => prev.map((r, j) => (j === seat ? role : r)))
        }
        onNumber={setNumber}
      />

      <fieldset className={styles.group} disabled={building}>
        <legend className={chrome.panelTitle}>Failures</legend>
        {failures.length === 0 ? (
          <p className={chrome.hint}>
            No failures configured — the swarm flies the whole run nominal.
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
                  onRemove={() => setFailures((rows) => rows.filter((r) => r.key !== f.key))}
                />
              ))}
            </tbody>
          </table>
        )}
        <button type="button" className={chrome.btn} onClick={addFailure} disabled={building}>
          Add failure
        </button>
      </fieldset>

      <PhysicsSection values={nums} onNumber={setNumber} disabled={building} />

      <fieldset className={styles.group} disabled={building}>
        <legend className={chrome.panelTitle}>Recovery policy</legend>
        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="builder-policy">
            Policy
          </label>
          <select
            id="builder-policy"
            className={chrome.select}
            value={policy}
            onChange={(e) => setPolicy(e.target.value as PolicyId)}
          >
            {POLICIES.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
          <p className={chrome.hint}>
            Sent as policy on /simulation/start. The active policy reads back on
            the wire as "Recovery mode" above.
          </p>
        </div>
      </fieldset>

      <fieldset className={styles.group} disabled={building}>
        <legend className={chrome.panelTitle}>Run</legend>
        <div className={styles.field}>
          <label className={styles.toggle} htmlFor="builder-predictor">
            <input
              id="builder-predictor"
              type="checkbox"
              checked={predictor}
              onChange={(e) => setPredictor(e.target.checked)}
            />
            AI risk overlay
          </label>
          <p className={chrome.hint}>
            Scores failure risk for this run (display-only); the AI early-warning panel
            below reads it.
          </p>
        </div>
        <div className={styles.field}>
          <label className={chrome.fieldLabel} htmlFor="builder-name">
            Run name (optional)
          </label>
          <input
            id="builder-name"
            className={chrome.input}
            type="text"
            value={runName}
            placeholder="live_custom"
            spellCheck={false}
            onChange={(e) => setRunName(e.target.value)}
          />
          <p className={chrome.hint}>Letters, digits, - and _ only. Left empty, a free name is picked.</p>
        </div>
        <button
          type="button"
          className={`${chrome.btn} ${styles.runBtn}`}
          onClick={() => void run()}
          disabled={building}
        >
          {building ? "Starting simulation…" : "Run simulation"}
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
          <button type="button" className={chrome.btn} onClick={switchToReplay}>
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
      </fieldset>
    </section>
  );
}
