// Closest approach between any two satellites over time, with the scenario's
// keep-out floor (sent by the backend) drawn as a labeled line. Unknown floor
// (null) draws no line rather than a guessed one.
import { useHistoryStore } from "../../stores/historyStore";
import { useSimStore } from "../../stores/simStore";
import TelemetryChart, { TICK_STYLE } from "./TelemetryChart";
import { EventMarkers } from "./EventMarkers";
import { ReferenceLine } from "recharts";

export default function InterSatDistanceChart() {
  const samples = useHistoryStore((s) => s.samples);
  const markers = useHistoryStore((s) => s.markers);
  const keepOutM = useSimStore((s) => s.minSepM);
  const data = samples.map((s) => ({ t: s.t, minSep: s.minSep }));
  const last = samples.length > 0 ? samples[samples.length - 1] : null;

  return (
    <TelemetryChart
      title="Closest approach over time"
      data={data}
      xKey="t"
      xLabel="Time (s)"
      yLabel="Closest approach (m)"
      yTickFormat={(v) => v.toFixed(0)}
      endLabelX={last?.t ?? null}
      endLabelY={() => last?.minSep ?? null}
      series={[{ key: "minSep", label: "Closest", color: "var(--ink)" }]}
    >
      <EventMarkers markers={markers} />
      {keepOutM !== null && (
        <ReferenceLine
          y={keepOutM}
          stroke="var(--status-caution)"
          strokeDasharray="6 4"
          label={{
            value: `Keep-out ${keepOutM.toFixed(0)} m`,
            position: "insideBottomRight",
            ...TICK_STYLE,
            fill: "var(--status-caution)",
          }}
        />
      )}
    </TelemetryChart>
  );
}
