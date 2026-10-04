// UI store — FRONTEND_SPEC §15.2. View preferences only; no simulation data.
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

/** sessionStorage key marking the mission brief as shown this browser session
 * (the brief is the first-load landing page; "?" in the top bar reopens it).
 * Session-scoped by design: a fresh tab is a fresh audience member. */
const MISSION_BRIEF_SEEN_KEY = "cubesat.missionBriefSeen";

function missionBriefSeenThisSession(): boolean {
  try {
    return window.sessionStorage.getItem(MISSION_BRIEF_SEEN_KEY) === "1";
  } catch {
    return false; // storage blocked (privacy mode): show the brief, never crash
  }
}

function markMissionBriefSeen(): void {
  try {
    window.sessionStorage.setItem(MISSION_BRIEF_SEEN_KEY, "1");
  } catch {
    // storage blocked: the brief simply re-shows next reload — acceptable
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
  /** Mission brief modal (onboarding/MissionBrief.tsx) is on screen. True on
   * first load of a browser session, reopened by the top-bar "?" button. */
  missionBriefOpen: boolean;
  /** Set when the brief's "Open replay mode" button fires. The brief also
   * loads the latest replay log directly (same path as SwarmScene's §20.1
   * fallback button) so the button works today; components that want to react
   * to the request (e.g. preselecting a log in ReplayControls) read this flag. */
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
  setMissionBriefOpen(v: boolean): void;
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
  missionBriefOpen: !missionBriefSeenThisSession(),
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
  // Closing the brief (either footer button or Escape) marks it seen for this
  // session; "?" reopens it without clearing the flag.
  setMissionBriefOpen: (v) => {
    if (!v) markMissionBriefSeen();
    set({ missionBriefOpen: v });
  },
  setReplayModeRequested: (v) => set({ replayModeRequested: v }),
  setRoute: (r) => set({ route: r }),
}));
