// UI store — FRONTEND_SPEC §15.2. View preferences only; no simulation data.
// Dormant missionBriefOpen + sessionStorage startup code removed in round 4
// (§3.2 #11): #/ LandingPage is the intro surface.
import { create } from "zustand";

export type CameraMode = "free" | "formation" | "follow";

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
    return "landing"; // no window (non-browser): land, never crash
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
  /** Active hash-router page (round 2). Set by pages/Router.tsx on hashchange. */
  route: Route;

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
}

export const useUiStore = create<UiStore>((set) => ({
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
}));
