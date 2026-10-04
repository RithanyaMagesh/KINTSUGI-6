// Recovery log — the step-by-step answer to "HOW did it recover — what did
// the system do" (user demand, asked twice). One numbered, timestamped chain
// per failure episode: failure event -> declared dead -> replan -> propellant
// burned -> recovered. EVERY step is measured: episodes derive from
// recoveryStore (fed by the ONE shared deserializer, src/api/deserializer.ts
// §18/§21.9), propellant deltas from the chart history's streamed dv_used
// samples (historyStore), coverage from the same stream. A piece the wire
// does not carry renders as a SKIPPED step, never a guess (repo invariant 1).
//
// recoveryStore selectors consumed as-is: failures / assignments / phases.
// It tracks no dv history, so the burn step reads historyStore.samples — a
// derivation this component owns; recoveryStore.ts itself is not modified.
//
// Bare section: the host supplies panel chrome (no card inside a card,
// §13.3). Embeddable on the replay page AND the live page's Recovery tab.
import type { ReactNode } from "react";
import { useSimStore } from "../../stores/simStore";
import { useRecoveryStore } from "../../stores/recoveryStore";
import type {
  AssignmentEvent,
  FailureRecord,
  RecoveryPhase,
} from "../../stores/recoveryStore";
import { useHistoryStore, type ChartSample } from "../../stores/historyStore";
import { formatPercent, formatSimTime } from "../../utils/format";
import styles from "./RecoveryLog.module.css";

/** The recovery mode the UI names. The log's ASSIGNMENT payload carries
 * method: "hungarian" (data/logs/two_failure.jsonl t=1208), but cubesat/wire.py
 * _role_reassignment (wire.py:180-200) forwards only assignments + cost_total
 * to /ws/state — no policy field exists on the wire, so the spec's fallback
 * literal is what shows. Never invent a wire field to "improve" this. */
const RECOVERY_MODE = "Hungarian (default)";

/** m/s — below any measured burn (dead satellites coast, invariant 5). */
const DV_EPSILON = 1e-9;

interface Step {
  time: number | null; // sim time stamp [s]; null = no measured instant
  body: ReactNode;
  muted?: boolean; // context line (in-progress / superseded), not an action
}

interface Episode {
  failure: FailureRecord;
  next: FailureRecord | null;
  assignment: AssignmentEvent | null; // first replan issued inside the episode
  reconfig: { t0: number; t1: number } | null; // this episode's RECONFIGURING window
  recoveredAt: number | null; // RECOVERED phase start inside the episode
}

/** Rewind (replay seek backwards) re-delivers frames and recoveryStore's
 * append paths do not dedupe (assignments push unconditionally, failures
 * re-create after failedSeen clears) — this component's own fold collapses
 * those repeats instead of modifying the store. Keyed on measured identity:
 * failure = satId@tFail, assignment = its sim time. */
function dedupeEpisodes(
  failures: FailureRecord[],
  assignments: AssignmentEvent[],
  phases: RecoveryPhase[],
  simTime: number | null,
): Episode[] {
  const seenFailures = new Set<string>();
  const seenAssignments = new Set<number>();
  const cleanFailures: FailureRecord[] = [];
  for (const f of failures) {
    const key = `${f.satId}@${f.tFail}`;
    if (seenFailures.has(key)) continue;
    seenFailures.add(key);
    cleanFailures.push(f);
  }
  // Chronological episodes: the store appends in stream order, but a replay
  // rewind can deliver an older failure after a newer one (stable sort,
  // ES2019+). Episodes and their windows are time-ordered by definition.
  cleanFailures.sort((a, b) => a.tFail - b.tFail);
  const cleanAssignments: AssignmentEvent[] = [];
  for (const a of assignments) {
    if (seenAssignments.has(a.time)) continue;
    seenAssignments.add(a.time);
    cleanAssignments.push(a);
  }
  const episodes: Episode[] = [];
  for (let i = 0; i < cleanFailures.length; i++) {
    const failure = cleanFailures[i];
    const next = i + 1 < cleanFailures.length ? cleanFailures[i + 1] : null;
    const upper = next !== null ? next.tFail : Number.POSITIVE_INFINITY;
    const assignment =
      cleanAssignments.find((a) => a.time >= failure.tFail && a.time < upper) ?? null;
    const reconfigPhase =
      phases.find(
        (p) =>
          p.state === "RECONFIGURING" &&
          p.tStart > failure.tFail &&
          p.tStart < upper,
      ) ?? null;
    const reconfig =
      reconfigPhase !== null
        ? { t0: reconfigPhase.tStart, t1: reconfigPhase.tEnd ?? simTime ?? reconfigPhase.tStart }
        : null;
    // Dead satellites never un-fail on the wire (invariant 5), so mission
    // recovery is the swarm-level RECOVERED phase — the same measured signal
    // roleHistoryStore uses for its "recovered" entries.
    const recoveredPhase =
      phases.find(
        (p) => p.state === "RECOVERED" && p.tStart > failure.tFail && p.tStart < upper,
      ) ?? null;
    episodes.push({
      failure,
      next,
      assignment,
      reconfig,
      recoveredAt: recoveredPhase !== null ? recoveredPhase.tStart : null,
    });
  }
  return episodes;
}

