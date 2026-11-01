// Event + wire-message types — FRONTEND_SPEC §16. The message union matches
// what cubesat.wire actually emits on /ws/state (see cubesat/wire.py).

export type EventLevel = "info" | "warning" | "critical";

export interface SimEvent {
  simTime: number;
  level: EventLevel;
  message: string;
  satId?: string; // "SAT-n" the event is about, when the backend knows it
  from?: string; // STATE events: raw mission states
  to?: string;
  label?: string; // STATE events: plain sentence, e.g. "Planning recovery"
  fn?: string; // FUNCTION_HANDOFF: the leader function that moved
  fromSats?: string[]; // FUNCTION_HANDOFF holders before / after (lists: one per group)
  toSats?: string[];
  link?: string[]; // LINK_LOCKED / LINK_LOST pair
  reason?: string; // LINK_LOST: partner_down | budget | sun | replan
  cause?: string; // FAILURE_DETECTED{cause: "isolated"} = cut off, not failed
}

export interface RoleHandoff {
  role: string;
  from_sat: string;
  to_sat: string;
}

export interface RunSummary {
  coverageMeanLastOrbit: number | null;
  simTime: number | null;
  scenario: string | null;
}

export interface RoleReassignment {
  simTime: number;
  assignments: Array<{
    satelliteId: string;
    newRole: string | null;
    targetSlot: string | null;
  }>;
  costTotal?: number; // present only when the log carried cost_total — never invented
}

export type WireMessage =
  | SimStateMessage
  | EventMessage
  | RoleReassignmentMessage
  | { type: string; [key: string]: unknown };

export interface SimStateMessage {
  type: "sim_state";
  sim_time: number;
  state: string;
  scenario: string | null;
  seed: number | null;
  sats: Array<{
    id: string;
    role: string;
    status: string;
    r: [number, number, number];
    v: [number, number, number];
    dv_used: number;
    target_slot?: string;
    failure_type?: string;
    risk?: number;
  }>;
  coverage: number | null;
  min_sep: number | null;
  metrics: {
    coverage?: number;
    coverage_avg?: number;
    formation_deviation?: number;
    min_sep?: number;
    detection_latency_s?: number;
    replanning_latency_ms?: number;
  };
}

export interface EventMessage {
  type: "event";
  sim_time: number;
  level: string;
  message: string;
}

/** Shape the backend actually sends (cubesat/wire.py): no old_role/per-sat
 * cost — the log does not carry them, and the UI must not invent them. */
export interface RoleReassignmentMessage {
  type: "role_reassignment";
  sim_time: number;
  assignments: Array<{
    satellite_id: string;
    new_role: string | null;
    target_slot: string | null;
  }>;
  cost_total?: number;
  method?: string; // hungarian | greedy | do_no_harm_hold | even_split ...
  kept_formation?: boolean; // true = held the current slots, nobody moved
  transfer_lower_bound_s?: number;
  role_handoffs?: RoleHandoff[];
}
