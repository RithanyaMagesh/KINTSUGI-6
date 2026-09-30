// Replay store — FRONTEND_SPEC §15.3. The G5 backend drives replay
// server-side (POST /replay/load + frames over /ws/state); this store tracks
// playback UI state and the loaded file. frames[] stays empty until a
// client-side replay path exists — never filled with synthetic data.
import { create } from "zustand";
import type { SimFrame } from "../types/telemetry";

interface ReplayStore {
  isPlaying: boolean;
  currentTime: number;
  playbackSpeed: number;
  frames: SimFrame[];
  activeFile: string | null;

  setIsPlaying(v: boolean): void;
  setCurrentTime(t: number): void;
  setPlaybackSpeed(s: number): void;
  setActiveFile(name: string | null): void;
  setFrames(frames: SimFrame[]): void;
}

export const useReplayStore = create<ReplayStore>((set) => ({
  isPlaying: false,
  currentTime: 0,
  playbackSpeed: 100, // backend SessionEnrich default speed (cubesat/wire.py StartRequest)
  frames: [],
  activeFile: null,

  setIsPlaying: (v) => set({ isPlaying: v }),
  setCurrentTime: (t) => set({ currentTime: t }),
  setPlaybackSpeed: (s) => set({ playbackSpeed: s }),
  setActiveFile: (name) => set({ activeFile: name }),
  setFrames: (frames) => set({ frames }),
}));