/** Per-satellite dv_used delta across [t0, t1], from the chart sampler's
 * streamed snapshots (historyStore samples carry every satellite's cumulative
 * dv_used). Endpoints are the samples nearest the window bounds BY SIM TIME,
 * so after a rewind the re-measured frames pair with themselves: dv_used is a
 * deterministic function of sim t in a log (invariant 2). Sats absent from a
 * bound, or deltas under epsilon, are not burns — no row, no guess. */
function dvDeltas(
  samples: ChartSample[],
  t0: number,
  t1: number,
): Array<{ satId: string; delta: number }> {
  let first: ChartSample | null = null;
  let last: ChartSample | null = null;
  for (const s of samples) {
    if (s.t < t0 || s.t > t1) continue;
    if (first === null || s.t < first.t) first = s;
    if (last === null || s.t > last.t) last = s;
  }
  if (first === null || last === null) return [];
  const out: Array<{ satId: string; delta: number }> = [];
  for (const satId of Object.keys(last.dv)) {
    const before = first.dv[satId];
    if (before === undefined) continue;
    const delta = last.dv[satId] - before;
    if (Number.isFinite(delta) && delta > DV_EPSILON) out.push({ satId, delta });
  }
  return out.sort((a, b) => a.satId.localeCompare(b.satId, undefined, { numeric: true }));
}

/** Last measured coverage at or before t (for the recovery step: coverage AT
 * recovery, not the running "current" that keeps drifting after it). */
function coverageAt(samples: ChartSample[], t: number): number | null {
  for (let i = samples.length - 1; i >= 0; i--) {
    const s = samples[i];
    if (s.t <= t && s.coverage !== null) return s.coverage;
  }
  return null;
}

/** The episode's action chain — every clause backed by a measured value. */
function stepsFor(
  ep: Episode,
  isLatest: boolean,
  samples: ChartSample[],
  missionState: string | null,
): Step[] {
  const f = ep.failure;
  const steps: Step[] = [];

  // (a) The failure event, in the wire's own words (cubesat/wire.py:176:
  // f"{who} {mode} failure detected"). The event fires at t_detect; when the
  // measured detection latency is known the step stamps that instant,
  // otherwise the first frame that observed the failure.
  const detectedAt = f.detectionLatencyS !== null ? f.tFail + f.detectionLatencyS : f.tFail;
  steps.push({
    time: detectedAt,
    body: (
      <>
        <span className={styles.mono}>{f.satId}</span>{" "}
        {f.mode !== null && (
          <>
            <span className={styles.mono}>{f.mode}</span>{" "}
          </>
        )}
        failure detected
      </>
    ),
  });

  // (b) Declared dead — only when metrics.detection_latency_s reached the
  // store (wire.py:169-172 computes it from the event payload). Skipped
  // otherwise, never estimated.
  if (f.detectionLatencyS !== null) {
    steps.push({
      time: null,
      body: (
        <>
          Declared <span className={styles.mono}>{f.mode ?? "failed"}</span> after{" "}
          <span className={styles.mono}>{f.detectionLatencyS.toFixed(1)} s</span>
        </>
      ),
    });
  }

  // (c) The replan. The wire's role_reassignment covers EVERY survivor
  // (cubesat/wire.py _role_reassignment), so only rows whose pre-assignment
  // slot (recoveryStore's measured diff) differs from the target are moves;
  // a row "takes over" when its target is the failed satellite's last
  // measured slot. No provable mover (e.g. the run's first ASSIGNMENT: the
  // wire carries target_slot only after the first assignment_map fill) says
  // exactly that instead of inventing movements. cost_total only when sent.
  if (ep.assignment !== null) {
    const a = ep.assignment;
    const movers = a.rows.filter(
      (r) => r.prevSlot !== null && r.targetSlot !== null && r.prevSlot !== r.targetSlot,
    );
    const parts: ReactNode[] = [];
    if (movers.length > 0) {
      movers.forEach((m, i) => {
        parts.push(
          <span key={`mover-${m.satelliteId}`} className={styles.mono}>
            {m.satelliteId} {m.prevSlot} {"->"} {m.targetSlot}
          </span>,
        );
        if (f.vacatedSlot !== null && m.targetSlot === f.vacatedSlot) {
          parts.push(
            <span key={`takeover-${m.satelliteId}`}>
              {" "}
              (takes over from <span className={styles.mono}>{f.satId}</span>)
            </span>,
          );
        }
        if (i < movers.length - 1) parts.push(", ");
      });
    } else {
      parts.push(
        <span key="nomovers">
          {a.rows.length} survivor slots assigned; no slot change provable from the wire yet
        </span>,
      );
    }
    if (a.costTotal !== null) {
      parts.push(
        <span key="cost">
          ; assignment cost <span className={styles.mono}>{a.costTotal.toFixed(2)}</span>
        </span>,
      );
    }
    steps.push({
      time: a.time,
      body: (
        <>
          Replan via {RECOVERY_MODE}: {parts}
        </>
      ),
    });
  }

  // (d) Propellant burned across this episode's reconfiguration window
  // (measured dv_used deltas). No samples in the window (e.g. the console
  // joined after it) or no measured burn: the step is skipped entirely.
  if (ep.reconfig !== null) {
    const deltas = dvDeltas(samples, ep.reconfig.t0, ep.reconfig.t1);
    if (deltas.length > 0) {
      steps.push({
        time: ep.reconfig.t0,
        body: (
          <>
            Propellant burned across reconfiguration (
            <span className={styles.mono}>
              {ep.reconfig.t0.toFixed(1)} s to {ep.reconfig.t1.toFixed(1)} s
            </span>
            ):
            <span className={styles.burnList}>
              {deltas.map((d) => (
                <span key={d.satId} className={styles.burn}>
                  {d.satId} +{d.delta.toFixed(2)} m/s
                </span>
              ))}
            </span>
          </>
        ),
      });
    }
  }

  // (e) Recovery. The ask's own wording for the settled-within-band
  // transition; coverage at recovery (measured at the RECOVERED stamp)
  // against the last measured coverage before the failure. An episode still
  // open says so; one interrupted by the next failure says by whom.
  if (ep.recoveredAt !== null) {
    const atRecovery = coverageAt(samples, ep.recoveredAt) ?? f.coverage.current;
    steps.push({
      time: ep.recoveredAt,
      body: (
        <>
          Formation error back within band; <span className={styles.mono}>RECOVERED</span>.
          {atRecovery !== null && f.coverage.pre !== null && (
            <>
              {" "}
              Coverage <span className={styles.mono}>{formatPercent(atRecovery)}</span> vs{" "}
              <span className={styles.mono}>{formatPercent(f.coverage.pre)}</span> before the
              failure.
            </>
          )}
        </>
      ),
    });
  } else if (isLatest) {
    steps.push({
      time: null,
      muted: true,
      body:
        missionState !== null ? (
          <>
            Recovery in progress — mission state{" "}
            <span className={styles.mono}>{missionState}</span>
          </>
        ) : (
          <>Recovery in progress</>
        ),
    });
  } else if (ep.next !== null) {
    steps.push({
      time: null,
      muted: true,
      body: (
        <>
          Superseded by the <span className={styles.mono}>{ep.next.satId}</span> failure at{" "}
          <span className={styles.mono}>{formatSimTime(ep.next.tFail)}</span>
        </>
      ),
    });
  }
  return steps;
}

