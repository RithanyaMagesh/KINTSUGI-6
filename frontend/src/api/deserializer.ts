// Shared wire deserializer — FRONTEND_SPEC §18 + §21.9.
// ONE parser serves the live /ws/state stream AND replay: the G5 backend
// drives replay through the same socket (cubesat/session.py load_replay ->
// Hub -> /ws/state), so both paths parse identical bytes through this module
// and schema drift is impossible by construction. §18: defensive per-message
// parse — a malformed message is dropped, never thrown; the console keeps its
// last good state (§20). Message shapes mirror cubesat/wire.py exactly:
// hello / sim_state / event / role_reassignment / pong.

import type {
  EventMessage,
  RoleReassignmentMessage,
  SimStateMessage,
} from "../types/events";
import type { Satellite } from "../types/satellite";
import type { SimEvent, EventLevel, RunSummary } from "../types/events";
import type { Link, SimFrame, SimMode } from "../types/telemetry";

export type Deserialized =
  | { kind: "frame"; frame: SimFrame }
  | { kind: "event"; event: SimEvent }
  | { kind: "reassignment"; reassignment: RoleReassignmentMessage }
  | { kind: "summary"; summary: RunSummary }
  | {
      kind: "hello";
      mode: SimMode;
      scenario: string | null;
      seed: number | null;
      /** Recovery policy the session reports (additive `policy` field). null
       * while the backend predates the field — never guessed (invariant 1). */
      policy: string | null;
      /** Scenario keep-out floor [m]; null = unknown (replay / stopped). */
      minSepM: number | null;
      /** v2 live hellos: cartwheel | pco | gco | helix | string; null = unknown. */
      formationShape: string | null;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Additive wire field: the session's recovery policy (hello and sim_state
 * both carry it once the backend grows it; cubesat/session.py). Read off the
 * raw record — SimStateMessage in types/events.ts predates the field. Empty
 * or missing -> null; the UI renders "unmeasured", never a guessed default
 * (repo invariant 1). */
function readPolicy(raw: Record<string, unknown>): string | null {
  return typeof raw.policy === "string" && raw.policy.length > 0 ? raw.policy : null;
}

function toVec3(raw: unknown): [number, number, number] | null {
  if (!Array.isArray(raw) || raw.length !== 3) return null;
  const x = Number(raw[0]);
  const y = Number(raw[1]);
  const z = Number(raw[2]);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
  return [x, y, z];
}

/** One wire sat -> Satellite. Returns null for rows the log cannot support
 * (missing id / r / v / dv_used) — dropped, never defaulted into fake data
 * (invariant 1: dv_used=0 would fabricate "no fuel spent"). */
export function toSatellite(raw: unknown): Satellite | null {
  if (!isRecord(raw) || typeof raw.id !== "string") return null;
  const r = toVec3(raw.r);
  const v = toVec3(raw.v);
  if (r === null || v === null) return null;
  if (typeof raw.dv_used !== "number" || !Number.isFinite(raw.dv_used)) return null;
  const status =
    typeof raw.status === "string" && raw.status.length > 0 ? raw.status : "inactive";
  return {
    id: raw.id,
    role: typeof raw.role === "string" ? raw.role : "unknown",
    status: status as Satellite["status"],
    r,
    v,
    dv_used: raw.dv_used,
    targetSlot: typeof raw.target_slot === "string" ? raw.target_slot : undefined,
    failureType: typeof raw.failure_type === "string" ? raw.failure_type : undefined,
    risk: typeof raw.risk === "number" ? raw.risk : undefined,
    roles: Array.isArray(raw.roles) ? raw.roles.filter((x): x is string => typeof x === "string") : undefined,
    originalRole: str(raw.original_role),
    oldRole: str(raw.old_role),
    fuelKg: num(raw.fuel_kg),
    fuelMpsLeft: num(raw.fuel_mps_left),
    thrust: num(raw.k),
    payloadOk: bool(raw.payload_ok),
    radioOk: bool(raw.radio_ok),
    stuck: bool(raw.stuck),
    functions: strs(raw.functions),
  };
}

function strs(x: unknown): string[] | undefined {
  return Array.isArray(x) ? x.filter((v): v is string => typeof v === "string") : undefined;
}

const LINK_STATES = ["LOCKED", "ACQUIRING", "DOWN"] as const;
function toLink(x: unknown): Link | null {
  if (!Array.isArray(x) || typeof x[0] !== "string" || typeof x[1] !== "string") return null;
  const state = LINK_STATES.find((s) => s === x[2]);
  if (state === undefined) return null;
  return { a: x[0], b: x[1], state, rangeM: num(x[3]) ?? null, rateBps: num(x[4]) ?? null };
}

/** Alive sats outside the biggest talking group are "cut off" (the swarm can't
 * hear them); when every group is a single sat, all of them are. A sat that is
 * heard again gets no event, so this is read from `components` each frame. */
function markCutOff(sats: Satellite[], comps: string[][] | undefined): Satellite[] {
  if (comps === undefined || comps.length < 2) return sats;
  const biggest = Math.max(...comps.map((c) => c.length));
  const lonely = new Set(comps.filter((c) => c.length < biggest || biggest === 1).flat());
  return sats.map((s) => (s.status !== "failed" && lonely.has(s.id) ? { ...s, cutOff: true } : s));
}

function num(x: unknown): number | undefined {
  return typeof x === "number" && Number.isFinite(x) ? x : undefined;
}
function str(x: unknown): string | undefined {
  return typeof x === "string" && x.length > 0 ? x : undefined;
}
function bool(x: unknown): boolean | undefined {
  return typeof x === "boolean" ? x : undefined;
}

