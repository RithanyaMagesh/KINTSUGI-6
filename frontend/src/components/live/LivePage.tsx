// Live simulation page — route #/live (the shell's Router mounts this export;
// the landing page's "Open live sandbox" already links the hash). The
// standard §12.1 console grid with the scenario builder + AI early-warning
// panels in LeftPanel's documented `builder` slot (SideTabs appends the
// Builder tab); the swarm view, telemetry, narration and the state-machine
// spine are the SAME components the console mounts, so they keep their
// behavior and data sources unchanged. No top bar here: App.tsx owns the
// persistent TopStatusBar above the Router. No socket of its own: the WS
// driver lives at the App level (hooks/useWebSocket.ts) and a second one
// would double-deliver events.
import CenterPanel from "../layout/CenterPanel";
import LeftPanel from "../layout/LeftPanel";
import RightPanel from "../layout/RightPanel";
import BottomPanel from "../layout/BottomPanel";
import ScenarioBuilder from "./ScenarioBuilder";
import RiskPanel from "./RiskPanel";
import styles from "./LivePage.module.css";

export default function LivePage() {
  return (
    <div className={styles.page}>
      <div className={styles.main}>
        <LeftPanel
          builder={
            <>
              <ScenarioBuilder />
              <RiskPanel />
            </>
          }
        />
        <CenterPanel />
        <RightPanel />
      </div>
      <BottomPanel />
    </div>
  );
}
