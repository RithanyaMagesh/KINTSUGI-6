// Formation deviation over time — §7.5 chart 2. The value is DERIVED from
// measured positions vs the fitted seat references (utils/geometry.ts); when
// the fit is not possible the sample is null and the gap is bridged
// (connectNulls) rather than faked.
import { useHistoryStore } from "../../stores/historyStore";
import TelemetryChart from "./TelemetryChart";
import { EventMarkers } from "./EventMarkers";

export default function FormationDeviationChart() {
  const samples = useHistoryStore((s) => s.samples);
  const markers = useHistoryStore((s) => s.markers);
  const data = samples.map((s) => ({ t: s.t, deviation: s.deviation }));
  const last = samples.length > 0 ? samples[samples.length - 1] : null;

  return (
    <TelemetryChart
      title="Distance to slot"
      data={data}
      xKey="t"
      xLabel="Time (s)"
      yLabel="Distance (m)"
      yTickFormat={(v) => v.toFixed(0)}
      endLabelX={last?.t ?? null}
      endLabelY={() => last?.deviation ?? null}
      series={[{ key: "deviation", label: "Distance", color: "var(--status-caution)" }]}
    >
      <EventMarkers markers={markers} />
    </TelemetryChart>
  );
}