/** sim_state -> SimFrame (the §15.1 frame shape). INIT maps to the empty
 * state upstream (cubesat/wire.py to_sim_state), so sats: [] here simply
 * means "no data yet" and the UI renders its §20.3 / §24.3 states. */
export function toSimFrame(msg: SimStateMessage): SimFrame {
  const metrics: Partial<SimFrame["metrics"]> = {};
  if (typeof msg.coverage === "number" && Number.isFinite(msg.coverage)) {
    metrics.coverage = msg.coverage;
  }
  if (typeof msg.min_sep === "number" && Number.isFinite(msg.min_sep)) {
    metrics.minSep = msg.min_sep;
  }
  const m = isRecord(msg.metrics) ? msg.metrics : {};
  if (typeof m.detection_latency_s === "number") {
    metrics.detectionLatencyS = m.detection_latency_s;
  }
  if (typeof m.replanning_latency_ms === "number") {
    metrics.replanningLatencyMs = m.replanning_latency_ms;
  }
  const raw = msg as unknown as Record<string, unknown>;
  const components = Array.isArray(raw.components)
    ? raw.components.map(strs).filter((c): c is string[] => c !== undefined)
    : undefined;
  const sats = (msg.sats ?? []).map((s) => toSatellite(s)).filter((s): s is Satellite => s !== null);
  return {
    links: Array.isArray(raw.links) ? raw.links.map(toLink).filter((l): l is Link => l !== null) : undefined,
    components,
    splitBrain: strs(raw.split_brain),
    functionsVacant: strs(raw.functions_vacant),
    consensusRounds: num(raw.consensus_rounds),
    simTime: typeof msg.sim_time === "number" ? msg.sim_time : 0,
    missionState: typeof msg.state === "string" ? msg.state : "NOMINAL",
    scenario: typeof msg.scenario === "string" ? msg.scenario : null,
    seed: typeof msg.seed === "number" ? msg.seed : null,
    satellites: markCutOff(sats, components),
    coverage: metrics.coverage ?? null,
    minSep: metrics.minSep ?? null,
    metrics,
  };
}

const LEVELS: EventLevel[] = ["info", "warning", "critical"];

function toEvent(msg: EventMessage): SimEvent | null {
  if (typeof msg.message !== "string") return null;
  const level = LEVELS.includes(msg.level as EventLevel) ? (msg.level as EventLevel) : "info";
  const raw = msg as unknown as Record<string, unknown>;
  const ev: SimEvent = {
    simTime: typeof msg.sim_time === "number" ? msg.sim_time : 0,
    level,
    message: msg.message,
  };
  for (const [k, w] of [["satId", "sat_id"], ["from", "from"], ["to", "to"], ["label", "label"]] as const) {
    const v = str(raw[w]);
    if (v !== undefined) ev[k] = v;
  }
  // Track C extras: FUNCTION_HANDOFF carries holder LISTS in from/to.
  const fn = str(raw.function);
  if (fn !== undefined) {
    ev.fn = fn;
    ev.fromSats = strs(raw.from) ?? [];
    ev.toSats = strs(raw.to) ?? [];
  }
  const link = strs(raw.link);
  if (link !== undefined) ev.link = link;
  const reason = str(raw.reason);
  if (reason !== undefined) ev.reason = reason;
  const cause = str(raw.cause);
  if (cause !== undefined) ev.cause = cause;
  return ev;
}

/** Parse one raw wire message. Returns null for anything that is not one of
 * the shapes cubesat/wire.py emits — unknown types are ignored (§6.3). */
export function deserializeMessage(raw: unknown): Deserialized | null {
  if (!isRecord(raw) || typeof raw.type !== "string") return null;
  switch (raw.type) {
    case "sim_state": {
      if (
        typeof raw.sim_time !== "number" ||
        typeof raw.state !== "string" ||
        !Array.isArray(raw.sats)
      ) {
        return null; // malformed sim_state: dropped, last good state kept (§18)
      }
      const frame = toSimFrame(raw as unknown as SimStateMessage);
      // policy is read off the raw record (see readPolicy) and attached here —
      // SimFrame.policy is optional, so no other frame constructor breaks.
      return { kind: "frame", frame: { ...frame, policy: readPolicy(raw) } };
    }
    case "event": {
      const event = toEvent(raw as unknown as EventMessage);
      return event === null ? null : { kind: "event", event };
    }
    case "role_reassignment": {
      const r = raw as unknown as RoleReassignmentMessage;
      if (!Array.isArray(r.assignments)) return null;
      return { kind: "reassignment", reassignment: r };
    }
    case "run_summary":
      return {
        kind: "summary",
        summary: {
          coverageMeanLastOrbit: num(raw.coverage_mean_last_orbit) ?? null,
          simTime: num(raw.sim_time) ?? null,
          scenario: str(raw.scenario) ?? null,
        },
      };
    case "hello": {
      const mode = raw.mode === "live" || raw.mode === "replay" ? raw.mode : "stopped";
      return {
        kind: "hello",
        mode: mode as SimMode,
        scenario: typeof raw.scenario === "string" ? raw.scenario : null,
        seed: typeof raw.seed === "number" ? raw.seed : null,
        policy: readPolicy(raw),
        minSepM: typeof raw.min_sep_m === "number" ? raw.min_sep_m : null,
        formationShape: str(raw.formation_shape) ?? null,
      };
    }
    default:
      return null; // pong and anything else carry no UI state
  }
}
