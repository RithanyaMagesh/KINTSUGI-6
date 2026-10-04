// Top bar — round 2: persistent across pages. The wordmark links home (#/),
// the primary nav carries the hash-router pages with an underline indicator
// on the active route (§13.3), then the sim status cluster (mission state
// chip §7.2, sim time, live/replay mode chip §7.9, connection), then "?" —
// now a link to #/faq, the mission-brief overlay is retired as first-load —
// and the presentation toggle. In the §12.2 pitch layout PresentationView
// mounts this same bar; there the nav hides (the pitch strips chrome).
import { useSimStore } from "../../stores/simStore";
import { useUiStore, type Route } from "../../stores/uiStore";
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

const NAV: Array<{ route: Route; hash: string; label: string }> = [
  { route: "live", hash: "#/live", label: "Live simulation" },
  { route: "replay", hash: "#/replay", label: "Replay" },
  { route: "tutorial", hash: "#/tutorial", label: "Tutorial" },
  { route: "faq", hash: "#/faq", label: "FAQ" },
  { route: "docs", hash: "#/docs", label: "Docs" },
];

export default function TopStatusBar() {
  const missionState = useSimStore((s) => s.missionState);
  const simTime = useSimStore((s) => s.simTime);
  const connection = useSimStore((s) => s.connection);
  const mode = useSimStore((s) => s.mode);
  const route = useUiStore((s) => s.route);
  const presentation = useUiStore((s) => s.presentationMode);
  const setPresentationMode = useUiStore((s) => s.setPresentationMode);

  const stateLabel =
    missionState !== null && isMissionState(missionState)
      ? missionState // backend enum value — uppercase is data, not styling (§13.2)
      : "Waiting for simulation data"; // §6.1 verbatim while no frame has arrived

  return (
    <header className={styles.bar}>
      <a href="#/" className={styles.name}>
        Swarm console
      </a>
      {!presentation && (
        <nav className={styles.nav} aria-label="Primary">
          {NAV.map((n) => (
            <a
              key={n.route}
              href={n.hash}
              className={styles.navLink}
              aria-current={route === n.route ? "page" : undefined}
            >
              {n.label}
            </a>
          ))}
        </nav>
      )}
      <div className={styles.status}>
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
      </div>
      <a
        href="#/faq"
        className={`${chrome.btn} ${styles.helpBtn}`}
        aria-label="Frequently asked questions"
        title="Questions and answers"
      >
        ?
      </a>
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
