// End-of-run card from the server's run_summary, plus counts measured from the
// last frame and the handoff log. Dismissed per run.
import { useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { clock } from "./hudFormat";
import styles from "./ImmersiveLive.module.css";

export default function RunSummaryCard() {
  const summary = useSimStore((s) => s.runSummary);
  const sats = useSimStore((s) => s.satellites);
  const handoffs = useSimStore((s) => s.handoffs.length);
  const [closed, setClosed] = useState<typeof summary>(null);
  if (summary === null || closed === summary) return null;

  const lost = sats.filter((s) => s.status === "failed").length;
  const cov = summary.coverageMeanLastOrbit;
  return (
    <section className={`${styles.summary} ${styles.glass}`} aria-label="Run finished">
      <div className={styles.summaryHead}>
        <h2>Run finished{summary.scenario !== null && <span>{summary.scenario.replace(/_/g, " ")}</span>}</h2>
        <button type="button" className={styles.summaryClose} onClick={() => setClosed(summary)} aria-label="Close">
          ×
        </button>
      </div>
      <dl className={styles.summaryGrid}>
        <div>
          <dt>Coverage, last orbit</dt>
          <dd>{cov === null ? "unmeasured" : `${(cov * 100).toFixed(1)}%`}</dd>
        </div>
        <div>
          <dt>Ran for</dt>
          <dd>{summary.simTime === null ? "unmeasured" : clock(summary.simTime)}</dd>
        </div>
        <div>
          <dt>Satellites lost</dt>
          <dd>
            {lost} of {sats.length}
          </dd>
        </div>
        <div>
          <dt>Role handoffs</dt>
          <dd>{handoffs}</dd>
        </div>
      </dl>
    </section>
  );
}
