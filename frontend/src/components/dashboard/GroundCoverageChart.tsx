// Ground coverage over time — §7.5 chart 1, the money chart: high and stable
// before failure, a sharp drop after, recovery after replanning. Event markers
// at failure / replanning / recovery with mono sim-time stamps (§13.4).
// Honesty note (invariant 1): the spec's 3-curve comparison (nominal reference
// / no-recovery / with-recovery) needs reference runs the wire does not carry,
// so only the measured swarm curve is drawn — never a fabricated comparison.
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
      xLabel="t [s]"
      yLabel="coverage"
      yDomain={[0, 1]}
      yTickFormat={(v) => `${(v * 100).toFixed(0)}%`}
      endLabelX={last?.t ?? null}
      endLabelY={() => (last?.coverage ?? null)}
      series={[{ key: "coverage", label: "coverage", color: "var(--status-nominal)" }]}
      height={200}
      caption="Measured swarm curve. The spec's 3-curve comparison (nominal reference / no recovery / with recovery) needs reference runs the live wire does not carry."
    >
      <EventMarkers markers={markers} />
    </TelemetryChart>
  );
}
