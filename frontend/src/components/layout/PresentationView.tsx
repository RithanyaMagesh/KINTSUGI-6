// Presentation mode — FRONTEND_SPEC §6.3 + §12.2 layout. The pitch view:
// mission status bar / (3D swarm view | key metrics) / recovery-story band —
// compact state banner, the one-sentence NarrationStrip, and the latest event
// as ONE compact 14px mono line (the old banner-sized event text is gone).
// NO replay transport here — the §7.8 transport lives on the replay page;
// the replay entry below navigates there via the #/replay hash. During replay
// the §20.1 live-connection overlay stays off (SwarmScene keeps it
// live-mode-only — the top-bar badge carries connection state).
// §13 design law applies unchanged: readout rows, tokens only, no new pattern.
import { useState } from "react";
import { backend } from "../../api/backend";
import { useSimStore } from "../../stores/simStore";
import TopStatusBar from "./TopStatusBar";
import SwarmScene from "../three/SwarmScene.tsx"; // .tsx: keeps tsc from case-matching swarmScene.ts on Windows
import ReadoutRow from "../dashboard/ReadoutRow";
import GroundCoverageChart from "../dashboard/GroundCoverageChart";
import NarrationStrip from "../narration/NarrationStrip";
import { missionStateColor, eventLevelColor } from "../../utils/colors";
import { formatSimTime } from "../../utils/format";
import { missionHealthScore } from "../../utils/health";
import { fitFormation } from "../../utils/geometry";
import { useHistoryStore } from "../../stores/historyStore";
import { isMissionState } from "../../types/satellite";
import chrome from "../../styles/chrome.module.css";
import styles from "./PresentationView.module.css";

export default function PresentationView() {
  const satellites = useSimStore((s) => s.satellites);
  const metrics = useSimStore((s) => s.metrics);
  const mode = useSimStore((s) => s.mode);
  const simTime = useSimStore((s) => s.simTime);
  const missionState = useSimStore((s) => s.missionState);
  const events = useSimStore((s) => s.events);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const hasSats = satellites.length > 0;
  const failed = hasSats ? satellites.filter((s) => s.status === "failed").length : 0;
  const fit = hasSats ? fitFormation(satellites, satellites.length) : null;
  const health = hasSats
    ? missionHealthScore({
        coverage: metrics.coverage ?? null,
        deviation: fit !== null && fit.ok ? fit.deviationMean : null,
        amplitude: fit !== null ? fit.amplitude : 0,
        minSep: metrics.minSep ?? null,
        minSepRef: useHistoryStore.getState().minSepRef,
      })
    : null;

  // The latest event, compact: one 14px mono line, colored by severity
  // (§22: never color alone — the level word travels with the color).
  const latest = events.length > 0 ? events[events.length - 1] : null;

  async function injectFailure(): Promise<void> {
    // One big demo button: first healthy satellite in index order, DEAD mode.
    setBusy(true);
    setError(null);
    try {
      const target = satellites.find((s) => s.status !== "failed");
      if (target === undefined) throw new Error("No healthy satellite to fail.");
      await backend.failureInject(target.id, "DEAD");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Injection failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.presentation}>
      <TopStatusBar />
      <div className={styles.main}>
        <section className={`${chrome.panel} ${styles.scenePanel}`} aria-label="Swarm view">
          <SwarmScene />
        </section>
        <aside className={`${chrome.panel} ${styles.metrics}`} aria-label="Key metrics">
          <h2 className={chrome.panelTitle}>Key metrics</h2>
          <ReadoutRow
            label="Ground coverage"
            value={metrics.coverage === undefined ? null : metrics.coverage}
            format={(v) => `${(v * 100).toFixed(1)} %`}
          />
          <ReadoutRow
            label="Minimum separation"
            value={metrics.minSep}
            format={(v) => `${v.toFixed(1)} m`}
          />
          <ReadoutRow
            label="Mission health score"
            value={health}
            format={(v) => `${v.toFixed(0)} / 100`}
          />
          <div className={styles.row}>
            <span className={styles.label}>Satellites active / failed</span>
            <span className={styles.mono}>
              {hasSats ? `${satellites.length - failed} / ${failed}` : "unmeasured"}
            </span>
          </div>
          <GroundCoverageChart />
        </aside>
      </div>
      <footer className={styles.storyBand} aria-label="Mission story">
        <NarrationStrip />
        <div className={styles.bandRow}>
          <div className={styles.stateBlock}>
            <span
              className={styles.stateBanner}
              style={{ color: missionStateColor(missionState) }}
            >
              {missionState !== null && isMissionState(missionState)
                ? missionState // backend enum value — uppercase is data (§13.2)
                : "Waiting for simulation data"}
            </span>
            <span className={styles.simTime}>{formatSimTime(simTime)}</span>
          </div>
          <p className={styles.eventLine} role="status" aria-live="polite">
            {latest !== null ? (
              <>
                <span className={styles.level} style={{ color: eventLevelColor(latest.level) }}>
                  {latest.level}
                </span>{" "}
                <span className={styles.eventText}>
                  {formatSimTime(latest.simTime)} · {latest.message}
                </span>
              </>
            ) : (
              <span className={chrome.hint}>Events appear here as the mission runs.</span>
            )}
          </p>
          <div className={styles.actions}>
            <button
              className={styles.bigBtn}
              disabled={mode !== "live" || !hasSats || busy}
              onClick={() => void injectFailure()}
            >
              Inject failure
            </button>
            {/* Replay entry is pure navigation: the transport lives on the
                replay page (#/replay), which loads a log itself. An <a> —
                the hash is the mechanism, middle-click/new-tab still works. */}
            <a className={styles.bigBtn} href="#/replay">
              Open replay
            </a>
          </div>
        </div>
        {error !== null && <p className={chrome.errorText}>{error}</p>}
      </footer>
    </div>
  );
}
