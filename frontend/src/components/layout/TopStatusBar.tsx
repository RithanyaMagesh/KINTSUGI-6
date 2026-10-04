// Top status bar — ONE compact row (§12.1 mission status bar): identity,
// scenario, mission state chip (§7.2 state colors), sim time, live/replay
// mode chip (§7.9), connection dot + text, mission-brief "?" and the
// presentation toggle. The brief modal itself mounts in App.tsx (one instance
// for both layouts); this bar's "?" button drives its uiStore flag.
import { useSimStore } from "../../stores/simStore";
import { useUiStore } from "../../stores/uiStore";
import { missionStateColor } from "../../utils/colors";
import { formatSimTime } from "../../utils/format";
import { isMissionState } from "../../types/satellite";
import chrome from "../../styles/chrome.module.css";
import styles from "./TopStatusBar.module.css";

const CONNECTION_LABEL: Record<string, string> = {
  connected: "Connected",
  reconnecting: "Reconnecting…",
  disconnected: "Disconnected",
};

const CONNECTION_COLOR: Record<string, string> = {
  connected: "var(--status-nominal)",
  reconnecting: "var(--status-caution)",
  disconnected: "var(--status-failed)",
};

export default function TopStatusBar() {
  const missionState = useSimStore((s) => s.missionState);
  const simTime = useSimStore((s) => s.simTime);
  const connection = useSimStore((s) => s.connection);
  const mode = useSimStore((s) => s.mode);
  const scenario = useSimStore((s) => s.scenario);
  const presentation = useUiStore((s) => s.presentationMode);
  const setPresentationMode = useUiStore((s) => s.setPresentationMode);
  const setMissionBriefOpen = useUiStore((s) => s.setMissionBriefOpen);

  const stateLabel =
    missionState !== null && isMissionState(missionState)
      ? missionState // backend enum value — uppercase is data, not styling (§13.2)
      : "Waiting for simulation data"; // §6.1 verbatim while no frame has arrived

  return (
    <header className={styles.bar}>
        <span className={styles.name}>Swarm console</span>
        <span className={styles.scenario} title={scenario ?? undefined}>
          {scenario ?? "—"}
        </span>
        <span
          className={styles.stateChip}
          data-waiting={missionState === null}
          style={{ color: missionStateColor(missionState) }}
        >
          <span className={styles.dot} style={{ background: missionStateColor(missionState) }} />
          <span className={styles.stateWord}>{stateLabel}</span>
        </span>
        <span className={styles.mono} aria-label="Sim time">
          {formatSimTime(simTime)}
        </span>
        {/* §7.9 mode is part of the operator's picture; hidden while stopped
            because "Live" with no backend would be a lie (§20). */}
        {mode !== "stopped" && (
          <span className={styles.modeChip} data-mode={mode}>
            {mode === "replay" ? "Replay" : "Live"}
          </span>
        )}
        <span className={styles.connection} data-connection={connection}>
          <span
            className={styles.dot}
            style={{ background: CONNECTION_COLOR[connection] ?? "var(--ink-faint)" }}
          />
          {CONNECTION_LABEL[connection] ?? connection}
        </span>
        <button
          className={`${chrome.btn} ${styles.helpBtn}`}
          onClick={() => setMissionBriefOpen(true)}
          aria-label="Open mission brief"
          title="Mission brief"
        >
          ?
        </button>
        {/* §23 primary demo button — switches to the §12.2 presentation layout. */}
        <button
          className={chrome.btn}
          onClick={() => setPresentationMode(!presentation)}
          aria-pressed={presentation}
        >
          {presentation ? "Exit presentation" : "Presentation mode"}
        </button>
    </header>
  );
}
