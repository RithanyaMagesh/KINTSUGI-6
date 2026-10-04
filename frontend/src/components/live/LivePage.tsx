// Live simulation page — route #/live. THE CONTROL SEAT: the sidebar opens on
// the Builder tab (first tab; SideTabs defaults to the first), which offers
// everything the engine reads in one place — satellite count + roles,
// formation geometry, the failure list, the recovery policy, seed/speed/
// duration, the AI-risk overlay — and "Run simulation" starts the run in the
// 3D view on THIS page (pause/resume/reset ride along in the same Run group).
// The other tabs are readout/support, not competing controls: Satellites
// (fleet list), Recovery (runtime failure injection + the recovery log).
// The old LeftPanel is deliberately NOT mounted here: its Mission tab carried
// a second scenario-file selector and a second run-control group beside the
// builder's, plus a mission readout duplicating the builder's — the duplicate
// chrome this page exists to remove. The event log stays only in the bottom
// panel (BottomPanel hosts it full width; a sidebar Events tab was a second
// copy of the same log).
// No top bar here: App.tsx owns the persistent TopStatusBar above the Router,
// so the state chip + sim time come from the shell. No socket of its own: the
// WS driver lives at the App level (hooks/useWebSocket.ts); a second one
// would double-deliver events. No replay transport anywhere on this page:
// playback lives on #/replay — the builder's Run group links there instead.
import CenterPanel from "../layout/CenterPanel";
import RightPanel from "../layout/RightPanel";
import BottomPanel from "../layout/BottomPanel";
import SideTabs from "../layout/SideTabs";
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
        <aside className={chrome.panel}>
          <SideTabs
            label="Live sidebar"
            tabs={[
              {
                id: "builder",
                label: "Builder",
                content: (
                  <>
                    <ScenarioBuilder />
                    <RiskPanel />
                  </>
                ),
              },
              {
                id: "satellites",
                label: "Satellites",
                content: <SatelliteList />,
              },
              {
                id: "recovery",
                label: "Recovery",
                content: (
                  <>
                    <FailureInjectionPanel />
                    <RecoveryLog />
                  </>
                ),
              },
            ]}
          />
        </aside>
        <CenterPanel />
        <RightPanel />
      </div>
      <BottomPanel />
    </div>
  );
}
