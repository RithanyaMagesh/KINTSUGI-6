// ============================================================================
// DEV-ONLY MOCK DATA (FRONTEND_SPEC §13.6 / repo invariant 1)
//
// This file exists ONLY so the shell can be exercised visually during
// development without the backend running. NOTHING in here may appear in:
//   - the README or the pitch,
//   - screenshots presented as results or as measured numbers,
//   - the default running application.
//
// The app renders "unmeasured" everywhere unless (a) a live /ws/state frame
// or (b) an explicit dev override (import.meta.env.DEV && ?mock=1) applies
// these frames. Production builds ignore this module entirely.
// ============================================================================

import type { SimStateMessage } from "../types/events";

/** One invented nominal tick + one invented reassignment event. Values are
 * plausible-shaped, NOT measured — that is the whole point of the marking. */
export const MOCK_FRAMES: SimStateMessage[] = [
  {
    type: "sim_state",
    sim_time: 120.0,
    state: "NOMINAL",
    scenario: "mock-dev-only.json",
    seed: 0,
    sats: [
      {
        id: "SAT-1",
        role: "leader",
        status: "healthy",
        r: [0, 0, 0],
        v: [0, 0, 0],
        dv_used: 0,
        target_slot: "slot_0",
      },
      {
        id: "SAT-2",
        role: "sensor_1",
        status: "healthy",
        r: [10, 0, 0],
        v: [0, 0, 0],
        dv_used: 0,
        target_slot: "slot_1",
      },
      {
        id: "SAT-3",
        role: "sensor_2",
        status: "healthy",
        r: [-10, 0, 0],
        v: [0, 0, 0],
        dv_used: 0,
        target_slot: "slot_2",
      },
    ],
    coverage: 0.5, // INVENTED: dev rendering check only
    min_sep: 20.0, // INVENTED: dev rendering check only
    metrics: {},
  },
];

export const MOCK_EVENTS = [
  { type: "event", sim_time: 120.0, level: "info", message: "Mock event: dev rendering check" },
] as const;

/** True only in a dev build with an explicit ?mock=1 query parameter. */
export function mockEnabled(): boolean {
  return (
    import.meta.env.DEV &&
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("mock")
  );
}
