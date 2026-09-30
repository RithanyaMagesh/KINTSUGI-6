// Console shell — FRONTEND_SPEC §12.1 layout, §13.3 surfaces. Presentation
// mode (§6.3) swaps the console grid for the §12.2 pitch layout; the WS feed
// and the chart sampler run in both so the switch drops no data.
import { useWebSocket } from "./hooks/useWebSocket";
import { useFrameHistory } from "./stores/historyStore";
import { useUiStore } from "./stores/uiStore";
import TopStatusBar from "./components/layout/TopStatusBar";
import LeftPanel from "./components/layout/LeftPanel";
import CenterPanel from "./components/layout/CenterPanel";
import RightPanel from "./components/layout/RightPanel";
import BottomPanel from "./components/layout/BottomPanel";
import PresentationView from "./components/layout/PresentationView";
import styles from "./App.module.css";

export default function App() {
  useWebSocket();
  useFrameHistory(); // chart sampler — store subscriptions, zero per-message renders
  const presentation = useUiStore((s) => s.presentationMode);

  if (presentation) {
    return <PresentationView />;
  }

  return (
    <div className={styles.console}>
      <TopStatusBar />
      <div className={styles.main}>
        <LeftPanel />
        <CenterPanel />
        <RightPanel />
      </div>
      <BottomPanel />
    </div>
  );
}
