// UI store — FRONTEND_SPEC §15.2. View preferences only; no simulation data.
import { create } from "zustand";

export type CameraMode = "free" | "formation" | "follow";

interface UiStore {
  showLabels: boolean;
  showTrails: boolean;
  showFormationLines: boolean;
  showTargetSlots: boolean;
  showDebugPanel: boolean;
  presentationMode: boolean;
  selectedSatelliteId: string | null;
  cameraMode: CameraMode;

  setShowLabels(v: boolean): void;
  setShowTrails(v: boolean): void;
  setShowFormationLines(v: boolean): void;
  setShowTargetSlots(v: boolean): void;
  toggleDebugPanel(): void;
  setPresentationMode(v: boolean): void;
  selectSatellite(id: string | null): void;
  setCameraMode(m: CameraMode): void;
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

  setShowLabels: (v) => set({ showLabels: v }),
  setShowTrails: (v) => set({ showTrails: v }),
  setShowFormationLines: (v) => set({ showFormationLines: v }),
  setShowTargetSlots: (v) => set({ showTargetSlots: v }),
  toggleDebugPanel: () => set((s) => ({ showDebugPanel: !s.showDebugPanel })),
  setPresentationMode: (v) => set({ presentationMode: v }),
  selectSatellite: (id) => set({ selectedSatelliteId: id }),
  setCameraMode: (m) => set({ cameraMode: m }),
}));
