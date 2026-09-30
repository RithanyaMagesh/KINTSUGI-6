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

export default function TopStatusBar() {
  const missionState = useSimStore((s) => s.missionState);
  const simTime = useSimStore((s) => s.simTime);
  const connection = useSimStore((s) => s.connection);
  const mode = useSimStore((s) => s.mode);
  const scenario = useSimStore((s) => s.scenario);
  const presentation = useUiStore((s) => s.presentationMode);
  const setPresentationMode = useUiStore((s) => s.setPresentationMode);

  const stateLabel =
    missionState !== null && isMissionState(missionState)
      ? missionState // backend enum value — uppercase is data, not styling (§13.2)
      : "Waiting for simulation data";

  return (
    <header className={styles.bar}>
      <span className={styles.state} style={{ color: missionStateColor(missionState) }}>
        {stateLabel}
      </span>
      <span className={styles.item}>
        <span className={styles.label}>Sim time</span>
        <span className={styles.mono}>{formatSimTime(simTime)}</span>
      </span>
      <span className={styles.item}>
        <span className={styles.label}>Scenario</span>
        <span className={styles.mono}>{scenario ?? "—"}</span>
      </span>
      <span className={styles.connection} data-connection={connection}>
        {CONNECTION_LABEL[connection] ?? connection}
      </span>
      {mode === "replay" && <span className={styles.replayBadge}>Replay</span>}
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
