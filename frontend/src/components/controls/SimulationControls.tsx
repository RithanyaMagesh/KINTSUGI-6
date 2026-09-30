// Simulation start/pause/resume/reset — wired to the real G5 routes
// (cubesat/api.py /simulation/*). Errors surface inline in the panel's voice.
import { useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import chrome from "../../styles/chrome.module.css";
import styles from "./SimulationControls.module.css";

interface Props {
  scenario: string | null;
}

export default function SimulationControls({ scenario }: Props) {
  const mode = useSimStore((s) => s.mode);
  const setMode = useSimStore((s) => s.setMode);
  const resetStore = useSimStore((s) => s.reset);
  const [seed, setSeed] = useState("42");
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

  const live = mode === "live";

  return (
    <div className={styles.group}>
      <h3 className={styles.subTitle}>Simulation</h3>
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
      <div className={styles.seedRow}>
        <label className={chrome.fieldLabel} htmlFor="seed-input">
          Seed
        </label>
        <input
          id="seed-input"
          className={chrome.input}
          type="number"
          value={seed}
          disabled={live || busy}
          onChange={(e) => setSeed(e.target.value)}
        />
      </div>
      {scenario === null && <p className={chrome.hint}>Select a scenario to begin.</p>}
      {error !== null && <p className={chrome.errorText}>{error}</p>}
    </div>
  );
}
