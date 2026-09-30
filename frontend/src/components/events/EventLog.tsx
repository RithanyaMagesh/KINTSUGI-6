// Event log — §13.2: mono 14px rows, newest last. Rows come only from
// "event" messages on the wire; the empty state says what to do next.
import { useSimStore } from "../../stores/simStore";
import { eventLevelColor } from "../../utils/colors";
import chrome from "../../styles/chrome.module.css";
import styles from "./EventLog.module.css";

export default function EventLog() {
  const events = useSimStore((s) => s.events);

  return (
    <div className={styles.log}>
      <h2 className={chrome.panelTitle}>Events</h2>
      {events.length === 0 ? (
        <p className={chrome.hint}>
          No events yet — start a simulation or load a replay. Failures,
          replanning and state transitions appear here as they happen.
        </p>
      ) : (
        <ol className={styles.list}>
          {events.map((event, i) => (
            <li key={`${event.simTime}-${i}`} className={styles.row}>
              <span className={styles.time}>t + {event.simTime.toFixed(1)} s</span>
              <span className={styles.level} style={{ color: eventLevelColor(event.level) }}>
                {event.level}
              </span>
              <span className={styles.message}>{event.message}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
