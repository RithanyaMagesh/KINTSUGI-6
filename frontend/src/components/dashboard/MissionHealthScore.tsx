// Mission health score — §8.7: one judge-friendly number 0-100, derived ONLY
// from measured inputs (utils/health.ts). Rendered as a readout row (big mono
// value, §13.3) with its §8.7 colour band as text (§22: never colour alone),
// over its history line.
import { useHistoryStore } from "../../stores/historyStore";
import { healthBand } from "../../utils/health";
import TelemetryChart from "./TelemetryChart";
import styles from "./MissionHealthScore.module.css";

const BAND_TOKEN: Record<string, string> = {
  nominal: "var(--status-nominal)",
  caution: "var(--status-caution)",
  failed: "var(--status-failed)",
};

export default function MissionHealthScore() {
  const samples = useHistoryStore((s) => s.samples);
  const last = samples.length > 0 ? samples[samples.length - 1] : null;
  const health = last?.health ?? null;
  const band = health === null ? null : healthBand(health);

  return (
    <>
      <section className={styles.score}>
        <h3 className={styles.title}>Mission health score</h3>
        {health === null || band === null ? (
          <p className={styles.value}>unmeasured</p>
        ) : (
          <p className={styles.value} style={{ color: BAND_TOKEN[band] }}>
            {health.toFixed(0)} / 100 <span className={styles.band}>({band})</span>
          </p>
        )}
      </section>
      <TelemetryChart
        title="Mission health over time"
        data={samples.map((s) => ({ t: s.t, health: s.health }))}
        xKey="t"
        xLabel="t [s]"
        yLabel="health / 100"
        yDomain={[0, 100]}
        yTickFormat={(v) => v.toFixed(0)}
        endLabelX={last?.t ?? null}
        endLabelY={() => last?.health ?? null}
        series={[{ key: "health", label: "health", color: "var(--status-info)" }]}
        height={140}
      />
    </>
  );
}
