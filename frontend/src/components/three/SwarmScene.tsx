// SwarmScene — FRONTEND_SPEC §7.2/§14. Thin React wrapper around the plain
// Three.js SwarmSceneController.
// Features the Two-View 3D Toggle ([ Earth orbit view | Formation array view ])
// and adapts overlay controls to Simplified vs Advanced view mode.
import { useEffect, useRef, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { useSceneStore, type SceneViewMode } from "../../stores/sceneStore";
import { backend } from "../../api/backend";
import { SwarmSceneController, type CameraPreset } from "./swarmScene";
import chrome from "../../styles/chrome.module.css";
import styles from "./SwarmScene.module.css";

interface SwarmSceneProps {
  /** Full-screen live view: the HUD owns the controls, captions and banner,
   * so the scene renders only the canvas and the empty/connection notice. */
  immersive?: boolean;
  /** Hands the controller to the HUD (camera presets, layer toggles). */
  onController?: (controller: SwarmSceneController | null) => void;
}

export default function SwarmScene({ immersive = false, onController }: SwarmSceneProps = {}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SwarmSceneController | null>(null);
  const lastBannerRef = useRef<string | null>(null);
  const presentation = useUiStore((s) => s.presentationMode);
  const viewMode = useUiStore((s) => s.viewMode);
  const orbitViewMode = useSceneStore((s) => s.viewMode);
  const setSceneViewMode = useSceneStore((s) => s.setViewMode);
  const setUiOrbitViewMode = useUiStore((s) => s.setOrbitViewMode);
  const [notice, setNotice] = useState<{ title: string; body: string } | null>(null);
  const [banner, setBanner] = useState<{ text: string; token: string } | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [toggles, setToggles] = useState({ labels: true, trails: true, lines: true, slots: true });

  function selectOrbitViewMode(mode: SceneViewMode): void {
    setSceneViewMode(mode);
    setUiOrbitViewMode(mode);
  }

  // Connection + empty states (§20: never a blank screen).
  useEffect(() => {
    const render = (): void => {
      const { connection, satellites, mode } = useSimStore.getState();
      if (mode === "replay") {
        setNotice(null);
      } else if (connection === "reconnecting") {
        setNotice({ title: "Connection lost. Reconnecting…", body: "" });
      } else if (connection === "disconnected") {
        setNotice({
          title: "Backend disconnected.",
          body: "Live simulation unavailable. Switch to Replay Mode.",
        });
      } else if (satellites.length === 0) {
        if (mode === "stopped") {
          setNotice({
            title: "Simulation ready",
            body: immersive
              ? "Open Setup (S) and press Start live simulation."
              : "Configure your swarm on the left and press Start live simulation.",
          });
        } else {
          setNotice({ title: "Waiting for simulation data", body: "" });
        }
      } else {
        setNotice(null);
      }
    };
    render();
    return useSimStore.subscribe(render);
  }, [immersive]);

  // Scene lifetime + imperative data feed (no per-message React render).
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const controller = new SwarmSceneController(host, (id) => {
      useUiStore.getState().selectSatellite(id);
    });
    sceneRef.current = controller;
    onController?.(controller);
    controller.setOrbitViewMode(useSceneStore.getState().viewMode);

    let prevOrbitMode = useSceneStore.getState().viewMode;
    let prevTheme = useUiStore.getState().theme;
    let prevSel = useUiStore.getState().selectedSatelliteId;

    const unsubSim = useSimStore.subscribe((s) => {
      controller.update({
        satellites: s.satellites,
        selectedId: useUiStore.getState().selectedSatelliteId,
        missionState: s.missionState,
        simTime: s.simTime ?? undefined,
      });
      const state = s.missionState;
      const bannerState =
        state === "FAILURE_DETECTED" ||
        state === "REPLANNING" ||
        state === "RECONFIGURING" ||
        state === "RECOVERED"
          ? state
          : null;
      if (bannerState === null && lastBannerRef.current === null) return;
      lastBannerRef.current = bannerState;
      if (bannerState === null) {
        setBanner(null);
        return;
      }
      const critical = [...s.events].reverse().find((e) => e.level === "critical");
      setBanner({
        text:
          bannerState === "FAILURE_DETECTED" && critical !== undefined
            ? critical.message
            : bannerState,
        token:
          bannerState === "FAILURE_DETECTED"
            ? "var(--status-failed)"
            : bannerState === "RECONFIGURING"
              ? "var(--status-caution)"
              : "var(--status-info)",
      });
    });

    const unsubScene = useSceneStore.subscribe((s) => {
      if (s.viewMode !== prevOrbitMode) {
        prevOrbitMode = s.viewMode;
        controller.setOrbitViewMode(s.viewMode);
      }
    });

    const unsubUi = useUiStore.subscribe((s) => {
      if (s.orbitViewMode !== prevOrbitMode) {
        prevOrbitMode = s.orbitViewMode;
        useSceneStore.getState().setViewMode(s.orbitViewMode);
        controller.setOrbitViewMode(s.orbitViewMode);
      }
      if (immersive && s.selectedSatelliteId !== prevSel) {
        prevSel = s.selectedSatelliteId;
        controller.focusSatellite(prevSel); // click a satellite: fly to it
      }
      if (s.theme !== prevTheme) {
        prevTheme = s.theme;
        controller.refreshTheme();
      }
      controller.update({
        satellites: useSimStore.getState().satellites,
        selectedId: s.selectedSatelliteId,
        missionState: useSimStore.getState().missionState,
        simTime: useSimStore.getState().simTime ?? undefined,
      });
    });

    return () => {
      unsubSim();
      unsubScene();
      unsubUi();
      onController?.(null);
      controller.dispose();
      sceneRef.current = null;
    };
  }, []);

  function applyPreset(preset: CameraPreset): void {
    const controller = sceneRef.current;
    if (controller === null) return;
    const { satellites } = useSimStore.getState();
    const focus =
      satellites.find((s) => s.status === "failed") ??
      satellites.find((s) => s.id === useUiStore.getState().selectedSatelliteId) ??
      null;
    controller.applyPreset(preset, focus);
  }

  function setToggle(key: keyof typeof toggles, value: boolean): void {
    const next = { ...toggles, [key]: value };
    setToggles(next);
    sceneRef.current?.setToggles(next);
  }

  async function openReplay(): Promise<void> {
    setReplayError(null);
    try {
      const { files } = await backend.replayFiles();
      if (files.length === 0) {
        setReplayError("No replay logs available. Generate one with: uv run python -m cubesat.run");
        return;
      }
      const sim = useSimStore.getState();
      sim.reset();
      await backend.replayLoad(files[files.length - 1]);
      sim.setMode("replay");
    } catch (err) {
      setReplayError(err instanceof Error ? err.message : "Replay could not be loaded");
    }
  }

  if (immersive) {
    return (
      <div className={`${styles.viewport} ${styles.viewportImmersive}`}>
        <div ref={hostRef} className={styles.canvasHost} />
        {notice !== null && (
          <div className={`${styles.stateNotice} ${styles.stateNoticeImmersive}`}>
            <strong>{notice.title}</strong>
            {notice.body !== "" && <span>{notice.body}</span>}
            {notice.title.startsWith("Backend disconnected") && (
              <button className={chrome.btn} onClick={() => void openReplay()}>
                Open replay mode
              </button>
            )}
            {replayError !== null && <span>{replayError}</span>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={styles.viewport}>
      <div ref={hostRef} className={styles.canvasHost} />
      <div className={styles.overlay}>
        <div className={styles.controls}>
          {/* Prominent Two-View Switcher: Global Orbit vs Formation Array */}
          <div className={styles.viewSwitcher} role="group" aria-label="3D view mode">
            <button
              type="button"
              className={`${styles.viewBtn} ${orbitViewMode === "global" ? styles.viewBtnActive : ""}`}
              onClick={() => selectOrbitViewMode("global")}
              aria-pressed={orbitViewMode === "global"}
            >
              Global Orbit
            </button>
            <button
              type="button"
              className={`${styles.viewBtn} ${orbitViewMode === "local" ? styles.viewBtnActive : ""}`}
              onClick={() => selectOrbitViewMode("local")}
              aria-pressed={orbitViewMode === "local"}
            >
              Formation Array
            </button>
          </div>

          <button
            type="button"
            className={chrome.btn}
            onClick={() => applyPreset(orbitViewMode === "global" ? "reset" : "formation")}
          >
            Reset camera
          </button>
          <button
            type="button"
            className={chrome.btn}
            onClick={() => applyPreset("focus")}
          >
            Track failed
          </button>
        </div>

        {!presentation && viewMode === "advanced" && (
          <div className={styles.toggles}>
            {(
              [
                ["labels", "Labels"],
                ["trails", "Trails"],
                ["lines", "Formation links"],
                ["slots", "Target slots"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={toggles[key]}
                  onChange={(e) => setToggle(key, e.target.checked)}
                />
                {label}
              </label>
            ))}
          </div>
        )}

        {banner !== null && (
          <div className={styles.banner} style={{ color: banner.token }} role="status">
            {banner.text}
          </div>
        )}
      </div>

      <div className={styles.earthCaption}>
        {orbitViewMode === "global"
          ? "Global Orbit · Constellation orbiting Earth in inclined LEO"
          : "Formation Array · Local 2:1 Clohessy-Wiltshire relative grid"}
      </div>
      <div className={styles.axesHint}>
        {orbitViewMode === "global"
          ? "Click any satellite to inspect or inject a fault"
          : "LVLH: x radial · y along-track · z cross-track"}
      </div>

      {notice !== null && (
        <div className={styles.stateNotice}>
          <strong>{notice.title}</strong>
          {notice.body !== "" && <span>{notice.body}</span>}
          {notice.title.startsWith("Backend disconnected") && (
            <button className={chrome.btn} onClick={() => void openReplay()}>
              Open replay mode
            </button>
          )}
          {replayError !== null && <span>{replayError}</span>}
        </div>
      )}
    </div>
  );
}
