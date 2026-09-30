// Minimum inter-satellite distance over time — §7.5 chart 3, with the safety
// reference drawn as a labeled line. The threshold is NOT an invented number:
// it is the session's first measured min_sep (the swarm's own healthy
// clearance) recorded by the history sampler.
import { useHistoryStore } from "../../stores/historyStore";
import TelemetryChart from "./TelemetryChart";
import { ReferenceLine } from "recharts";

export default function InterSatDistanceChart() {
  const samples = useHistoryStore((s) => s.samples);
  const minSepRef = useHistoryStore((s) => s.minSepRef);
  const data = samples.map((s) => ({ t: s.t, minSep: s.minSep }));
  const last = samples.length > 0 ? samples[samples.length - 1] : null;

  return (
    <TelemetryChart
      title="Minimum separation over time"
      data={data}
      xKey="t"
      xLabel="t [s]"
      yLabel="min separation [m]"
      yTickFormat={(v) => v.toFixed(0)}
      endLabelX={last?.t ?? null}
      endLabelY={() => last?.minSep ?? null}
      series={[{ key: "minSep", label: "min sep", color: "var(--ink)" }]}
    >
      {minSepRef !== null && (
        <ReferenceLine
          y={minSepRef}
          stroke="var(--status-caution)"
          strokeDasharray="6 4"
          label={{
            value: `nominal min-sep reference ${minSepRef.toFixed(0)} m`,
            position: "insideBottomRight",
            fill: "var(--status-caution)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
          }}
        />
      )}
    </TelemetryChart>
  );
}
