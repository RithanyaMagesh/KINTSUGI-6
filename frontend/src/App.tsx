// App shell — round 2: the app is PAGES now. TopStatusBar carries the
// persistent nav (wordmark links home); pages/Router.tsx fills the page area
// below it via the hash routes #/ #/live #/replay #/tutorial #/faq #/docs.
// The 3D LandingPage (components/landing/) serves as the main intro on route #/.
// The top-bar "?" links to #/faq.
import { useWebSocket } from "./hooks/useWebSocket";
import { useFrameHistory } from "./stores/historyStore";
import { useUiStore } from "./stores/uiStore";
import TopStatusBar from "./components/layout/TopStatusBar";
import Router from "./pages/Router";
import styles from "./App.module.css";

export default function App() {
  useWebSocket();
  useFrameHistory(); // chart sampler — store subscriptions, zero per-message renders
  const route = useUiStore((s) => s.route);

  // #/live is a full-screen 3D stage with its own floating HUD (wordmark
  // links home), so the persistent top bar steps aside there.
  if (route === "live") {
    return <Router />;
  }

  return (
    <div className={styles.app}>
      <TopStatusBar />
      <Router />
    </div>
  );
}
