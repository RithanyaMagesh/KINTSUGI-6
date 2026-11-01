// Live simulation page — route #/live. Full-screen 3D: the Earth and the
// swarm fill the window; the interface floats over it as glass and stays out
// of the way. At first glance only the mission state, the clock and five key
// readouts show. Setup (S) and Telemetry (T) slide in on demand; H hides the
// whole interface for a clean stage; F goes fullscreen.
import RunSummaryCard from "./RunSummaryCard";
import { useCallback, useEffect, useRef, useState } from "react";
import SwarmScene from "../three/SwarmScene.tsx"; // explicit: macOS is case-insensitive and would resolve swarmScene.ts
import type { SwarmSceneController } from "../three/swarmScene";
import { useSimStore } from "../../stores/simStore";
import { useSceneStore } from "../../stores/sceneStore";
import { useUiStore } from "../../stores/uiStore";
import ScenarioBuilder from "./ScenarioBuilder";
import FailureInjectionPanel from "../controls/FailureInjectionPanel";
import SatelliteList from "../satellites/SatelliteList";
import SelectedSatellitePanel from "../satellites/SelectedSatellitePanel";
import NarrationStrip from "../narration/NarrationStrip";
import HudTopBar from "./HudTopBar";
import HudMetrics from "./HudMetrics";
import PhaseRail from "./PhaseRail";
import TelemetryDrawer from "./TelemetryDrawer";
import SceneControls from "./SceneControls";
import SpectatorBar, { spectateStart, spectateStep } from "./SpectatorBar";
import styles from "./ImmersiveLive.module.css";

function typingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el instanceof HTMLInputElement) {
    // checkboxes, radios and sliders don't take typed text: shortcuts still work
    return !["checkbox", "radio", "range", "button", "submit"].includes(el.type);
  }
  return el.tagName === "TEXTAREA" || el.isContentEditable;
}

