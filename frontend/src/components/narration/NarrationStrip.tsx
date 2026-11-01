// NarrationStrip — ONE plain-language sentence about NOW (user demand:
// "we are doing what, how we are recovering — nothing is explainable").
// Derived ONLY from recoveryStore + simStore (both fed by the ONE shared
// deserializer). Zero invention: a clause whose value is missing on the wire
// is dropped, never guessed. Severity-colored left border; 16px sans,
// numbers tabular.
import type { ReactNode } from "react";
import { useSimStore } from "../../stores/simStore";
import {
  useRecoveryStore,
  selectLatestFailure,
  selectLatestAssignment,
  selectDegradedSats,
  selectDegradedInfo,
} from "../../stores/recoveryStore";
import type { FailureRecord, AssignmentEvent } from "../../stores/recoveryStore";
import type { MissionState, Satellite } from "../../types/satellite";
import { missionStateColor } from "../../utils/colors";
import { formatSeconds } from "../../utils/format";
import { WHY_LINE, slotLabel } from "../recovery/RecoveryLog";
import { faultLabel, functionLabel, satLabel, stateLabel } from "../live/hudFormat";
import type { SimEvent } from "../../types/events";
import type { Handoff } from "../../stores/simStore";
import styles from "./NarrationStrip.module.css";

function Mono({ children }: { children: ReactNode }) {
  return <span className={styles.num}>{children}</span>;
}

function Pct({ value }: { value: number }) {
  return <Mono>{(value * 100).toFixed(0)}%</Mono>;
}

function activeCount(satellites: Satellite[]): number {
  let n = 0;
  for (const sat of satellites) {
    if (sat.status !== "failed" && sat.status !== "inactive") n += 1;
  }
  return n;
}

/** Rows that actually change slot, measured: the wire's role_reassignment
 * covers EVERY survivor (cubesat/wire.py _role_reassignment builds one row per
 * assignment entry), so most rows re-state a satellite's existing slot. A row
 * is a mover only when its pre-assignment slot (the previous frame's, captured
 * by recoveryStore) differs from the target — movement is never claimed from a
 * row alone (repo invariant 1). */
function moversOf(assignment: AssignmentEvent | null) {
  const rows = assignment?.rows ?? [];
  return {
    rows,
    movers: rows.filter(
      (r) => r.prevSlot !== null && r.targetSlot !== null && r.prevSlot !== r.targetSlot,
    ),
  };
}

/** Track C inputs (laser runs): talking groups, split-brain, recent handoffs. */
interface CommsView {
  simTime: number | null;
  components: string[][];
  splitBrain: string[];
  events: SimEvent[];
  handoffs: Handoff[];
}

const RECENT_S = 10; // sim seconds a handoff sentence stays up

/** Laser-run sentences, highest priority first; null when none applies. */
function commsSentence(satellites: Satellite[], c: CommsView): string | null {
  const live = satellites.filter((s) => s.status !== "failed");
  if (live.length > 0 && live.every((s) => s.cutOff === true)) {
    return "Every satellite is cut off: no laser link reaches anyone.";
  }
  if (c.components.length > 1) {
    const groups = c.components.map((g) => g.join(", ")).join(" | ");
    let text = `Swarm split into ${c.components.length} groups: ${groups}.`;
    if (c.splitBrain.length > 0) {
      const names = c.splitBrain.map((f) => functionLabel(f).toLowerCase()).join(", ");
      text += ` Split-brain: ${names} ${c.splitBrain.length === 1 ? "has" : "have"} two holders.`;
    }
    return text;
  }
  if (c.simTime === null) return null;
  const since = c.simTime - RECENT_S;
  // Decentral: the latest burst of consensus-auction handoffs (one per function).
  const fnEvents = c.events.filter((e) => e.fn !== undefined && e.simTime >= since);
  if (fnEvents.length > 0) {
    const burstT = fnEvents[fnEvents.length - 1].simTime;
    const latest = new Map<string, SimEvent>();
    for (const e of fnEvents) if (e.simTime === burstT) latest.set(e.fn!, e);
    const parts = [...latest.values()].map((e) => {
      const to = e.toSats ?? [];
      const name = functionLabel(e.fn!).toLowerCase();
      if (to.length === 0) return `${name} vacant`;
      return `${name} to ${to.join(" and ")}`;
    });
    const dead = c.events.find(
      (e) => e.level === "critical" && e.satId !== undefined && e.cause !== "isolated" && e.simTime >= since && e.simTime <= burstT,
    );
    const n = latest.size;
    return (
      `Consensus auction: ${n} leader function${n === 1 ? "" : "s"} moved` +
      (dead !== undefined ? ` after ${dead.satId} failed` : "") +
      `: ${parts.join(", ")}.`
    );
  }
  // Central: the leader role moved to another satellite.
  const lead = [...c.handoffs].reverse().find((h) => h.role === "leader" && h.t >= since);
  if (lead !== undefined) return `Leader role moved from ${lead.from} to ${lead.to}.`;
  return null;
}

