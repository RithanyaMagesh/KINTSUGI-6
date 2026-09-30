// The signature element (§13.5): the state-machine timeline spine —
// NOMINAL → FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED as a
// horizontal rail with real event ticks and mono sim-time stamps from the
// stream. No data, no story — the empty state says so.
import { useSimStore } from "../../stores/simStore";
import { STATE_SPINE, type MissionState } from "../../types/satellite";
import chrome from "../../styles/chrome.module.css";
import styles from "./Timeline.module.css";

const STATE_COLOR: Record<string, string> = {
  NOMINAL: "var(--status-nominal)",
  FAILURE_DETECTED: "var(--status-failed)",
  REPLANNING: "var(--status-caution)",
  RECONFIGURING: "var(--status-caution)",
  RECOVERED: "var(--status-info)",
};

export default function Timeline() {
  const missionState = useSimStore((s) => s.missionState);
  const simTime = useSimStore((s) => s.simTime);
  const events = useSimStore((s) => s.events);

  const activeIndex = missionState !== null ? STATE_SPINE.indexOf(missionState as MissionState) : -1;
  const railEnd = Math.max(simTime ?? 0, 1);
  const notable = events.filter((e) => e.level !== "info");

  return (
    <section className={styles.timeline} aria-label="Mission state timeline">
      <div className={styles.rail}>
        {STATE_SPINE.map((state, i) => {
          const reached = i <= activeIndex;
          return (
            <div key={state} className={styles.nodeWrap}>
              <div
                className={`${styles.node} ${reached ? styles.reached : ""} ${i === activeIndex ? styles.active : ""}`}
                style={reached ? { borderColor: STATE_COLOR[state] } : undefined}
              />
              <span className={`${styles.nodeLabel} ${reached ? styles.labelReached : ""}`}>
                {state}
              </span>
            </div>
          );
        })}
        {/* Event ticks: positioned by sim time over the rail span. */}
        {events.map((event, i) => (
          <span
            key={`tick-${i}`}
            className={styles.tick}
            style={{
              left: `${Math.min(100, Math.max(0, (event.simTime / railEnd) * 100))}%`,
              background: event.level === "critical" ? "var(--status-failed)" : "var(--status-caution)",
            }}
            title={`t + ${event.simTime.toFixed(1)} s — ${event.message}`}
          />
        ))}
      </div>
      <div className={styles.stamps}>
        {notable.slice(-4).map((event, i) => (
          <span key={`stamp-${i}`} className={styles.stamp}>
            t + {event.simTime.toFixed(1)} s · {event.message}
          </span>
        ))}
      </div>
      {missionState === null && (
        <p className={chrome.hint}>The timeline starts when a simulation runs.</p>
      )}
    </section>
  );
}
