// Center panel placeholder — the 3D swarm scene (plain Three.js in one
// imperative component, §5) is the next phase; this is its honest empty
// state, not a fake scene.
import chrome from "../../styles/chrome.module.css";
import styles from "./CenterPanel.module.css";

export default function CenterPanel() {
  return (
    <section className={`${chrome.panel} ${styles.panel}`}>
      <h2 className={chrome.panelTitle}>Swarm view</h2>
      <p className={chrome.hint}>
        The 3D swarm view is built in the scene phase. Telemetry, events and the
        state timeline around this panel are already live.
      </p>
      <div className={styles.canvasSlot} aria-hidden="true" />
    </section>
  );
}
