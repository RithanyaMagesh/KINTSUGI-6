// Live simulation page — route #/live.
// Clean 3-column workspace with zero redundant panels:
// - Left column: Unscripted custom swarm setup (ScenarioBuilder) + live fault
//   injection (FailureInjectionPanel) + clickable fleet list (SatelliteList).
// - Center column: 3D orbital viewport (Earth orbit view | Formation array view)
//   + single unified recovery status bar (NarrationStrip + Timeline).
// - Right column: View-aware telemetry & inspector (Simplified vs Advanced).
import CenterPanel from "../layout/CenterPanel";
import RightPanel from "../layout/RightPanel";
import SatelliteList from "../satellites/SatelliteList";
import FailureInjectionPanel from "../controls/FailureInjectionPanel";
import ScenarioBuilder from "./ScenarioBuilder";
import chrome from "../../styles/chrome.module.css";
import styles from "./LivePage.module.css";

export default function LivePage() {
  return (
    <div className={styles.page}>
      <div className={styles.main}>
        <aside className={`${chrome.panel} ${styles.controlSeat}`} aria-label="Live simulation controls">
          <ScenarioBuilder />
          <div className={styles.seatDivider} />
          <FailureInjectionPanel />
          <div className={styles.seatDivider} />
          <section className={styles.fleetSection} aria-label="Swarm satellites">
            <h2 className={chrome.panelTitle}>Swarm fleet (click to select)</h2>
            <SatelliteList />
          </section>
        </aside>
        <CenterPanel />
        <RightPanel />
      </div>
    </div>
  );
}
