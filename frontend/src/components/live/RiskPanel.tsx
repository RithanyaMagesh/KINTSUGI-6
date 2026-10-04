// AI early-warning panel — #/live sidebar. Per-satellite risk readout from
// the wire's optional sats[].risk field (FRONTEND_SPEC Appendix D): bars 0-1
// with mono values in --status-caution, one row per satellite the frame
// actually carries a score for. When the wire carries no risk at all the
// panel says so plainly — the predictor runs as an offline scoring pipeline
// (docs/ENDGAME_PLAN.md cut-first); no risk number is ever invented (repo
// invariant 1). Mount: LivePage passes it to LeftPanel's documented `builder`
// slot below ScenarioBuilder; standalone, wrap in chrome.panel.
import { useState } from "react";
import { useSimStore } from "../../stores/simStore";
import type { Satellite } from "../../types/satellite";
import chrome from "../../styles/chrome.module.css";
import styles from "./LivePage.module.css";

export default function RiskPanel() {
  const satellites = useSimStore((s) => s.satellites);
  const [show, setShow] = useState(true);

  // Appendix D: a satellite the frame does not score simply has no row —
  // never a placeholder value, never a guessed 0.
  const scored = satellites.filter(
    (s): s is Satellite & { risk: number } => typeof s.risk === "number",
  );

  return (
    <section className={styles.panel} aria-label="AI early warning">
      <div className={styles.panelHead}>
        <h2 className={chrome.panelTitle}>AI early warning</h2>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={show}
            onChange={(e) => setShow(e.target.checked)}
          />
          Show AI risk
        </label>
      </div>
      {show &&
        (scored.length > 0 ? (
          <ul className={styles.riskList}>
            {scored.map((sat) => (
              <li key={sat.id} className={styles.riskRow}>
                <span className={styles.riskId}>{sat.id}</span>
                <span
                  className={styles.riskTrack}
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={1}
                  aria-valuenow={sat.risk}
                  aria-label={`Failure risk, ${sat.id}`}
                >
                  <span
                    className={styles.riskBar}
                    style={{ width: `${Math.min(100, Math.max(0, sat.risk * 100))}%` }}
                  />
                </span>
                <span className={styles.riskValue}>{sat.risk.toFixed(3)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.riskAbsent}>
            Model not active on this backend — the predictor runs as an offline
            scoring pipeline; <a href="#/docs">see Docs</a>.
          </p>
        ))}
    </section>
  );
}
