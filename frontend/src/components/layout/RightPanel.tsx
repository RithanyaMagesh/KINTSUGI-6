// Telemetry readouts — §13.3 readout rows (label sans muted · value mono
// 28px+), grouped in a table-like column. NO metric-card grid. Every value
// traces to the stream; absent values render "unmeasured" (invariant 1).
import { useSimStore } from "../../stores/simStore";
import ReadoutRow from "../dashboard/ReadoutRow";
import chrome from "../../styles/chrome.module.css";
import styles from "./RightPanel.module.css";

export default function RightPanel() {
  const metrics = useSimStore((s) => s.metrics);
  const satellites = useSimStore((s) => s.satellites);

  // Δv used, swarm total: arithmetic on streamed values only — never invented.
  const dvTotal = satellites.reduce((sum, s) => sum + s.dv_used, 0);
  const hasSats = satellites.length > 0;

  return (
    <aside className={`${chrome.panel} ${styles.panel}`}>
      <h2 className={chrome.panelTitle}>Telemetry</h2>
      <div className={styles.column}>
        <ReadoutRow label="Ground coverage" value={metrics.coverage === undefined ? null : metrics.coverage} format={(v) => `${(v * 100).toFixed(1)} %`} />
        <ReadoutRow label="Coverage, orbit average" value={null} format={(v) => `${(v * 100).toFixed(1)} %`} />
        <ReadoutRow label="Formation deviation" value={metrics.formationDeviation} format={(v) => `${v.toFixed(1)} m`} />
        <ReadoutRow label="Minimum separation" value={metrics.minSep} format={(v) => `${v.toFixed(1)} m`} />
        <ReadoutRow label="Δv used, swarm total" value={hasSats ? dvTotal : null} format={(v) => `${v.toFixed(2)} m/s`} />
        <ReadoutRow label="Detection latency" value={metrics.detectionLatencyS} format={(v) => `${v.toFixed(2)} s`} />
        <ReadoutRow label="Replanning latency" value={metrics.replanningLatencyMs} format={(v) => `${v.toFixed(0)} ms`} />
      </div>
      <p className={chrome.hint}>
        Coverage average and formation deviation are not carried by the current
        log format — they render as unmeasured rather than being estimated.
      </p>
    </aside>
  );
}
