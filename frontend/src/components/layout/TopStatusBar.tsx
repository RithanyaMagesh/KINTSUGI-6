// Top bar — persistent across pages.
// Includes primary navigation, Mission State chip, active/failed fleet count,
// Simulation time, Simplified vs. Advanced workspace view switcher, and
// Dark vs. Light theme toggle. Zero raw hex (§13.1).
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
  { route: "landing", hash: "#/", label: "Overview" },
  { route: "live", hash: "#/live", label: "Live simulation" },
  { route: "replay", hash: "#/replay", label: "Replay" },
  { route: "tutorial", hash: "#/tutorial", label: "Tutorial" },
];

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

const ICON_NAV: Array<{ route: Route; hash: string; label: string; icon: ReactElement }> = [
  { route: "faq", hash: "#/faq", label: "Frequently asked questions", icon: <FaqIcon /> },
  { route: "docs", hash: "#/docs", label: "Documentation", icon: <DocsIcon /> },
];

export default function TopStatusBar() {
  const missionState = useSimStore((s) => s.missionState);
  const simTime = useSimStore((s) => s.simTime);
  const connection = useSimStore((s) => s.connection);
  const mode = useSimStore((s) => s.mode);
  const scenario = useSimStore((s) => s.scenario);
  const satellites = useSimStore((s) => s.satellites);
  const route = useUiStore((s) => s.route);
  const viewMode = useUiStore((s) => s.viewMode);
  const setViewMode = useUiStore((s) => s.setViewMode);
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const presentation = useUiStore((s) => s.presentationMode);
  const setPresentationMode = useUiStore((s) => s.setPresentationMode);

  const stateLabel =
    missionState !== null && isMissionState(missionState)
      ? missionState
      : "Standby";

  const failedCount = satellites.reduce((n, s) => (s.status === "failed" ? n + 1 : n), 0);
  const activeCount = satellites.length - failedCount;

  return (
    <header className={styles.bar}>
      <div className={styles.brandCluster}>
        <a href="#/" className={styles.name}>
          <span className={styles.brandMark} aria-hidden="true" />
          CubeSat swarm console
        </a>
        {scenario !== null && scenario !== "" && (
          <span className={styles.metaTag} title="Active scenario">
            {scenario}
          </span>
        )}
      </div>

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
        {satellites.length > 0 && (
          <span className={styles.fleetCount} title="Active / total satellites">
            {activeCount}/{satellites.length} active
          </span>
        )}
        <span className={styles.mono} aria-label="Simulation time">
          {formatSimTime(simTime)}
        </span>
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

      {/* Console density toggle (Simplified vs Advanced) + Theme toggle (Dark vs Light) */}
      <div className={styles.toolbarControls}>
        {(route === "live" || route === "replay") && !presentation && (
          <div className={styles.segmented} role="group" aria-label="Console view density">
            <button
              type="button"
              className={`${styles.segBtn} ${viewMode === "simplified" ? styles.segActive : ""}`}
              onClick={() => setViewMode("simplified")}
              aria-pressed={viewMode === "simplified"}
            >
              Simplified
            </button>
            <button
              type="button"
              className={`${styles.segBtn} ${viewMode === "advanced" ? styles.segActive : ""}`}
              onClick={() => setViewMode("advanced")}
              aria-pressed={viewMode === "advanced"}
            >
              Advanced
            </button>
          </div>
        )}

        <button
          type="button"
          className={chrome.btn}
          onClick={toggleTheme}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </button>

        {presentation && (
          <button
            type="button"
            className={chrome.btn}
            onClick={() => setPresentationMode(false)}
          >
            Exit presentation
          </button>
        )}
      </div>
    </header>
  );
}
