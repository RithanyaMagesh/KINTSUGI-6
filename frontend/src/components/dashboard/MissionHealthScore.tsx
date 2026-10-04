// Mission health score over time — §8.7 chart (Health tab). The headline
// number itself is a readout row in the right panel (§13.3) with the §8.7
// derivation in its tooltip; this component draws only the history line,
// derived by utils/health.ts from measured inputs only (invariant 1).
import { useHistoryStore } from "../../stores/historyStore";
import TelemetryChart from "./TelemetryChart";
import { EventMarkers } from "./EventMarkers";

export default function MissionHealthScore() {
  const samples = useHistoryStore((s) => s.samples);
  const markers = useHistoryStore((s) => s.markers);
  const last = samples.length > 0 ? samples[samples.length - 1] : null;

  return (
    <TelemetryChart
      title="Mission health score over time"
      data={samples.map((s) => ({ t: s.t, health: s.health }))}
      xKey="t"
      xLabel="t [s]"
      yLabel="health / 100"
      yDomain={[0, 100]}
      yTickFormat={(v) => v.toFixed(0)}
      endLabelX={last?.t ?? null}
      endLabelY={() => last?.health ?? null}
      series={[{ key: "health", label: "health", color: "var(--status-info)" }]}
      height={180}
    >
      <EventMarkers markers={markers} />
    </TelemetryChart>
  );
}
