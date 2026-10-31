// Event log — §13.2: mono 14px rows, severity-colored levels, newest LAST and
// kept visible (auto-scroll). Collapsible with stable dimensions: collapsed,
// the latest event stays as one 14px line. Rows come only from "event"
// messages on the wire; the empty state says what to do next.
import { eventText } from "../live/hudFormat";
import { useEffect, useRef, useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { eventLevelColor } from "../../utils/colors";
import { formatSimTime } from "../../utils/format";
import chrome from "../../styles/chrome.module.css";
import styles from "./EventLog.module.css";

export default function EventLog() {
  const events = useSimStore((s) => s.events);
  const [collapsed, setCollapsed] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const listRef = useRef<HTMLOListElement | null>(null);
  const latest = events.length > 0 ? events[events.length - 1] : null;
  // Dedensify contract: the default view shows the latest 3 rows (the zone is
  // height-bounded by BottomPanel.module.css, so "show all" scrolls, never grows).
  const visible = showAll ? events : events.slice(-3);

  // Newest visible: keep the list scrolled to the newest row as events land.
  useEffect(() => {
    if (!collapsed && listRef.current !== null) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [events, collapsed]);

  return (
    <div className={styles.log}>
      <div className={styles.header}>
        <h2 className={styles.title}>Event log</h2>
        <span className={styles.count}>{events.length} events</span>
        <button
          type="button"
          className={chrome.btn}
          aria-expanded={!collapsed}
          aria-controls="event-log-body"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? "Show log" : "Collapse log"}
        </button>
      </div>
      {collapsed ? (
        <p id="event-log-body" className={styles.latestLine} role="status" aria-live="polite">
          {latest !== null ? (
            <>
              <span className={styles.time}>{formatSimTime(latest.simTime)}</span>
              <span className={styles.level} style={{ color: eventLevelColor(latest.level) }}>
                {latest.level}
              </span>
              <span className={styles.message}>{eventText(latest.message)}</span>
            </>
          ) : (
            <span className={chrome.hint}>No events yet.</span>
          )}
        </p>
      ) : events.length === 0 ? (
        <p id="event-log-body" className={chrome.hint}>
          No events yet — start a simulation or load a replay. Failures, replanning and
          state transitions appear here as they happen.
        </p>
      ) : (
        <>
          <ol id="event-log-body" ref={listRef} className={styles.list}>
            {visible.map((event, i) => (
              <li key={`${event.simTime}-${i}`} className={styles.row}>
                <span className={styles.time}>{formatSimTime(event.simTime)}</span>
                <span className={styles.level} style={{ color: eventLevelColor(event.level) }}>
                  {event.level}
                </span>
                <span className={styles.message}>{eventText(event.message)}</span>
              </li>
            ))}
          </ol>
          {events.length > 3 && (
            <button
              type="button"
              className={chrome.btn}
              aria-expanded={showAll}
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? "Show latest" : `Show all (${events.length})`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
