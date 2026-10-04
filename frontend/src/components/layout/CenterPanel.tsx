// Center panel — the 3D swarm scene, full bleed (§12.1): no title row and no
// padding, the canvas owns every pixel of the panel. The §8.8 camera preset
// buttons are the scene's own compact overlay row (SwarmScene.tsx, another
// agent's file) and stay exactly where they are; the scene also owns its §20
// connection/empty overlays so the canvas never shows a blank screen.
import SwarmScene from "../three/SwarmScene.tsx"; // .tsx: keeps tsc from case-matching swarmScene.ts on Windows
import chrome from "../../styles/chrome.module.css";
import styles from "./CenterPanel.module.css";

export default function CenterPanel() {
  return (
    <section className={`${chrome.panel} ${styles.panel}`} aria-label="Swarm view">
      <SwarmScene />
    </section>
  );
}
