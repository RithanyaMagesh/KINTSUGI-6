// Full-screen live HUD — the recovery sequence as five steps. Steps already
// passed show the sim time they started (measured, from recoveryStore);
// "Recovered" turns kintsugi gold — the one place the HUD spends that colour.
import { useSimStore } from "../../stores/simStore";
import { useRecoveryStore, selectPhaseStarts } from "../../stores/recoveryStore";
import { clock, PHASES } from "./hudFormat";
import styles from "./ImmersiveLive.module.css";

export default function PhaseRail() {
  const state = useSimStore((s) => s.missionState);
  const starts = useRecoveryStore(selectPhaseStarts);
  const currentIdx = PHASES.findIndex((p) => p.state === state);

  return (
    <ol className={styles.rail} aria-label="Recovery sequence">
      {PHASES.map((p, i) => {
        const reached = starts[p.state] !== undefined || i === currentIdx;
        const current = i === currentIdx;
        const repaired = p.state === "RECOVERED" && current;
        return (
          <li
            key={p.state}
            className={styles.railStep}
            data-reached={reached || undefined}
            data-current={current || undefined}
            data-repaired={repaired || undefined}
            aria-current={current ? "step" : undefined}
          >
            <span className={styles.railTick} aria-hidden="true" />
            <span className={styles.railLabel}>{p.label}</span>
            {starts[p.state] !== undefined && i > 0 && (
              <span className={styles.railTime}>{clock(starts[p.state])}</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
