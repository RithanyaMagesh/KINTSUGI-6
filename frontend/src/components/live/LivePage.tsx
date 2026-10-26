// Live simulation page — route #/live. THE CONTROL SEAT (§2):
// One unified control column on the left with collapsible scenario setup and
// always-visible live failure injection, AI early-warning readout, step-by-step
// recovery story (RecoveryLog), and fleet list (SatelliteList) — the operator
// never hunts across hidden sidebar tabs mid-run (§3.2 #1, #2, #3).
// CenterPanel hosts the 3D LVLH scene + NarrationStrip + Timeline; RightPanel
// hosts the live telemetry readouts, 5 underline-tabbed charts, Role
// reassignment table, and SelectedSatellitePanel inspector; BottomPanel hosts
// the full-width EventLog.
import CenterPanel from "../layout/CenterPanel";
import RightPanel from "../layout/RightPanel";
import BottomPanel from "../layout/BottomPanel";
import SatelliteList from "../satellites/SatelliteList";
import FailureInjectionPanel from "../controls/FailureInjectionPanel";
import RecoveryLog from "../recovery/RecoveryLog";
import ScenarioBuilder from "./ScenarioBuilder";
import RiskPanel from "./RiskPanel";
import chrome from "../../styles/chrome.module.css";
import styles from "./LivePage.module.css";

export default function LivePage() {
  return (
    <div className={styles.page}>
      <div className={styles.main}>
        <aside className={`${chrome.panel} ${styles.controlSeat}`} aria-label="Live control seat">
          <ScenarioBuilder />
          <div className={styles.seatDivider} />
          <FailureInjectionPanel />
          <div className={styles.seatDivider} />
          <RiskPanel />
          <div className={styles.seatDivider} />
          <RecoveryLog />
          <div className={styles.seatDivider} />
          <section className={styles.fleetSection} aria-label="Swarm satellites">
            <h2 className={chrome.panelTitle}>Swarm fleet (click to inspect)</h2>
            <SatelliteList />
          </section>
        </aside>
        <CenterPanel />
        <RightPanel />
      </div>
      <BottomPanel />
    </div>
  );
}
