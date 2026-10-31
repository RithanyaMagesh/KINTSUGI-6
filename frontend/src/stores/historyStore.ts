// Chart history — FRONTEND_SPEC §19: charts update at 2-5 Hz and history is
// limited. The sampler (useFrameHistory) subscribes to simStore OUTSIDE React
// render (no re-render per WS message) and appends one sample per 500 ms of
// wall-clock — wall-clock is used for the sampling cadence only (§19 allows
// throttling); every VALUE in a sample comes from the stream or a derivation
// on streamed values. Sim time is never advanced here.
import { create } from "zustand";
import { useSimStore } from "./simStore";
import { useEffect } from "react";
import { fitFormation } from "../utils/geometry";

export interface ChartSample {
  t: number; // sim time [s] — from the data, never the clock
  coverage: number | null;
  minSep: number | null;
  deviation: number | null; // derived from measured positions (geometry.ts)
  dv: Record<string, number>; // satellite id -> dv_used [m/s] (streamed)
}

export interface ChartMarker {
  t: number;
  label: string; // mission-state literal from the backend enum
  level: "critical" | "caution" | "info";
}

const MAX_SAMPLES = 900; // ~2 s/sim-sampling keeps two_failure (~17k s) covered at speed 100
const MAX_MARKERS = 24;

interface HistoryStore {
  samples: ChartSample[];
  markers: ChartMarker[];
  minSepRef: number | null; // first measured min_sep of the session
  push(sample: ChartSample): void;
  mark(marker: ChartMarker): void;
  reset(): void;
}

export const useHistoryStore = create<HistoryStore>((set) => ({
  samples: [],
  markers: [],
  minSepRef: null,

  push: (sample) =>
    set((s) => ({
      samples:
        s.samples.length > 0 && s.samples[s.samples.length - 1].t === sample.t
          ? s.samples
          : [...s.samples, sample].slice(-MAX_SAMPLES),
    })),

  mark: (marker) =>
    set((s) => ({
      markers: [...s.markers, marker].slice(-MAX_MARKERS),
    })),

  reset: () => set({ samples: [], markers: [], minSepRef: null }),
}));

const SAMPLE_INTERVAL_MS = 500; // §19 chart cadence: 2 Hz

/** Subscribe to simStore and record chart samples + mission-state markers.
 * Mount once (App). Wall-clock gates the cadence only; values are streamed. */
export function useFrameHistory(): void {
  useEffect(() => {
    let lastSampleAt = 0;
    let lastT: number | null = null;
    let lastState: string | null = null;

    const unsubSim = useSimStore.subscribe((s) => {
      if (s.satellites.length === 0) return; // nothing measured yet
      const now = Date.now(); // sampling cadence only (§19)
      const stateChanged = s.missionState !== lastState && s.missionState !== null;
      const tChanged = s.simTime !== lastT;
      if (!tChanged || (!stateChanged && now - lastSampleAt < SAMPLE_INTERVAL_MS)) return;
      lastSampleAt = now;
      lastT = s.simTime;

      const nSeats = Math.max(s.satellites.length, 1);
      const fit = fitFormation(s.satellites, nSeats);
      const minSep = s.metrics.minSep ?? null;
      const minSepRef = useHistoryStore.getState().minSepRef;

      const dv: Record<string, number> = {};
      for (const sat of s.satellites) dv[sat.id] = sat.dv_used; // index iteration

      useHistoryStore.getState().push({
        t: s.simTime ?? 0,
        coverage: s.metrics.coverage ?? null,
        minSep,
        deviation: fit.ok ? fit.deviationMean : null,
        dv,
      });
      if (minSepRef === null && minSep !== null) {
        useHistoryStore.setState({ minSepRef: minSep });
      }

      if (stateChanged) {
        lastState = s.missionState;
        const label = s.missionState as string;
        const level: ChartMarker["level"] =
          label === "FAILURE_DETECTED"
            ? "critical"
            : label === "REPLANNING" || label === "RECONFIGURING"
              ? "caution"
              : "info";
        if (label !== "NOMINAL") {
          useHistoryStore.getState().mark({ t: s.simTime ?? 0, label, level });
        }
      }
    });

    const unsubResetWatch = useSimStore.subscribe((s, prev) => {
      // A fresh session (new run, replay load, restart or backward seek) clears
      // the charts; failure-free runs have no events, so time going backwards counts too.
      const timeWentBack = s.simTime !== null && prev.simTime !== null && s.simTime < prev.simTime;
      const satsCleared = s.satellites.length === 0 && prev.satellites.length > 0;
      if ((s.events.length === 0 && prev.events.length > 0) || timeWentBack || satsCleared) {
        useHistoryStore.getState().reset();
        lastState = null;
        lastT = null;
      }
    });

    return () => {
      unsubSim();
      unsubResetWatch();
    };
  }, []);
}
