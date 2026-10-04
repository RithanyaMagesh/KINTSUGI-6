// Top bar — round 2: persistent across pages. The wordmark links home (#/),
// the primary nav carries the operator pages as text links plus FAQ and Docs
// as 16px inline-SVG icon links (user order: "replace with icons for Docs,
// FAQs" — the old square "?" help button is retired by the FAQ icon), the
// sim status cluster (mission state chip §7.2, sim time, live/replay mode
// chip §7.9, connection), and the presentation toggle. In the §12.2 pitch
// layout PresentationView mounts this same bar; there the nav hides (the
// pitch strips chrome).
import type { ReactElement } from "react";
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
];

// Hand-drawn 16px icons (§13.6: one consistent set, meaning-bearing) — 1.5px
// currentColor stroke, rounded caps, geometry on the 16 grid. The parent
// link carries aria-label + title; the svg is decorative.
function FaqIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="8" cy="8" r="6.7" />
      <path d="M5.9 6.3c0-1.16.94-2.1 2.1-2.1s2.1.94 2.1 2.1c0 1.5-2.1 1.7-2.1 3.4" />
      <path d="M8 12.3h.01" />
    </svg>
  );
}

function DocsIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M9.5 1.75H4.5c-.97 0-1.75.78-1.75 1.75v9c0 .97.78 1.75 1.75 1.75h7c.97 0 1.75-.78 1.75-1.75V5.25L9.5 1.75z" />
      <path d="M9.5 1.75v3.5h3.75" />
      <path d="M5.5 8.75h5" />
      <path d="M5.5 11.25h3.5" />
    </svg>
  );
}

// Reference surfaces render as icon links (user order: text links go to the
// operator surfaces only); labels are announced via aria-label + title.
const ICON_NAV: Array<{ route: Route; hash: string; label: string; icon: ReactElement }> = [
  { route: "faq", hash: "#/faq", label: "Frequently asked questions", icon: <FaqIcon /> },
  { route: "docs", hash: "#/docs", label: "Documentation", icon: <DocsIcon /> },
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
          {ICON_NAV.map((n) => (
            <a
              key={n.route}
              href={n.hash}
              className={styles.iconLink}
              aria-label={n.label}
              title={n.label}
              aria-current={route === n.route ? "page" : undefined}
            >
              {n.icon}
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