/** The story so far as clauses — every clause backed by a measured value. */
function narrationFor(
  missionState: MissionState,
  satellites: Satellite[],
  coverage: number | null,
  failure: FailureRecord | null,
  assignment: AssignmentEvent | null,
  degradedSats: string[] = [],
  degradedInfo: Record<string, { tDegraded: number; degrade_s?: number }> = {},
  comms: CommsView | null = null,
): ReactNode {
  const coverageNow = coverage ?? failure?.coverage.current ?? null;
  const { rows, movers } = moversOf(assignment);

  // Laser runs (Track C): a split swarm or a handoff burst outranks the rest.
  const commsText = comms === null ? null : commsSentence(satellites, comms);
  if (commsText !== null) return commsText;

  const degradedSat = satellites.find((s) => s.status === "degraded");
  const degradedId = degradedSat?.id ?? (degradedSats.length > 0 ? degradedSats[0] : null);
  if (degradedSat?.fuelMpsLeft !== undefined && (missionState === "NOMINAL" || missionState === "DEGRADED")) {
    // v2: degraded has several causes; name the one this satellite has
    return <>{degradedSat.id}: {satLabel(degradedSat).toLowerCase()}.</>;
  }
  if (degradedId && (missionState === "NOMINAL" || missionState === "DEGRADED")) {
    const dId = degradedId.startsWith("SAT-") ? degradedId : `SAT-${degradedId}`;
    const fadeS = degradedInfo[degradedId]?.degrade_s;
    return (
      <>
        {dId} power is fading
        {fadeS !== undefined && (
          <>
            {" "}over <Mono>{fadeS} s</Mono>
          </>
        )}
        .
      </>
    );
  }

  if (assignment?.keptFormation === true && (missionState === "REPLANNING" || missionState === "RECONFIGURING")) {
    return "Kept formation, no move: every survivor holds its slot.";
  }

  switch (missionState) {
    case "NOMINAL": {
      if (satellites.length === 0) return "Nominal. Waiting for the first telemetry frame.";
      return (
        <>
          Nominal: <Mono>{activeCount(satellites)} of {satellites.length}</Mono> satellites
          active
          {coverageNow !== null && (
            <>
              , coverage <Pct value={coverageNow} />
            </>
          )}
          .
        </>
      );
    }
    case "FAILURE_DETECTED": {
      if (failure === null) return "Failure detected.";
      return (
        <>
          Failure detected: {failure.satId}
          {failure.mode !== null && <> ({faultLabel(failure.mode).toLowerCase()})</>}
          {failure.detectionLatencyS !== null && (
            <>
              , detected <Mono>{formatSeconds(failure.detectionLatencyS)}</Mono> after onset
            </>
          )}
          {coverageNow !== null && (
            <>
              , coverage <Pct value={coverageNow} />
            </>
          )}
          .
        </>
      );
    }
    case "REPLANNING": {
      return (
        <>
          {stateLabel(missionState)}
          {failure !== null && <>: reassigning roles after the {failure.satId} failure</>}
          {movers.length > 0 && (
            <>
              ; <Mono>{movers.length}</Mono> of <Mono>{rows.length}</Mono> slots reassigned
            </>
          )}
          .
        </>
      );
    }
    case "RECONFIGURING": {
      // Name a satellite that is MEASURED to move (prevSlot != target), never
      // rows[0]: the assignment payload lists every survivor, unchanged rows
      // included (measured on data/logs/two_failure.jsonl t=1508: SAT-5 is the
      // only mover of four rows). With no provable mover — the run's first
      // ASSIGNMENT has no earlier slot on the wire (wire.py emits target_slot
      // only after the first assignment_map fill) — no movement is claimed.
      const first = movers[0] ?? null;
      const allKeepers =
        rows.length > 0 &&
        rows.every((r) => r.prevSlot !== null && r.prevSlot === r.targetSlot);
      const vacatedByFailure =
        failure !== null &&
        failure.vacatedSlot !== null &&
        movers.some((r) => r.targetSlot === failure.vacatedSlot);
      return (
        <>
          {stateLabel(missionState)}
          {first !== null ? (
            <>
              : {first.satelliteId} moving to {slotLabel(first.targetSlot ?? "")}
              {vacatedByFailure && <>, left empty by {failure.satId}</>}
              {movers.length > 1 && <> + {movers.length - 1} more</>}
            </>
          ) : allKeepers ? (
            ": survivors hold their slots"
          ) : rows.length > 0 ? (
            <>
              : the replan assigned <Mono>{rows.length}</Mono> survivor slots
            </>
          ) : (
            ": survivors moving to reassigned slots"
          )}
          {failure !== null &&
            failure.coverage.current !== null &&
            failure.coverage.pre !== null && (
              <>
                ; coverage <Pct value={failure.coverage.current} />, was{" "}
                <Pct value={failure.coverage.pre} /> before the failure
              </>
            )}
          .
        </>
      );
    }
    case "RECOVERED": {
      return (
        <>
          {stateLabel(missionState)}
          {failure !== null &&
            failure.coverage.current !== null &&
            failure.coverage.pre !== null && (
              <>
                : coverage <Pct value={failure.coverage.current} />, was{" "}
                <Pct value={failure.coverage.pre} /> before the {failure.satId} failure
              </>
            )}
          .
        </>
      );
    }
    case "DEGRADED": {
      if (satellites.length === 0) return "Degraded.";
      return (
        <>
          Degraded: <Mono>{activeCount(satellites)} of {satellites.length}</Mono> satellites
          active
          {coverageNow !== null && (
            <>
              , coverage <Pct value={coverageNow} />
            </>
          )}
          .
        </>
      );
    }
    default:
      return `${stateLabel(missionState)}.`;
  }
}

