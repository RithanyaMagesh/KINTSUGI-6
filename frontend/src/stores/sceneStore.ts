// 3D Scene perspective store — manages the 'Global Orbit' ("global") vs
// 'Formation Array' ("local") 3D camera perspective state.
import { create } from "zustand";

export type SceneViewMode = "global" | "local";

interface SceneStore {
  viewMode: SceneViewMode;
  setViewMode(mode: SceneViewMode): void;
  toggleViewMode(): void;
}

export const useSceneStore = create<SceneStore>((set, get) => ({
  viewMode: "global",
  setViewMode: (viewMode) => set({ viewMode }),
  toggleViewMode: () =>
    set({ viewMode: get().viewMode === "global" ? "local" : "global" }),
}));
