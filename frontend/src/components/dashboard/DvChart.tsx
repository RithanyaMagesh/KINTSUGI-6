// Δv used per satellite — §7.5 chart 4. Per-sat stepped lines (stepAfter:
// dv_used changes only when a burn is commanded). Series colors come from the
// §13.1 token set with §13.4 line-style variation; every line carries its
// direct end-of-line SAT label — never a legend chip row.
import { useSimStore } from "../../stores/simStore";
import { useHistoryStore } from "../../stores/historyStore";
import TelemetryChart, { type SeriesSpec } from "./TelemetryChart";

// §13.1 token palette in id order; dash patterns add the §13.4 line-style cue.
const PALETTE = [
  { color: "var(--status-nominal)" },
  { color: "var(--status-info)", dash: "6 3" },
  { color: "var(--status-caution)" },
  { color: "var(--status-leader)", dash: "2 3" },
  { color: "var(--ink)", dash: "8 3" },
  { color: "var(--status-failed)", dash: "4 3" },
  { color: "var(--ink-muted)" },
  { color: "var(--ink-faint)", dash: "6 3" },
];

export default function DvChart() {
  const samples = useHistoryStore((s) => s.samples);
  const satellites = useSimStore((s) => s.satellites);
  const data = samples.map((s) => ({ t: s.t, ...s.dv }));
  const last = samples.length > 0 ? samples[samples.length - 1] : null;

  // Series keys from the LIVE satellite list (the ids the backend reports);
  // index iteration, one series per id.
  const series: SeriesSpec[] = satellites.map((sat, i) => ({
    key: sat.id,
    label: sat.id,
    color: PALETTE[i % PALETTE.length].color,
    dash: PALETTE[i % PALETTE.length].dash,
    step: true, // §7.5: per-sat stepped lines
  }));

  return (
    <TelemetryChart
      title="Δv used per satellite"
      data={data}
      xKey="t"
      xLabel="t [s]"
      yLabel="Δv [m/s]"
      yTickFormat={(v) => v.toFixed(1)}
      endLabelX={last?.t ?? null}
      endLabelY={(s) => {
        const v = last?.dv[s.key];
        return typeof v === "number" ? v : null;
      }}
      series={series}
      height={190}
    />
  );
}