export default function NarrationStrip() {
  const missionState = useSimStore((s) => s.missionState);
  const satellites = useSimStore((s) => s.satellites);
  const metricsCoverage = useSimStore((s) => s.metrics.coverage);
  const failure = useRecoveryStore(selectLatestFailure);
  const assignment = useRecoveryStore(selectLatestAssignment);
  const degradedSats = useRecoveryStore(selectDegradedSats);
  const degradedInfo = useRecoveryStore(selectDegradedInfo);
  const simTime = useSimStore((s) => s.simTime);
  const components = useSimStore((s) => s.components);
  const splitBrain = useSimStore((s) => s.splitBrain);
  const events = useSimStore((s) => s.events);
  const handoffs = useSimStore((s) => s.handoffs);

  const { movers } = moversOf(assignment);
  const multiMovers =
    movers.length > 1 &&
    (missionState === "REPLANNING" || missionState === "RECONFIGURING");

  const isDegraded = satellites.some((s) => s.status === "degraded") || degradedSats.length > 0;
  const color =
    isDegraded && missionState === "NOMINAL"
      ? "var(--status-caution)"
      : missionStateColor(missionState);

  return (
    <section
      className={styles.strip}
      style={{ borderLeftColor: color }}
      aria-label="Recovery narration"
    >
      {missionState === null ? (
        <p className={styles.sentence} role="status" aria-live="polite">
          The recovery story starts when a simulation runs. Start one or load a replay.
        </p>
      ) : (
        <div role="status" aria-live="polite">
          <p className={styles.sentence}>
            {narrationFor(
              missionState,
              satellites,
              metricsCoverage ?? null,
              failure,
              assignment,
              degradedSats,
              degradedInfo,
              { simTime, components, splitBrain, events, handoffs },
            )}
          </p>
          {multiMovers && (
            <p
              className={styles.sentence}
              style={{ color: "var(--ink-muted)", marginTop: "var(--space-1)" }}
            >
              {WHY_LINE}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