export default function LivePage() {
  const [setupOpen, setSetupOpen] = useState(false);
  const [telemetryOpen, setTelemetryOpen] = useState(false);
  const [hudHidden, setHudHidden] = useState(false);
  const [spectating, setSpectating] = useState(false);
  const [isFs, setIsFs] = useState(false);
  const controllerRef = useRef<SwarmSceneController | null>(null);
  const [controller, setController] = useState<SwarmSceneController | null>(null);
  const selectedId = useUiStore((s) => s.selectedSatelliteId);
  const hasSats = useSimStore((s) => s.satellites.length > 0);
  const missionState = useSimStore((s) => s.missionState);

  const onController = useCallback((c: SwarmSceneController | null) => {
    controllerRef.current = c;
    setController(c);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement !== null) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.();
  }, []);

  useEffect(() => {
    const onFs = () => setIsFs(document.fullscreenElement !== null);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  // Open Setup on first visit when nothing is running, so the next step is obvious.
  useEffect(() => {
    if (useSimStore.getState().satellites.length === 0) setSetupOpen(true);
  }, []);

  const exitSpectate = useCallback(() => {
    setSpectating(false);
    useUiStore.getState().selectSatellite(null); // flies back out to the Earth
  }, []);
  const enterSpectate = useCallback(() => {
    if (useSimStore.getState().satellites.length === 0) return;
    setSpectating(true);
    spectateStart();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "escape" && e.target instanceof HTMLElement) e.target.blur();
      else if (typingTarget(e.target)) return;
      if (k === "escape") {
        if (hudHidden) setHudHidden(false);
        else if (setupOpen || telemetryOpen) {
          setSetupOpen(false);
          setTelemetryOpen(false);
        }
        else if (spectating) exitSpectate();
        else useUiStore.getState().selectSatellite(null);
        return;
      }
      if (k === "v") {
        if (spectating) exitSpectate();
        else enterSpectate();
      } else if (k === "arrowright" || k === "arrowleft") {
        if (!spectating) enterSpectate(); // first press lands on the leader
        else spectateStep(k === "arrowright" ? 1 : -1);
      } else if (k === "h") setHudHidden((v) => !v);
      else if (k === "s" && !hudHidden) setSetupOpen((v) => !v);
      else if (k === "t" && !hudHidden) setTelemetryOpen((v) => !v);
      else if (k === "f") toggleFullscreen();
      else if (k === "1" || k === "2") {
        const v = k === "1" ? "global" : "local";
        useSceneStore.getState().setViewMode(v);
        useUiStore.getState().setOrbitViewMode(v);
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setupOpen, telemetryOpen, hudHidden, spectating, toggleFullscreen, exitSpectate, enterSpectate]);

  const showSelected = selectedId !== null && !telemetryOpen && !hudHidden;

  return (
    <div
      className={styles.stage}
      data-stage="space"
      data-state={missionState ?? undefined}
      data-drawer={setupOpen || telemetryOpen || undefined}
    >
      <SwarmScene immersive onController={onController} />

      <div className={styles.hud} data-hidden={hudHidden || undefined} aria-hidden={hudHidden || undefined}>
        <HudTopBar
          setupOpen={setupOpen}
          telemetryOpen={telemetryOpen}
          onToggleSetup={() => setSetupOpen((v) => !v)}
          onToggleTelemetry={() => setTelemetryOpen((v) => !v)}
          onToggleFullscreen={toggleFullscreen}
          onHideHud={() => setHudHidden(true)}
          spectating={spectating}
          onToggleSpectate={() => (spectating ? exitSpectate() : enterSpectate())}
          isFullscreen={isFs}
        />

        <SceneControls controller={controller} />

        {spectating && <SpectatorBar onExit={exitSpectate} />}

        <aside className={styles.drawerLeft} data-open={setupOpen || undefined} aria-label="Setup">
          <div className={styles.drawerHead}>
            <h2 className={styles.drawerTitle}>Setup</h2>
            <button type="button" className={styles.closeBtn} onClick={() => setSetupOpen(false)} aria-label="Close setup">
              ×
            </button>
          </div>
          <div className={styles.drawerScroll}>
            <ScenarioBuilder />
            <FailureInjectionPanel />
            <section aria-label="Satellites">
              <h3 className={styles.groupTitle}>Satellites</h3>
              <SatelliteList />
            </section>
          </div>
        </aside>

        <aside className={styles.drawerRight} data-open={telemetryOpen || undefined} aria-label="Telemetry">
          <div className={styles.drawerHead}>
            <h2 className={styles.drawerTitle}>Telemetry</h2>
            <button type="button" className={styles.closeBtn} onClick={() => setTelemetryOpen(false)} aria-label="Close telemetry">
              ×
            </button>
          </div>
          {telemetryOpen && <TelemetryDrawer />}
        </aside>

        {showSelected && (
          <aside className={styles.selectedCard} aria-label="Selected satellite">
            <div className={styles.drawerHead}>
              <h2 className={styles.drawerTitle}>{selectedId}</h2>
              <button
                type="button"
                className={styles.closeBtn}
                onClick={() => useUiStore.getState().selectSatellite(null)}
                aria-label="Close satellite details"
              >
                ×
              </button>
            </div>
            <div className={styles.selectedScroll}>
              <SelectedSatellitePanel />
            </div>
          </aside>
        )}

        <footer className={styles.bottom}>
          <RunSummaryCard />
          {hasSats && (
            <div className={styles.narration}>
              <NarrationStrip />
            </div>
          )}
          <div className={styles.bottomRow}>
            <HudMetrics />
            <PhaseRail />
          </div>
        </footer>
      </div>

      {hudHidden && (
        <button type="button" className={styles.showHud} onClick={() => setHudHidden(false)}>
          Show interface <kbd className={styles.kbd}>H</kbd>
        </button>
      )}
    </div>
  );
}
