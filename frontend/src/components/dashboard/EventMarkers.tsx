// Event markers — §13.4: labeled vertical ticks with mono sim-time stamps at
// failure / replan / recovery. Values come from the mission-state transitions
// recorded by the history sampler; nothing is invented.
import { ReferenceLine } from "recharts";
import { TICK_STYLE } from "./TelemetryChart";
import type { ChartMarker } from "../../stores/historyStore";

function markerColor(level: ChartMarker["level"]): string {
  switch (level) {
    case "critical":
      return "var(--status-failed)";
    case "caution":
      return "var(--status-caution)";
    default:
      return "var(--status-info)";
  }
}

export function EventMarkers({ markers }: { markers: ChartMarker[] }) {
  return (
    <>
      {markers.map((m, i) => (
        <ReferenceLine
          key={`${m.label}-${m.t}-${i}`}
          x={m.t}
          stroke={markerColor(m.level)}
          strokeDasharray="4 4"
          label={{
            value: `t+${m.t.toFixed(0)}s`,
            position: "insideTopLeft",
            ...TICK_STYLE,
            fill: markerColor(m.level),
          }}
        />
      ))}
    </>
  );
}
