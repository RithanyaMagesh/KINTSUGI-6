// Telemetry chart frame — §13.4 chart law: solid 2px lines, no per-point
// dots, no gradient fills, hairline gridlines in --border, axis ticks in
// Plex Mono at the §13.2 tick size, direct end-of-line labels (no legend
// chip row). Shared by every chart in the dashboard so the styling is
// decided once. Animation is off everywhere (§13.5: near-zero UI motion;
// data streams at 2 Hz).
import type { ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import chrome from "../../styles/chrome.module.css";
import styles from "./TelemetryChart.module.css";

export const TICK_STYLE = {
  fill: "var(--ink-muted)",
  fontSize: 12, // §13.2 axis ticks: 12-13px
  fontFamily: "var(--font-mono)",
} as const;

export interface SeriesSpec {
  key: string;
  label: string; // direct end-of-line label text
  color: string; // a var() token reference — never a library default
  dash?: string; // line-style AND color distinguish series (§13.4)
  step?: boolean; // stepped interpolation (§7.5 dv lines)
}

interface Props {
  title: string;
  data: Array<Record<string, unknown>>;
  xKey: string;
  xLabel: string;
  yLabel: string;
  yDomain?: [number | string, number | string];
  yTickFormat?: (v: number) => string;
  children?: ReactNode; // extra layers: event-marker ReferenceLines etc.
  series: SeriesSpec[];
  endLabelX?: number | null; // last x value — anchors the end-of-line labels
  endLabelY?: (series: SeriesSpec) => number | null;
  height?: number;
}

export default function TelemetryChart({
  title,
  data,
  xKey,
  xLabel,
  yLabel,
  yDomain,
  yTickFormat,
  children,
  series,
  endLabelX = null,
  endLabelY,
  height = 160,
}: Props) {
  const last = data.length > 0 ? data[data.length - 1] : null;
  return (
    <section className={styles.chart}>
      <h3 className={chrome.panelTitle}>{title}</h3>
      {data.length === 0 ? (
        <p className={chrome.hint} style={{ minHeight: 60 }}>
          Waiting for telemetry...
        </p>
      ) : (
        <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 88, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--border)" />
            <XAxis
              dataKey={xKey}
              tick={TICK_STYLE}
              stroke="var(--border)"
              label={{
                value: xLabel,
                position: "insideBottomRight",
                offset: -2,
                ...TICK_STYLE,
              }}
              tickLine={false}
              minTickGap={40}
            />
            <YAxis
              domain={yDomain ?? ["auto", "auto"]}
              tick={TICK_STYLE}
              tickFormatter={yTickFormat}
              stroke="var(--border)"
              width={56}
              tickLine={false}
              label={{
                value: yLabel,
                angle: -90,
                position: "insideLeft",
                ...TICK_STYLE,
              }}
            />
            <Tooltip
              contentStyle={{
                background: "var(--panel-raised)",
                border: "1px solid var(--border-strong)",
                borderRadius: 6,
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--ink)",
              }}
              labelFormatter={(v) => `${xLabel} ${Number(v).toFixed(0)}`}
              isAnimationActive={false}
            />
            {children}
            {series.map((s) => (
              <Line
                key={s.key}
                type={s.step === true ? "stepAfter" : "linear"}
                dataKey={s.key}
                stroke={s.color}
                strokeWidth={2} // §13.4: solid 2px
                strokeDasharray={s.dash}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
            {series.map((s) => {
              const y = endLabelY?.(s) ?? null;
              if (last === null || endLabelX === null || y === null) return null;
              return (
                <ReferenceDot
                  key={`${s.key}-end`}
                  x={endLabelX}
                  y={y}
                  r={0}
                  isFront
                  ifOverflow="extendDomain"
                  label={{
                    value: s.label,
                    position: "right",
                    fill: s.color,
                    fontSize: 12,
                    fontFamily: "var(--font-mono)",
                  }}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
