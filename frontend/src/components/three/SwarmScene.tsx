// SwarmScene — FRONTEND_SPEC §7.2/§14. Thin React wrapper: creates the plain
// Three.js controller (swarmScene.ts) once, feeds it from the stores via
// subscriptions (React never re-renders per WS message, §19), and renders the
// §20 connection/empty states plus the §7.3/§7.4 banners and §8.8 camera
// presets as chrome overlays.
import { useEffect, useRef, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { backend } from "../../api/backend";
import { SwarmSceneController, type CameraPreset } from "./swarmScene";
import chrome from "../../styles/chrome.module.css";
import styles from "./SwarmScene.module.css";

const PRESETS: Array<{ id: CameraPreset; label: string }> = [
  { id: "reset", label: "Reset view" },
  { id: "top", label: "Top view" },
  { id: "formation", label: "Formation view" },
  { id: "focus", label: "Focus failed" },
];

export default function SwarmScene() {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<SwarmSceneController | null>(null);
  const lastBannerRef = useRef<string | null>(null);
  const presentation = useUiStore((s) => s.presentationMode); // §6.3 hides developer toggles
  const [notice, setNotice] = useState<{ title: string; body: string } | null>(null);
  const [banner, setBanner] = useState<{ text: string; token: string } | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [toggles, setToggles] = useState({ labels: true, trails: true, lines: true, slots: true });

  // Connection + empty states (§20: never a blank screen).
  useEffect(() => {
    const render = (): void => {
      const { connection, satellites, mode } = useSimStore.getState();
      // §20 connection notices are LIVE-mode language: during replay the
      // top-bar badge carries the state, and an overlay over a playing
      // replay misleads (found in the 2026-09-30 live run).
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
        // §24.2 verbatim when the session is stopped; §6.1 waiting text otherwise.
        if (mode === "stopped") {
          setNotice({ title: "Simulation stopped.", body: "Press Start to begin." });
        } else {
          setNotice({ title: "Waiting for simulation data", body: "" });
        }
      } else {
        setNotice(null);
      }
    };
    render();
    return useSimStore.subscribe(render);
  }, []);

  // Scene lifetime + imperative data feed (no per-message React render).
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const controller = new SwarmSceneController(host, (id) => {
      useUiStore.getState().selectSatellite(id);
    });
    sceneRef.current = controller;

    const unsubSim = useSimStore.subscribe((s) => {
      controller.update({
        satellites: s.satellites,
        selectedId: useUiStore.getState().selectedSatelliteId,
        missionState: s.missionState,
      });
      // §7.3/§7.4 banner sequence: the mission-state literals themselves
      // (uppercase is a backend data value, §13.2). FAILURE_DETECTED carries
      // the latest critical event message so the judge sees WHICH satellite.
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
            ? critical.message // event message as delivered — no ALL-CAPS restyle (§13.2)
            : bannerState,
        token:
          bannerState === "FAILURE_DETECTED"
            ? "var(--status-failed)"
            : bannerState === "RECONFIGURING"
              ? "var(--status-caution)"
              : "var(--status-info)",
      });
    });
    const unsubUi = useUiStore.subscribe((s) => {
      controller.update({
        satellites: useSimStore.getState().satellites,
        selectedId: s.selectedSatelliteId,
        missionState: useSimStore.getState().missionState,
      });
    });

    return () => {
      unsubSim();
      unsubUi();
      controller.dispose();
      sceneRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    // §20.1: one button to the fallback. Loads the LAST file the backend
    // lists (the same /replay/files list ReplayControls shows).
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

  return (
    <div className={styles.viewport}>
      <div ref={hostRef} className={styles.canvasHost} />
      <div className={styles.overlay}>
        <div className={styles.controls}>
          {PRESETS.map((p) => (
            <button key={p.id} className={chrome.btn} onClick={() => applyPreset(p.id)}>
              {p.label}
            </button>
          ))}
        </div>
        {!presentation && (
          <div className={styles.toggles}>
            {(
              [
                ["labels", "Labels"],
                ["trails", "Trails"],
                ["lines", "Formation lines"],
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
      {/* Fixed scene captions — frame-of-reference honesty, mono 12px (§13.2). */}
      <div className={styles.earthCaption}>Earth - stylized, not to scale</div>
      <div className={styles.axesHint}>x radial / y along-track / z cross-track</div>
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
