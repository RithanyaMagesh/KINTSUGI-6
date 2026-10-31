// FAQ: the questions a judge actually asks, answered with the project's own
// recorded numbers. Static Q/A rows, all answers visible at once. Technical
// terms are fine; file paths and spec numbers are not.
import PageShell from "../../pages/PageShell";
import styles from "./pages.module.css";

const QUESTIONS = [
  {
    q: "Is this a real satellite cluster?",
    a: (
      <>
        <p className={styles.p}>
          No. The swarm is hypothetical — it does not exist; only the chief&apos;s orbit is
          real. The six satellites fly formation on the measured orbit of FIREFLY-1 (Pixxel,
          NORAD 62701: altitude 589.309 km, eccentricity 3.72e-4), taken from a saved
          CelesTrak orbit snapshot.
        </p>
        <p className={`${styles.p} ${styles.muted}`}>
          The physics is the honest part: relative motion, failure detection, replanning and
          recovery are computed by the same engine that writes the committed logs — only the
          constellation itself is imagined.
        </p>
      </>
    ),
  },
  {
    q: "What happens when a satellite fails?",
    a: (
      <>
        <p className={styles.p}>
          Every satellite reports a heartbeat each tick. After 3 missed heartbeats (ticks are
          2 s, so 4 s for a tick-aligned failure) the swarm declares Failure detected, and
          the state machine moves on through Replanning and Moving to new slots to
          Recovered.
        </p>
        <p className={styles.p}>
          A dead satellite goes silent and coasts
          ballistically — it never freezes, and it keeps counting as a collision obstacle the
          replanner must respect. A satellite with its thruster out
          keeps reporting heartbeats but cannot maneuver — invisible to failure detection by
          design, shown as a failure annotation in the UI.
        </p>
      </>
    ),
  },
  {
    q: "How does the swarm decide who takes over?",
    a: (
      <>
        <p className={styles.p}>
          In two steps. First the survivors&apos; new formation is chosen: candidate slot sets
          are swept and one is picked that keeps minimum separation (with coasting dead
          satellites as obstacles) and stays inside the delta-v budget, maximizing coverage.
          Critical roles — leader, downlink — are re-elected first.
        </p>
        <p className={styles.p}>
          Then each survivor gets a slot by rectangular Hungarian assignment (rows are
          survivors, columns are candidate slots) on a cost matrix of distance, distance over remaining fuel, and
          role mismatch, with a tiny index-based epsilon breaking ties. Same input, same
          assignment — determinism is a tested invariant. A greedy nearest-slot fallback
          exists as a scenario toggle to show graceful degradation.
        </p>
      </>
    ),
  },
  {
    q: "What is delta-v here, and why are the numbers what they are?",
    a: (
      <>
        <p className={styles.p}>
          Delta-v is the velocity change a satellite&apos;s thrusters have spent, in m/s — the
          fuel cost of flying to a new slot. Thrust is capped at an engine limit (the
          maximum acceleration), a scenario parameter.
        </p>
        <p className={styles.p}>
          The committed demo scenario uses 0.1 m/s² — a higher-thrust variant of the assumed
          cold-gas class — because the measured finding is that at the 8 km formation scale
          the small-satellite default (0.01 m/s²) cannot complete the transfers at all: CW
          dynamics cap what a saturated controller can chase. The result is honest heavy
          spending — up to 193.68 m/s per satellite in the recorded two-failure demo run,
          reported rather than tuned away. <a href="#/docs">Details in Docs</a>.
        </p>
      </>
    ),
  },
  {
    q: "Can the AI predict failures?",
    a: (
      <>
        <p className={styles.p}>
          There is a sealed LightGBM proof of concept, trained on synthetic degradation
          telemetry from the simulator&apos;s own failure schedule. Its honest status: on the
          failure families it was trained on it flags precursors earlier than the EWMA/CUSUM
          baseline — about 260 s median lead across 31/31 paired events. It does not
          generalize to unseen families (family holdout: 0/15 detected), and sudden death has
          about zero recall by construction — a satellite that dies without warning has no
          precursor to learn; the reactive 4 s detection is the safety net for it.
        </p>
        <p className={styles.p}>
          It is not wired into the swarm. The pre-registered kill switch — an oracle sweep
          asking how much warning lead time is worth — found that even perfect warning
          improved how well the critical roles stay covered by at most 0.0235 percentage
          points, far below the 0.5-point bar set before the test, so the
          verdict was CUT: the demo ships reactive-only. The Suspect annotation you may see on
          a satellite is a rule-based drift detector, not the learned model.
        </p>
      </>
    ),
  },
  {
    q: "Why does the UI sometimes say “unmeasured”?",
    a: (
      <p className={styles.p}>
        Project rule: no number appears anywhere without a measured source — the live wire
        or a recorded run. When a value does not exist (no reference runs, no backend
        greeting yet), the console shows the word &quot;unmeasured&quot; instead of inventing
        one. Treat every number you see as traceable, and every &quot;unmeasured&quot; as a
        promise kept.
      </p>
    ),
  },
  {
    q: "What are live and replay?",
    a: (
      <p className={styles.p}>
        Live runs the physics engine now: the console connects over a WebSocket, and you can
        start the simulation, inject failures and watch detection, replanning and recovery in
        real time. Replay scrubs a recorded run through the same console — it reads the same
        logs the simulator writes, one schema, one deserializer — so the demo always has
        a deterministic fallback. Same scenario and seed produce a byte-identical log; replay
        is frozen evidence, not a re-enactment.
      </p>
    ),
  },
] as const;

export default function FaqPage() {
  return (
    <PageShell title="FAQ">
      <p className={styles.lede}>
        Short answers to the questions KINTSUGI-6 gets asked in the room. Every number comes
        from a recorded run or the benchmark.
      </p>

      <section className={styles.section} aria-label="Questions and answers">
        {QUESTIONS.map((item) => (
          <article key={item.q} className={styles.qa}>
            <h2 className={styles.q}>{item.q}</h2>
            {item.a}
          </article>
        ))}
      </section>
    </PageShell>
  );
}