export default function RecoveryLog() {
  const failures = useRecoveryStore((s) => s.failures);
  const assignments = useRecoveryStore((s) => s.assignments);
  const phases = useRecoveryStore((s) => s.phases);
  const simTime = useSimStore((s) => s.simTime);
  const missionState = useSimStore((s) => s.missionState);
  const samples = useHistoryStore((s) => s.samples);

  const episodes = dedupeEpisodes(failures, assignments, phases, simTime);

  return (
    <section className={styles.log} aria-label="Recovery log">
      <div className={styles.header}>
        <h3 className={styles.title}>Recovery log</h3>
        <span className={styles.policy}>Recovery policy: {RECOVERY_MODE}</span>
      </div>
      {episodes.length === 0 ? (
        <p className={styles.empty}>
          No failure episodes yet. The log fills in as the mission detects failures, replans
          and recovers.
        </p>
      ) : (
        <ol className={styles.episodes}>
          {episodes.map((ep, i) => {
            const isLatest = i === episodes.length - 1;
            const outcomeClass =
              ep.recoveredAt !== null
                ? styles.episodeRecovered
                : isLatest
                  ? styles.episodeActive
                  : styles.episodeSuperseded;
            return (
              <li
                key={`${ep.failure.satId}-${ep.failure.tFail}`}
                className={`${styles.episode} ${outcomeClass}`}
              >
                <h4 className={styles.episodeTitle}>
                  Episode {i + 1}: <span className={styles.mono}>{ep.failure.satId}</span>
                  {ep.failure.mode !== null && (
                    <>
                      {" "}(<span className={styles.mono}>{ep.failure.mode}</span>)
                    </>
                  )}
                </h4>
                <ol className={styles.steps}>
                  {stepsFor(ep, isLatest, samples, missionState).map((s, j) => (
                    <li key={j} className={s.muted === true ? styles.stepMuted : styles.step}>
                      <span className={styles.stepTime}>
                        {s.time !== null ? formatSimTime(s.time) : ""}
                      </span>
                      <span className={styles.stepBody}>{s.body}</span>
                    </li>
                  ))}
                </ol>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export { RecoveryLog };
