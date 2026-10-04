// Replay page (#/replay) — FRONTEND_SPEC §6.2 + §7.8. Premade runs in the
// left gallery (GET /replay/files); the main column is the SAME 3D view,
// narration and §13.5 spine the console uses, with the §7.8 transport
// (controls/ReplayControls) mounted here — the live console no longer hosts
// it. The recovery log (the step-by-step "how did it recover" record) sits
// under the transport: replay is where the two-failure demo gets explained.
//
// Loading a run resets the console + story stores (PresentationView's
// openReplay pattern) and posts /replay/load; playback, seek, speed and
// restart stay server-side — the frames arrive over the same /ws/state
// socket App drives, so this page must render INSIDE App's tree (it mounts
// neither useWebSocket nor useFrameHistory itself).
import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
import { useReplayStore } from "../../stores/replayStore";
import { useRecoveryStore } from "../../stores/recoveryStore";
import { useSimStore } from "../../stores/simStore";
import TopStatusBar from "../layout/TopStatusBar";
import SwarmScene from "../three/SwarmScene.tsx"; // .tsx: keeps tsc from case-matching swarmScene.ts on Windows
import NarrationStrip from "../narration/NarrationStrip";
import Timeline from "../events/Timeline";
import ReplayControls from "../controls/ReplayControls";
import RecoveryLog from "../recovery/RecoveryLog";
import chrome from "../../styles/chrome.module.css";
import styles from "./ReplayPage.module.css";

// Load at the transport's own default: ReplayControls' speed select offers
// 0.5x-10x only (its SPEEDS), so loading at the backend's 100x default would
// leave the select showing a speed the session is not running (a lying
// readout). Keep in step with ReplayControls DEFAULT_SPEED.
const LOAD_SPEED = 10;

// Doc-sourced gallery labels — no invented claims. A label shows only when
// the log's base name matches a scenario file the backend actually serves
// (GET /scenarios) AND the docs name what that scenario demonstrates:
//   firefly_swarm — "hypothetical-swarm-on-FIREFLY-1", chief FIREFLY-1
//     NORAD 62701 (docs/IMPLEMENTATION_NOTES.md:753, 838-843).
//   two_failure — the primary two-failure recovery demo
//     (docs/MASTER_PROMPT.md:120). The ask names both likewise.
// The trailing _runN strip is the determinism double-run convention visible
// in data/logs (firefly_swarm.jsonl + firefly_swarm_run2.jsonl): a re-run of
// the same scenario, so it earns the same doc label. Anything else shows its
// file name and nothing else.
const RUN_LABELS: Record<string, string> = {
  firefly_swarm: "Hypothetical swarm on FIREFLY-1's orbit",
  two_failure: "Two-failure recovery demo",
};

function scenarioBaseOf(filename: string): string {
  return filename.replace(/\.jsonl$/, "").replace(/_run\d+$/, "");
}

export default function ReplayPage() {
  // files === null while GET /replay/files is in flight (the "loading" state
  // keeps the panel's dimensions, §13.3).
  const [files, setFiles] = useState<string[] | null>(null);
  const [scenarioFiles, setScenarioFiles] = useState<string[]>([]);
  const [busyFile, setBusyFile] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeFile = useReplayStore((s) => s.activeFile);
  const scenario = useSimStore((s) => s.scenario);

  useEffect(() => {
    let cancelled = false;
    backend
      .replayFiles()
      .then((d) => {
        if (!cancelled) setFiles(d.files);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setFiles([]);
          setError(err instanceof Error ? err.message : "Could not list replay logs");
        }
      });
    // Scenario file names gate the doc labels. A failure degrades to
    // filename-only rows — never a wrong label.
    backend
      .scenarios()
      .then((d) => {
        if (!cancelled) setScenarioFiles(d.scenarios);
      })
      .catch(() => {
        if (!cancelled) setScenarioFiles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function labelFor(filename: string): string | null {
    const base = scenarioBaseOf(filename);
    const label = RUN_LABELS[base];
    if (label === undefined) return null;
    return scenarioFiles.includes(`${base}.json`) ? label : null;
  }

  async function loadRun(filename: string): Promise<void> {
    setBusyFile(filename);
    setError(null);
    try {
      // Console + story reset with the run (PresentationView.openReplay
      // pattern; the INIT empty frame re-clears the stores via ingest too,
      // and simStore.reset keeps the live socket state).
      useSimStore.getState().reset();
      useRecoveryStore.getState().resetForNewRun();
      useReplayStore.getState().setPlaybackSpeed(LOAD_SPEED);
      await backend.replayLoad(filename, LOAD_SPEED);
      useReplayStore.getState().setActiveFile(filename);
      useReplayStore.getState().setIsPlaying(true);
      useSimStore.getState().setMode("replay");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay could not be loaded");
    } finally {
      setBusyFile(null);
    }
  }

  return (
    <div className={styles.page}>
      <TopStatusBar />
      <div className={styles.main}>
        <aside className={`${chrome.panel} ${styles.gallery}`} aria-label="Replay runs">
          <h2 className={chrome.panelTitle}>Runs</h2>
          {files === null ? (
            <p className={chrome.hint}>Loading runs…</p>
          ) : files.length === 0 ? (
            <p className={chrome.hint}>
              No replay logs found. Generate one:{" "}
              <span className={styles.command}>
                uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed
                42 --out data/logs/two_failure.jsonl
              </span>
            </p>
          ) : (
            <ul className={styles.runList}>
              {files.map((f) => {
                const label = labelFor(f);
                const active = activeFile === f;
                return (
                  <li key={f}>
                    <button
                      type="button"
                      className={`${styles.runRow} ${active ? styles.runActive : ""}`}
                      onClick={() => void loadRun(f)}
                      disabled={busyFile !== null}
                      aria-current={active ? "true" : undefined}
                    >
                      <span className={styles.runName}>{f}</span>
                      {label !== null && <span className={styles.runLabel}>{label}</span>}
                      {active && scenario !== null && (
                        <span className={styles.runScenario}>Scenario: {scenario}</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {/* Reserved slot: loading note or load error, no layout shift. */}
          <div className={styles.hintSlot} aria-live="polite">
            {error !== null && <p className={chrome.errorText}>{error}</p>}
            {busyFile !== null && error === null && (
              <p className={chrome.hint}>Loading {busyFile}…</p>
            )}
          </div>
        </aside>
        <div className={styles.content}>
          <section className={`${chrome.panel} ${styles.scenePanel}`} aria-label="Swarm view">
            <SwarmScene />
          </section>
          <div className={styles.storyZone}>
            <NarrationStrip />
            <Timeline />
          </div>
          <ReplayControls />
          <section className={`${chrome.panel} ${styles.recoveryPanel}`} aria-label="Recovery log">
            <RecoveryLog />
          </section>
        </div>
      </div>
    </div>
  );
}

export { ReplayPage };
