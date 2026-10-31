// SwarmScene — FRONTEND_SPEC §7.2/§14. Thin React wrapper around the plain
// Three.js SwarmSceneController.
// Features the two-view 3D toggle (Earth | Formation)
// and adapts overlay controls to Simplified vs Advanced view mode.
import { useEffect, useRef, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { useSceneStore, type SceneViewMode } from "../../stores/sceneStore";
import { eventText, stateLabel } from "../live/hudFormat";
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
  const viewMode = useUiStore((s) => s.viewMode);
  const orbitViewMode = useSceneStore((s) => s.viewMode);
  const setSceneViewMode = useSceneStore((s) => s.setViewMode);
  const setUiOrbitViewMode = useUiStore((s) => s.setOrbitViewMode);
  const [notice, setNotice] = useState<{ title: string; body: string } | null>(null);
  const [banner, setBanner] = useState<{ text: string; token: string } | null>(null);
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
          body: "Start the backend, then reload this page.",
        });
      } else if (satellites.length === 0) {
        if (mode === "stopped") {
          setNotice({
            title: "Simulation ready",
            body: immersive
              ? "Open Setup (S) and press Start live simulation."
              : useUiStore.getState().route === "replay"
                ? "Pick a run to replay."
                : "Open the Live simulation page to start a run.",
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
            ? eventText(critical.message)
            : stateLabel(bannerState),
        token:
          bannerState === "FAILURE_DETECTED"
            ? "var(--status-failed)"
            : bannerState === "RECONFIGURING"
              ? "var(--status-caution)"
              : bannerState === "RECOVERED"
                ? "var(--status-repaired)"
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

  if (immersive) {
    return (
      <div className={`${styles.viewport} ${styles.viewportImmersive}`}>
        <div ref={hostRef} className={styles.canvasHost} />
        {notice !== null && (
          <div className={`${styles.stateNotice} ${styles.stateNoticeImmersive}`}>
            <strong>{notice.title}</strong>
            {notice.body !== "" && <span>{notice.body}</span>}
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
          {/* Two-view switcher: whole orbit around Earth vs close-up of the formation */}
          <div className={styles.viewSwitcher} role="group" aria-label="3D view mode">
            <button
              type="button"
              className={`${styles.viewBtn} ${orbitViewMode === "global" ? styles.viewBtnActive : ""}`}
              onClick={() => selectOrbitViewMode("global")}
              aria-pressed={orbitViewMode === "global"}
            >
              Earth
            </button>
            <button
              type="button"
              className={`${styles.viewBtn} ${orbitViewMode === "local" ? styles.viewBtnActive : ""}`}
              onClick={() => selectOrbitViewMode("local")}
              aria-pressed={orbitViewMode === "local"}
            >
              Formation
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

        {viewMode === "advanced" && (
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
          ? "Swarm orbiting Earth"
          : "Close-up of the formation"}
      </div>

      {notice !== null && (
        <div className={styles.stateNotice}>
          <strong>{notice.title}</strong>
          {notice.body !== "" && <span>{notice.body}</span>}
        </div>
      )}
    </div>
  );
}
