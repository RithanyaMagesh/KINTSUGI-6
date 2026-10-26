// AI early-warning panel — #/live control seat. Per-satellite risk readout from
// the wire's optional sats[].risk field (FRONTEND_SPEC Appendix D): bars 0-1
// with mono values in --status-caution, one row per satellite the frame
// actually carries a score for.
//
// Claims honesty (audit_out/AUDIT.md + ENDGAME_PLAN §7): the LightGBM model is
// strictly display-only — cut from the control loop by the pre-registered
// oracle sweep (+0.0235 pp vs 0.5 pp threshold). Reactive 4 s heartbeat
// detection drives all reassignments; no risk number is ever invented.
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
        <h2 className={chrome.panelTitle}>AI early warning (display-only)</h2>
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
          <>
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
            <p className={chrome.hint}>
              Display-only LightGBM precursor score (sats[].risk); cut from the
              control loop by the oracle kill switch (+0.0235 pp vs 0.5 pp
              threshold). Reactive 4 s heartbeat detection drives recovery.
            </p>
          </>
        ) : (
          <p className={styles.riskAbsent}>
            No sats[].risk scores on the stream — enable &quot;AI risk overlay&quot; before
            starting a run to attach the offline LightGBM precursor scores
            (display-only, not in the control loop; <a href="#/docs">see Docs</a>).
          </p>
        ))}
    </section>
  );
}
