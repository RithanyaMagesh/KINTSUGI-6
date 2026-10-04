// Live-run controls — start/pause/resume/reset via the real G5 routes
// (cubesat/api.py /simulation/*) and run speed via POST /simulation/speed.
// The scenario dropdown sits directly above this group (ScenarioSelector,
// rendered by LeftPanel). "Switch to replay" scrolls to the replay transport
// bar (id="replay-controls", bottom panel) — it is navigation, never a mode
// lie: the mode only flips when a replay is actually loaded there.
import { useState } from "react";
import { backend } from "../../api/backend";
import { simulationSpeed } from "../../api/scenarios";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import chrome from "../../styles/chrome.module.css";
import styles from "./SimulationControls.module.css";

// Live-run speed multipliers (same transport range as replay; the backend
// default of 100× is offered as the initial "Default" option — measured from
// cubesat/session.py:157).
const SPEEDS = [0.5, 1, 2, 5, 10];

interface Props {
  scenario: string | null;
}

export default function SimulationControls({ scenario }: Props) {
  const mode = useSimStore((s) => s.mode);
  const setMode = useSimStore((s) => s.setMode);
  const resetStore = useSimStore((s) => s.reset);
  const [seed, setSeed] = useState("42");
  const [speed, setSpeed] = useState<number | null>(null); // null = backend default (100×)
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, nextMode: "live" | "stopped" | null) {
    setBusy(true);
    setError(null);
    try {
      await action();
      if (nextMode !== null) setMode(nextMode);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Command failed");
    } finally {
      setBusy(false);
    }
  }

  function switchToReplay(): void {
    const el = document.getElementById("replay-controls");
    el?.scrollIntoView({ block: "nearest" });
    el?.focus();
  }

  const live = mode === "live";

  return (
    <div className={styles.group}>
      <h3 className={styles.subTitle}>Live run</h3>
      <div className={chrome.btnRow}>
        <button
          className={chrome.btn}
          disabled={live || busy || scenario === null}
          onClick={() => {
            useReplayStore.getState().setActiveFile(null);
            const seedNum = Number.parseInt(seed, 10);
            run(
              () => backend.simulationStart(scenario, Number.isNaN(seedNum) ? null : seedNum),
              "live",
            );
          }}
        >
          Start simulation
        </button>
        <button className={chrome.btn} disabled={!live || busy} onClick={() => run(backend.simulationPause, null)}>
          Pause
        </button>
        <button className={chrome.btn} disabled={!live || busy} onClick={() => run(backend.simulationResume, null)}>
          Resume
        </button>
        <button
          className={chrome.btn}
          disabled={mode === "stopped" || busy}
          onClick={() =>
            run(async () => {
              await backend.simulationReset();
              resetStore();
            }, "stopped")
          }
        >
          Reset
        </button>
      </div>
      <div className={styles.rowInline}>
        <label className={chrome.fieldLabel} htmlFor="seed-input">
          Seed
        </label>
        <input
          id="seed-input"
          className={`${chrome.input} ${styles.input}`}
          type="number"
          value={seed}
          disabled={live || busy}
          onChange={(e) => setSeed(e.target.value)}
        />
      </div>
      <div className={styles.rowInline}>
        <label className={chrome.fieldLabel} htmlFor="live-speed">
          Speed
        </label>
        <select
          id="live-speed"
          className={chrome.select}
          value={speed === null ? "" : String(speed)}
          disabled={!live || busy}
          onChange={(e) => {
            const next = Number(e.target.value);
            setSpeed(next);
            run(() => simulationSpeed(next), null);
          }}
        >
          <option value="">Default (100×)</option>
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
      </div>
      <div className={chrome.btnRow}>
        <button className={chrome.btn} onClick={switchToReplay}>
          Switch to replay
        </button>
      </div>
      {scenario === null && <p className={chrome.hint}>Select a scenario to begin.</p>}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </div>
  );
}
