// Console shell — FRONTEND_SPEC §12.1 layout, §13.3 surfaces.
// Grid: top status bar / (left panel | center | right panel) / bottom panel.
import { useWebSocket } from "./hooks/useWebSocket";
import TopStatusBar from "./components/layout/TopStatusBar";
import LeftPanel from "./components/layout/LeftPanel";
import CenterPanel from "./components/layout/CenterPanel";
import RightPanel from "./components/layout/RightPanel";
import BottomPanel from "./components/layout/BottomPanel";
import styles from "./App.module.css";

export default function App() {
  useWebSocket();
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
