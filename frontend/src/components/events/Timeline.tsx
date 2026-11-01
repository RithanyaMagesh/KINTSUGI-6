// The signature element (§13.5): the state-machine timeline spine —
// Nominal, Failure detected, Replanning, Moving to new slots, Recovered as a
// horizontal rail with real event ticks and sim-time stamps from the stream. No data, no story — the empty state says so.
// In replay mode the spine seeks: state nodes and stamps are buttons that
// call the same server-side seek the ReplayControls use (POST /replay/seek),
// targeting the measured phase-start times from recoveryStore.
import { useState } from "react";
import { useSimStore } from "../../stores/simStore";
import { useReplayStore } from "../../stores/replayStore";
import { useRecoveryStore, selectPhaseStarts } from "../../stores/recoveryStore";
import { backend } from "../../api/backend";
import { STATE_SPINE, type MissionState } from "../../types/satellite";
import { clock, eventText, stateLabel } from "../live/hudFormat";
import { rewindStores } from "../controls/ReplayControls";
import chrome from "../../styles/chrome.module.css";
import styles from "./Timeline.module.css";

export default function Timeline() {
  const missionState = useSimStore((s) => s.missionState);
  const simTime = useSimStore((s) => s.simTime);
  const events = useSimStore((s) => s.events);
  const mode = useSimStore((s) => s.mode);
  const phaseStarts = useRecoveryStore(selectPhaseStarts);
  const [seekError, setSeekError] = useState<string | null>(null);

  const activeIndex = missionState !== null ? STATE_SPINE.indexOf(missionState as MissionState) : -1;
  const railEnd = Math.max(simTime ?? 0, 1);
  const notable = events.filter((e) => e.level !== "info");
  const replay = mode === "replay";

  function seekTo(t: number): void {
    // Same plumbing ReplayControls uses: the backend owns replay playback
    // (POST /replay/seek) and the next frames arrive over /ws/state.
    const now = useSimStore.getState().simTime;
    if (now !== null && t < now) rewindStores(); // keep later events from leaking backwards
    useReplayStore.getState().setCurrentTime(t);
    backend
      .replaySeek(t)
      .then(() => setSeekError(null))
      .catch((err: unknown) =>
        setSeekError(err instanceof Error ? err.message : "Replay seek failed"),
      );
  }

  return (
    <section className={styles.timeline} aria-label="Mission state timeline">
      <div className={styles.rail}>
        {STATE_SPINE.map((state, i) => {
          const reached = i <= activeIndex;
          const tStart = phaseStarts[state];
          const canSeek = replay && reached && tStart !== undefined;
          const label =
            tStart !== undefined
              ? `Jump to ${stateLabel(state)} at ${clock(tStart)}`
              : `Jump to ${stateLabel(state)}`;
          const node = (
            <span
              className={`${styles.node} ${reached ? styles.reached : ""} ${i === activeIndex ? styles.active : ""}`}
              data-state={state}
            />
          );
          return (
            <div key={state} className={styles.nodeWrap}>
              {canSeek ? (
                <button
                  type="button"
                  className={styles.nodeBtn}
                  onClick={() => seekTo(tStart)}
                  aria-label={label}
                  title={label}
                >
                  {node}
                </button>
              ) : (
                node
              )}
              <span className={`${styles.nodeLabel} ${reached ? styles.labelReached : ""}`}>
                {stateLabel(state)}
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
            title={`${clock(event.simTime)}: ${eventText(event.message)}`}
          />
        ))}
      </div>
      <div className={styles.stamps}>
        {notable.slice(-2).map((event, i) => {
          const label = `Jump to ${clock(event.simTime)}`;
          const stamp = (
            <>
              {clock(event.simTime)}: {eventText(event.message)}
            </>
          );
          return replay ? (
            <button
              key={`stamp-${i}`}
              type="button"
              className={styles.stampBtn}
              onClick={() => seekTo(event.simTime)}
              aria-label={label}
              title={label}
            >
              {stamp}
            </button>
          ) : (
            <span key={`stamp-${i}`} className={styles.stamp}>
              {stamp}
            </span>
          );
        })}
      </div>
      {seekError !== null && <p className={chrome.errorText}>{seekError}</p>}
      {missionState === null && (
        <p className={chrome.hint}>The timeline starts when a simulation runs.</p>
      )}
    </section>
  );
}
