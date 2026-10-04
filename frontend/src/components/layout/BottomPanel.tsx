// Bottom panel — live console only: LEFT the one-sentence NarrationStrip
// above the §13.5 signature state-machine timeline spine; RIGHT the event
// log. The replay transport NO LONGER lives here — it mounts on the replay
// page (that page mounts controls/ReplayControls); live-layout entry points
// navigate to #/replay instead of hosting playback chrome.
import EventLog from "../events/EventLog";
import Timeline from "../events/Timeline";
import NarrationStrip from "../narration/NarrationStrip";
import styles from "./BottomPanel.module.css";

export default function BottomPanel() {
  return (
    <footer className={styles.footer}>
      <section className={styles.storyZone} aria-label="Recovery story">
        <NarrationStrip />
        <Timeline />
      </section>
      <section className={styles.logZone} aria-label="Event log">
        <EventLog />
      </section>
    </footer>
  );
}
