// Center panel — the 3D swarm scene (plain Three.js, §5/§14). The scene owns
// its own §20 connection/empty overlays so the canvas never shows a blank
// screen.
import SwarmScene from "../three/SwarmScene.tsx"; // .tsx: keeps tsc from case-matching swarmScene.ts on Windows
import chrome from "../../styles/chrome.module.css";
import styles from "./CenterPanel.module.css";

export default function CenterPanel() {
  return (
    <section className={`${chrome.panel} ${styles.panel}`}>
      <h2 className={chrome.panelTitle}>Swarm view</h2>
      <SwarmScene />
    </section>
  );
}
