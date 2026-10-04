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
import type { SimEvent, EventLevel } from "../types/events";
import type { SimFrame, SimMode } from "../types/telemetry";

export type Deserialized =
  | { kind: "frame"; frame: SimFrame }
  | { kind: "event"; event: SimEvent }
  | { kind: "reassignment"; reassignment: RoleReassignmentMessage }
  | {
      kind: "hello";
      mode: SimMode;
      scenario: string | null;
      seed: number | null;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
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
  };
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
  return {
    simTime: typeof msg.sim_time === "number" ? msg.sim_time : 0,
    missionState: typeof msg.state === "string" ? msg.state : "NOMINAL",
    scenario: typeof msg.scenario === "string" ? msg.scenario : null,
    seed: typeof msg.seed === "number" ? msg.seed : null,
    satellites: (msg.sats ?? [])
      .map((s) => toSatellite(s))
      .filter((s): s is Satellite => s !== null),
    coverage: metrics.coverage ?? null,
    minSep: metrics.minSep ?? null,
    metrics,
  };
}

const LEVELS: EventLevel[] = ["info", "warning", "critical"];

function toEvent(msg: EventMessage): SimEvent | null {
  if (typeof msg.message !== "string") return null;
  const level = LEVELS.includes(msg.level as EventLevel) ? (msg.level as EventLevel) : "info";
  return {
    simTime: typeof msg.sim_time === "number" ? msg.sim_time : 0,
    level,
    message: msg.message,
  };
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
      return { kind: "frame", frame };
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
    case "hello": {
      const mode = raw.mode === "live" || raw.mode === "replay" ? raw.mode : "stopped";
      return {
        kind: "hello",
        mode: mode as SimMode,
        scenario: typeof raw.scenario === "string" ? raw.scenario : null,
        seed: typeof raw.seed === "number" ? raw.seed : null,
      };
    }
    default:
      return null; // pong and anything else carry no UI state
  }
}
