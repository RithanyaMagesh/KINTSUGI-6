// Full-screen live HUD — map-style camera controls on the right edge: zoom,
// reset, follow the failed satellite, and the scene layers.
import { useState } from "react";
import type { SwarmSceneController } from "../three/swarmScene";
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { useSceneStore } from "../../stores/sceneStore";
import styles from "./ImmersiveLive.module.css";

type Layer = "labels" | "trails" | "lines" | "slots";
const LAYERS: Array<[Layer, string]> = [
  ["labels", "Names"],
  ["trails", "Trails"],
  ["lines", "Links"],
  ["slots", "Slots"],
];

export default function SceneControls({ controller }: { controller: SwarmSceneController | null }) {
  const [layers, setLayers] = useState({ labels: true, trails: true, lines: true, slots: true });
  const [layersOpen, setLayersOpen] = useState(false);
  const view = useSceneStore((s) => s.viewMode);
  const anyFailed = useSimStore((s) => s.satellites.some((x) => x.status === "failed"));

  function preset(p: "reset" | "focus"): void {
    if (controller === null) return;
    const ui = useUiStore.getState();
    if (p === "reset") {
      ui.selectSatellite(null); // also ends any follow
      controller.applyPreset(view === "global" ? "reset" : "formation", null);
      return;
    }
    // Follow = select: the scene's follow-cam does the rest.
    const sats = useSimStore.getState().satellites;
    const pick = sats.find((s) => s.id === ui.selectedSatelliteId) ?? sats.find((s) => s.status === "failed");
    if (pick !== undefined) ui.selectSatellite(pick.id);
  }

  function toggle(k: Layer): void {
    const next = { ...layers, [k]: !layers[k] };
    setLayers(next);
    controller?.setToggles(next);
  }

  return (
    <div className={styles.camStack} aria-label="Camera">
      <div className={styles.camGroup}>
        <button type="button" className={styles.camBtn} onClick={() => controller?.zoom(0.8)} aria-label="Zoom in" title="Zoom in (or scroll)">
          +
        </button>
        <button type="button" className={styles.camBtn} onClick={() => controller?.zoom(1.25)} aria-label="Zoom out" title="Zoom out (or scroll)">
          −
        </button>
      </div>
      <div className={styles.camGroup}>
        <button type="button" className={styles.camBtn} onClick={() => preset("reset")} title="Reset view" aria-label="Reset view">
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <circle cx="8" cy="8" r="5.5" />
            <path d="M8 1v3M8 12v3M1 8h3M12 8h3" />
          </svg>
        </button>
        <button
          type="button"
          className={styles.camBtn}
          onClick={() => preset("focus")}
          disabled={!anyFailed && useUiStore.getState().selectedSatelliteId === null}
          title="Follow the failed or selected satellite"
          aria-label="Follow the failed or selected satellite"
        >
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M2 5V2h3M14 5V2h-3M2 11v3h3M14 11v3h-3" />
            <circle cx="8" cy="8" r="2" />
          </svg>
        </button>
        <button
          type="button"
          className={styles.camBtn}
          aria-expanded={layersOpen}
          onClick={() => setLayersOpen((v) => !v)}
          title="Layers"
          aria-label="Layers"
        >
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M8 2l6 3-6 3-6-3 6-3z" />
            <path d="M2 8l6 3 6-3M2 11l6 3 6-3" />
          </svg>
        </button>
      </div>
      {layersOpen && (
        <div className={styles.layers} role="group" aria-label="Layers">
          {LAYERS.map(([k, label]) => (
            <label key={k} className={styles.layer}>
              <input type="checkbox" checked={layers[k]} onChange={() => toggle(k)} />
              {label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
