// Center panel — hosts the 3D SwarmScene viewport plus the single unified
// recovery status rail (NarrationStrip + state-machine Timeline spine) directly
// underneath so there are never duplicate recovery timelines across the screen.
import SwarmScene from "../three/SwarmScene.tsx";
import NarrationStrip from "../narration/NarrationStrip";
import Timeline from "../events/Timeline";
import chrome from "../../styles/chrome.module.css";
import styles from "./CenterPanel.module.css";

export default function CenterPanel() {
  return (
    <div className={styles.centerColumn}>
      <section className={`${chrome.panel} ${styles.sceneHost}`} aria-label="Swarm 3D view">
        <SwarmScene />
      </section>
      <div className={styles.storyBar}>
        <NarrationStrip />
        <Timeline />
      </div>
    </div>
  );
}
