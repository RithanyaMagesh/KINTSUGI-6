// Full-screen live HUD — top edge. Left: wordmark home link, mission state,
// sim clock. Right: run transport, view switch and the buttons that open the
// hidden layers (Setup, Telemetry), fullscreen and hide-HUD.
import { useReplayStore } from "../../stores/replayStore";
import { useEffect, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useSceneStore, type SceneViewMode } from "../../stores/sceneStore";
import { useUiStore } from "../../stores/uiStore";
import { backend, simulationSpeed } from "../../api/backend";
import { missionStateColor } from "../../utils/colors";
import { clock, stateLabel } from "./hudFormat";
import styles from "./ImmersiveLive.module.css";

const SPEEDS = [10, 20, 50, 100, 200] as const;

interface Props {
  setupOpen: boolean;
  telemetryOpen: boolean;
  onToggleSetup(): void;
  onToggleTelemetry(): void;
  onToggleFullscreen(): void;
  onHideHud(): void;
  spectating: boolean;
  onToggleSpectate(): void;
  isFullscreen: boolean;
}

export default function HudTopBar(p: Props) {
  const missionState = useSimStore((s) => s.missionState);
  const simTime = useSimStore((s) => s.simTime);
  const scenario = useSimStore((s) => s.scenario);
  const mode = useSimStore((s) => s.mode);
  const connection = useSimStore((s) => s.connection);
  const view = useSceneStore((s) => s.viewMode);
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false); // one request at a time: no out-of-order speed/pause
  const speed = useUiStore((s) => s.runSpeed);
  const setSpeed = useUiStore((s) => s.setRunSpeed);
  const [err, setErr] = useState<string | null>(null);

  const live = mode === "live";
  const replay = mode === "replay";

  // Pause can also be toggled from Setup or another tab: mirror the backend.
  useEffect(() => {
    if (!live && !replay) return;
    let alive = true;
    const poll = async (): Promise<void> => {
      try {
        const h = (await backend.health()) as { paused?: unknown };
        if (alive && typeof h.paused === "boolean") setPaused(h.paused);
      } catch {
        // backend unreachable: the connection dot already says so
      }
    };
    void poll();
    const t = window.setInterval(() => void poll(), 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [live, replay]);
  const color = missionStateColor(missionState);
  const connColor =
    connection === "connected"
      ? "var(--status-nominal)"
      : connection === "reconnecting"
        ? "var(--status-caution)"
        : "var(--status-failed)";

  function setView(v: SceneViewMode): void {
    useSceneStore.getState().setViewMode(v);
    useUiStore.getState().setOrbitViewMode(v);
  }

  async function togglePause(): Promise<void> {
    setErr(null);
    setBusy(true);
    try {
      if (replay) await (paused ? backend.replayResume() : backend.replayPause());
      else await (paused ? backend.simulationResume() : backend.simulationPause());
      if (replay) useReplayStore.getState().setIsPlaying(paused);
      setPaused(!paused);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not reach the simulator");
    } finally {
      setBusy(false);
    }
  }

  async function pickSpeed(v: number): Promise<void> {
    setErr(null);
    setBusy(true);
    try {
      if (replay) await backend.replaySpeed(v);
      else await simulationSpeed(v);
      if (replay) useReplayStore.getState().setPlaybackSpeed(v);
      setSpeed(v);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not change speed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <header className={styles.top}>
      <div className={styles.topLeft}>
        <a href="#/" className={styles.wordmark} aria-label="KINTSUGI-6 home">
          KINTSUGI-6
        </a>
        <div className={styles.stateBlock} role="status" aria-live="polite">
          <span className={styles.stateDot} style={{ background: color }} aria-hidden="true" />
          <span className={styles.stateText} style={{ color }}>
            {stateLabel(missionState)}
          </span>
          <span className={styles.clock} title="Simulation time">
            {clock(simTime)}
          </span>
        </div>
        {scenario !== null && <span className={styles.scenario}>{scenario.replace(/\.json$/, "").replace(/_/g, " ")}</span>}
        <span className={styles.conn} title={`Backend ${connection}`}>
          <span className={styles.connDot} style={{ background: connColor }} aria-hidden="true" />
          <span className={styles.srOnly}>Backend {connection}</span>
        </span>
      </div>

      <div className={styles.topRight}>
        {(live || replay) && (
          <div className={styles.group} role="group" aria-label="Run speed">
            <button type="button" className={styles.hudBtn} disabled={busy} onClick={() => void togglePause()}>
              {paused ? "Resume" : "Pause"}
            </button>
            {SPEEDS.map((v) => (
              <button
                key={v}
                type="button"
                className={styles.seg}
                aria-pressed={speed === v}
                disabled={busy}
                onClick={() => void pickSpeed(v)}
                title={`Run at ${v}× real time`}
              >
                {v}×
              </button>
            ))}
          </div>
        )}
        <div className={styles.group} role="group" aria-label="3D view">
          <button type="button" className={styles.seg} aria-pressed={view === "global"} onClick={() => setView("global")}>
            Earth
          </button>
          <button type="button" className={styles.seg} aria-pressed={view === "local"} onClick={() => setView("local")}>
            Formation
          </button>
        </div>
        <button
          type="button"
          className={styles.hudBtn}
          aria-pressed={p.spectating}
          onClick={p.onToggleSpectate}
          title="Ride along with each satellite (← → to switch)"
        >
          Spectate <kbd className={styles.kbd}>V</kbd>
        </button>
        <button type="button" className={styles.hudBtn} aria-pressed={p.setupOpen} onClick={p.onToggleSetup}>
          Setup <kbd className={styles.kbd}>S</kbd>
        </button>
        <button type="button" className={styles.hudBtn} aria-pressed={p.telemetryOpen} onClick={p.onToggleTelemetry}>
          Telemetry <kbd className={styles.kbd}>T</kbd>
        </button>
        <button
          type="button"
          className={styles.iconBtn}
          onClick={p.onToggleFullscreen}
          aria-label={p.isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
          title={p.isFullscreen ? "Exit fullscreen (F)" : "Fullscreen (F)"}
        >
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            {p.isFullscreen ? (
              <path d="M6 2v4H2M10 2v4h4M6 14v-4H2M10 14v-4h4" />
            ) : (
              <path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4" />
            )}
          </svg>
        </button>
        <button type="button" className={styles.iconBtn} onClick={p.onHideHud} aria-label="Hide interface" title="Hide interface (H)">
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8 12.1 12.5 8 12.5 1.5 8 1.5 8z" />
            <path d="M2.5 13.5l11-11" />
          </svg>
        </button>
      </div>
      {err !== null && <p className={styles.topErr}>{err}</p>}
    </header>
  );
}
