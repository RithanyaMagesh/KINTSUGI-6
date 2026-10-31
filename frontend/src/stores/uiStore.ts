// UI store — FRONTEND_SPEC §15.2. View preferences only; no simulation data.
// Supports Simplified vs Advanced workspace views, Global Earth Orbit vs Local
// Formation Array 3D views, and Dark vs Light theme modes.
import { create } from "zustand";
import { clearColorCache } from "../components/three/sceneColors";

export type CameraMode = "free" | "formation" | "follow";
export type ViewMode = "simplified" | "advanced";
export type OrbitViewMode = "global" | "local";
export type ThemeMode = "dark" | "light";

/** Hash-router pages (round 2). pages/Router.tsx owns the hashchange wiring;
 * TopStatusBar reads `route` for the active nav underline. */
export type Route = "landing" | "live" | "replay" | "tutorial" | "faq" | "docs";

/** Hash → route. Unknown or missing hash resolves to landing. */
export function routeFromHash(hash: string): Route {
  const name = hash.replace(/^#\/?/, "");
  switch (name) {
    case "live":
    case "replay":
    case "tutorial":
    case "faq":
    case "docs":
      return name;
    default:
      return "landing";
  }
}

function initialRoute(): Route {
  try {
    return routeFromHash(window.location.hash);
  } catch {
    return "landing";
  }
}

function initialTheme(): ThemeMode {
  try {
    const saved = window.localStorage.getItem("cubesat_theme");
    const theme: ThemeMode = saved === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    return theme;
  } catch {
    return "dark";
  }
}

interface UiStore {
  showLabels: boolean;
  showTrails: boolean;
  showFormationLines: boolean;
  showTargetSlots: boolean;
  showDebugPanel: boolean;
  presentationMode: boolean;
  selectedSatelliteId: string | null;
  cameraMode: CameraMode;
  replayModeRequested: boolean;
  route: Route;
  viewMode: ViewMode;
  orbitViewMode: OrbitViewMode;
  theme: ThemeMode;
  /** Playback speed of the current run (x real time) as last set from this
   * console; null = unknown (run started elsewhere). */
  runSpeed: number | null;

  setShowLabels(v: boolean): void;
  setShowTrails(v: boolean): void;
  setShowFormationLines(v: boolean): void;
  setShowTargetSlots(v: boolean): void;
  toggleDebugPanel(): void;
  setPresentationMode(v: boolean): void;
  selectSatellite(id: string | null): void;
  setCameraMode(m: CameraMode): void;
  setReplayModeRequested(v: boolean): void;
  setRoute(r: Route): void;
  setViewMode(m: ViewMode): void;
  setOrbitViewMode(m: OrbitViewMode): void;
  setTheme(t: ThemeMode): void;
  toggleTheme(): void;
  setRunSpeed(v: number | null): void;
}

export const useUiStore = create<UiStore>((set, get) => ({
  showLabels: true,
  showTrails: true,
  showFormationLines: true,
  showTargetSlots: true,
  showDebugPanel: false,
  presentationMode: false,
  selectedSatelliteId: null,
  cameraMode: "free",
  replayModeRequested: false,
  route: initialRoute(),
  viewMode: "simplified",
  orbitViewMode: "global",
  theme: initialTheme(),
  runSpeed: null,
  setRunSpeed: (v) => set({ runSpeed: v }),

  setShowLabels: (v) => set({ showLabels: v }),
  setShowTrails: (v) => set({ showTrails: v }),
  setShowFormationLines: (v) => set({ showFormationLines: v }),
  setShowTargetSlots: (v) => set({ showTargetSlots: v }),
  toggleDebugPanel: () => set((s) => ({ showDebugPanel: !s.showDebugPanel })),
  setPresentationMode: (v) => set({ presentationMode: v }),
  selectSatellite: (id) => set({ selectedSatelliteId: id }),
  setCameraMode: (m) => set({ cameraMode: m }),
  setReplayModeRequested: (v) => set({ replayModeRequested: v }),
  setRoute: (r) => set({ route: r }),
  setViewMode: (m) => set({ viewMode: m }),
  setOrbitViewMode: (m) => set({ orbitViewMode: m }),
  setTheme: (t) => {
    try {
      document.documentElement.dataset.theme = t;
      window.localStorage.setItem("cubesat_theme", t);
    } catch {
      // ignore storage errors
    }
    clearColorCache();
    set({ theme: t });
  },
  toggleTheme: () => {
    const next: ThemeMode = get().theme === "dark" ? "light" : "dark";
    get().setTheme(next);
  },
}));
