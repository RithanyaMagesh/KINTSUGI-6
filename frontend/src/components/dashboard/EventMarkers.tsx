// Event markers — labeled vertical ticks with sim-time stamps at
// failure / replan / recovery. Values come from the mission-state transitions
// recorded by the history sampler; nothing is invented (invariant 1).
// Display decision: RECONFIGURING is dropped — it fires within seconds of
// REPLANNING and its tick lands on top of the replan label. Adjacent
// markers alternate label sides so stamps stay readable.
import { ReferenceLine } from "recharts";
import { TICK_STYLE } from "./TelemetryChart";
import type { ChartMarker } from "../../stores/historyStore";
import { clock, stateLabel } from "../live/hudFormat";

function markerColor(m: ChartMarker): string {
  if (m.label === "RECOVERED") return "var(--status-repaired)"; // gold = recovered only
  switch (m.level) {
    case "critical":
      return "var(--status-failed)";
    case "caution":
      return "var(--status-caution)";
    default:
      return "var(--status-info)";
  }
}

export function EventMarkers({ markers }: { markers: ChartMarker[] }) {
  const shown = markers.filter((m) => m.label !== "RECONFIGURING");
  return (
    <>
      {shown.map((m, i) => {
        const word = stateLabel(m.label);
        return (
          <ReferenceLine
            key={`${m.label}-${m.t}-${i}`}
            x={m.t}
            stroke={markerColor(m)}
            strokeDasharray="4 4"
            label={{
              value: `${word} ${clock(m.t)}`,
              position: i % 2 === 0 ? "insideTopLeft" : "insideTopRight",
              ...TICK_STYLE,
              fill: markerColor(m),
            }}
          />
        );
      })}
    </>
  );
}
