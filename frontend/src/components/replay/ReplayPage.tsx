// Replay page (#/replay) — FRONTEND_SPEC §6.2 + §7.8.
// Strictly playback-only: premade runs in the left gallery (GET /replay/files)
// + fleet list for quick selection; the center column hosts the 3D LVLH scene,
// NarrationStrip, §13.5 state-machine Timeline, the ONE ReplayControls
// transport bar, and the step-by-step RecoveryLog; the right column mounts
// the read-only RightPanel (telemetry readouts, 5 underline-tabbed charts,
// Role reassignment table, and SelectedSatellitePanel inspector).
// Zero live simulation or failure-injection controls appear on this page.
import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
import { useReplayStore } from "../../stores/replayStore";
import { useRecoveryStore } from "../../stores/recoveryStore";
import { useRoleHistoryStore } from "../../stores/roleHistoryStore";
import { useSimStore } from "../../stores/simStore";
import SwarmScene from "../three/SwarmScene.tsx";
import NarrationStrip from "../narration/NarrationStrip";
import Timeline from "../events/Timeline";
import ReplayControls from "../controls/ReplayControls";
import RecoveryLog from "../recovery/RecoveryLog";
import RightPanel from "../layout/RightPanel";
import SatelliteList from "../satellites/SatelliteList";
import chrome from "../../styles/chrome.module.css";
import styles from "./ReplayPage.module.css";

const LOAD_SPEED = 10;

// Doc-sourced gallery labels (docs/IMPLEMENTATION_NOTES.md + MASTER_PROMPT.md).
const RUN_LABELS: Record<string, string> = {
  firefly_swarm: "Hypothetical 6-sat swarm on FIREFLY-1's real orbit (NORAD 62701)",
  two_failure: "Primary 6-sat two-failure recovery demo (SAT-2 & SAT-3 DEAD)",
  cascading_n8: "8-sat cascading failures (2 DEAD + 1 THRUSTER_OUT downlink)",
  leader_failure_6sat: "6-sat leader death at t=2400 s + imager death at t=3000 s",
  single_failure_n4: "4-sat minimal swarm with leader failure and re-election",
  nominal: "6-sat nominal baseline (1 orbit, zero failures)",
};

function scenarioBaseOf(filename: string): string {
  return filename.replace(/\.jsonl$/, "").replace(/_run\d+$/, "");
}

export default function ReplayPage() {
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
    return scenarioFiles.length === 0 || scenarioFiles.includes(`${base}.json`)
      ? label
      : null;
  }

  async function loadRun(filename: string): Promise<void> {
    setBusyFile(filename);
    setError(null);
    try {
      useSimStore.getState().reset();
      useRecoveryStore.getState().resetForNewRun();
      useRoleHistoryStore.getState().resetForNewRun();
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
      <div className={styles.main}>
        {/* tabIndex -1: focus target for ReplayControls' "Change recording". */}
        <aside
          id="replay-gallery"
          tabIndex={-1}
          className={`${chrome.panel} ${styles.gallery}`}
          aria-label="Replay runs"
        >
          <h2 className={chrome.panelTitle}>Committed replay runs</h2>
          <p className={chrome.hint}>
            Playback-only evidence logs. Click a recording to stream it through
             the console; click any satellite to inspect its role &amp; task history.
          </p>
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
          <div className={styles.hintSlot} aria-live="polite">
            {error !== null && <p className={chrome.errorText}>{error}</p>}
            {busyFile !== null && error === null && (
              <p className={chrome.hint}>Loading {busyFile}…</p>
            )}
          </div>
          <div className={styles.fleetSection}>
            <h2 className={chrome.panelTitle}>Swarm fleet (click to inspect)</h2>
            <SatelliteList />
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
        <RightPanel />
      </div>
    </div>
  );
}

export { ReplayPage };
