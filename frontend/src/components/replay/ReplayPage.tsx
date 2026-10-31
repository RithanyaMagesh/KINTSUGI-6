// Replay page (#/replay) — FRONTEND_SPEC §6.2 + §7.8.
// Strictly playback-only: committed scenario runs in the left gallery
// (GET /replay/files) + clickable fleet list; center column hosts the 3D
// SwarmScene, the single NarrationStrip + Timeline recovery status bar, and
// the single ReplayControls transport bar; right column mounts the view-aware
// RightPanel (Simplified vs Advanced). Zero builder or fault-injection controls.
import { useEffect, useState } from "react";
import { backend } from "../../api/backend";
import { useReplayStore } from "../../stores/replayStore";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import SwarmScene from "../three/SwarmScene.tsx";
import NarrationStrip from "../narration/NarrationStrip";
import Timeline from "../events/Timeline";
import ReplayControls, { resetRunStores, runTitle } from "../controls/ReplayControls";
import RightPanel from "../layout/RightPanel";
import SatelliteList from "../satellites/SatelliteList";
import chrome from "../../styles/chrome.module.css";
import styles from "./ReplayPage.module.css";

const LOAD_SPEED = 10;

export default function ReplayPage() {
  const [files, setFiles] = useState<string[] | null>(null);
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
          setError(`Could not list recorded runs: ${err instanceof Error ? err.message : "unknown error"}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadRun(filename: string): Promise<void> {
    setBusyFile(filename);
    setError(null);
    try {
      resetRunStores();
      useReplayStore.getState().setPlaybackSpeed(LOAD_SPEED);
      useUiStore.getState().setRunSpeed(LOAD_SPEED);
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
        <aside
          id="replay-gallery"
          tabIndex={-1}
          className={`${chrome.panel} ${styles.gallery}`}
          aria-label="Replay runs"
        >
          <h2 className={chrome.panelTitle}>Recorded runs</h2>
          <p className={chrome.hint}>
            Pick a run to replay it and scrub through the recovery.
          </p>
          {files === null ? (
            <p className={chrome.hint}>Loading runs…</p>
          ) : files.length === 0 ? (
            <p className={chrome.hint}>No recorded runs yet.</p>
          ) : (
            <ul className={styles.runList}>
              {files.map((f) => {
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
                      <span className={styles.runName}>{runTitle(f)}</span>
                      {active && scenario !== null && (
                        <span className={styles.runScenario}>Now playing</span>
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
              <p className={chrome.hint}>Loading {runTitle(busyFile)}…</p>
            )}
          </div>
          <div className={styles.fleetSection}>
            <h2 className={chrome.panelTitle}>Satellites (click one to inspect)</h2>
            <SatelliteList />
          </div>
        </aside>

        <div className={styles.content}>
          <section className={`${chrome.panel} ${styles.scenePanel}`} aria-label="Swarm 3D view">
            <SwarmScene />
          </section>
          <div className={styles.storyZone}>
            <NarrationStrip />
            <Timeline />
          </div>
          <ReplayControls />
        </div>

        <RightPanel />
      </div>
    </div>
  );
}

export { ReplayPage };
