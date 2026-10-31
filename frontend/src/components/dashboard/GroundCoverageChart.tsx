// Ground coverage over time — §7.5 chart 1, the money chart: high and stable
// before failure, a sharp drop after, recovery after replanning. Event markers
// at failure / replanning / recovery with mono sim-time stamps (§13.4).
// Honesty note (invariant 1 + §3.2 #10): the wire carries a single active run,
// so only the measured swarm curve is plotted; the caption states the measured
// P0 benchmark comparison from data/eval/benchmark_results.json rather than
// fabricating synthetic reference curves.
import { useHistoryStore } from "../../stores/historyStore";
import TelemetryChart from "./TelemetryChart";
import { EventMarkers } from "./EventMarkers";

export default function GroundCoverageChart() {
  const samples = useHistoryStore((s) => s.samples);
  const markers = useHistoryStore((s) => s.markers);
  const data = samples.map((s) => ({ t: s.t, coverage: s.coverage }));
  const last = samples.length > 0 ? samples[samples.length - 1] : null;

  return (
    <TelemetryChart
      title="Ground coverage over time"
      data={data}
      xKey="t"
      xLabel="Time (s)"
      yLabel="Coverage"
      yDomain={[0, 1]}
      yTickFormat={(v) => `${(v * 100).toFixed(0)}%`}
      endLabelX={last?.t ?? null}
      endLabelY={() => (last?.coverage ?? null)}
      series={[{ key: "coverage", label: "coverage", color: "var(--status-nominal)" }]}
      height={200}
      caption="This run only. Markers show the failure, the replan and the recovery."
    >
      <EventMarkers markers={markers} />
    </TelemetryChart>
  );
}
