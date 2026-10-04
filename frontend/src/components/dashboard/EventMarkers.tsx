// Event markers — §13.4: labeled vertical ticks with mono sim-time stamps at
// failure / replan / recovery. Values come from the mission-state transitions
// recorded by the history sampler; nothing is invented (invariant 1).
// Display decision: RECONFIGURING is dropped — it fires within seconds of
// REPLANNING and its tick lands on top of the replan label. Adjacent
// markers alternate label sides so stamps stay readable.
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

/** Mission-state literals (backend enum) to operator words for the tick label. */
const WORD: Record<string, string> = {
  FAILURE_DETECTED: "failure",
  REPLANNING: "replan",
  RECOVERED: "recovered",
  DEGRADED: "degraded",
};

export function EventMarkers({ markers }: { markers: ChartMarker[] }) {
  const shown = markers.filter((m) => m.label !== "RECONFIGURING");
  return (
    <>
      {shown.map((m, i) => {
        const word = WORD[m.label] ?? m.label.toLowerCase();
        return (
          <ReferenceLine
            key={`${m.label}-${m.t}-${i}`}
            x={m.t}
            stroke={markerColor(m.level)}
            strokeDasharray="4 4"
            label={{
              value: `${word} t+${m.t.toFixed(0)}s`,
              position: i % 2 === 0 ? "insideTopLeft" : "insideTopRight",
              ...TICK_STYLE,
              fill: markerColor(m.level),
            }}
          />
        );
      })}
    </>
  );
}
