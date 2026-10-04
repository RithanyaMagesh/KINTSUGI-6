// Console shell — FRONTEND_SPEC §12.1 layout, §13.3 surfaces. Presentation
// mode (§6.3) swaps the console grid for the §12.2 pitch layout; the WS feed
// and the chart sampler run in both so the switch drops no data. The mission
// brief mounts HERE (not inside a layout) so the first-load landing page and
// the top-bar "?" reopen it in BOTH layouts from one instance.
import { useWebSocket } from "./hooks/useWebSocket";
import { useFrameHistory } from "./stores/historyStore";
import { useUiStore } from "./stores/uiStore";
import TopStatusBar from "./components/layout/TopStatusBar";
import LeftPanel from "./components/layout/LeftPanel";
import CenterPanel from "./components/layout/CenterPanel";
import RightPanel from "./components/layout/RightPanel";
import BottomPanel from "./components/layout/BottomPanel";
import PresentationView from "./components/layout/PresentationView";
import MissionBrief from "./components/onboarding/MissionBrief";
import styles from "./App.module.css";

export default function App() {
  useWebSocket();
  useFrameHistory(); // chart sampler — store subscriptions, zero per-message renders
  const presentation = useUiStore((s) => s.presentationMode);
  const missionBriefOpen = useUiStore((s) => s.missionBriefOpen);

  // MissionBrief portals itself to document.body (§13.3 modal); one instance
  // for both layouts. Initial value = unseen this browser session (uiStore
  // sessionStorage flag); the top-bar "?" reopens it.
  const brief = missionBriefOpen ? <MissionBrief /> : null;

  if (presentation) {
    return (
      <>
        <PresentationView />
        {brief}
      </>
    );
  }

  return (
    <>
      <div className={styles.console}>
        <TopStatusBar />
        <div className={styles.main}>
          <LeftPanel />
          <CenterPanel />
          <RightPanel />
        </div>
        <BottomPanel />
      </div>
      {brief}
    </>
  );
}
