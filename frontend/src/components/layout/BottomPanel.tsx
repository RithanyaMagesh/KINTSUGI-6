// Bottom panel — compact two-zone recovery story: LEFT the one-sentence
// NarrationStrip above the §13.5 signature state-machine timeline spine;
// RIGHT the collapsible 14px-mono event log. ReplayControls stays mounted
// below the spine: it is the only replay load/play/seek surface in console
// mode (removing it would strand §6.2 replay). PresentationView mounts its
// own instance in replay mode — App renders one layout at a time, so the two
// never coexist.
import EventLog from "../events/EventLog";
import Timeline from "../events/Timeline";
import ReplayControls from "../controls/ReplayControls";
import NarrationStrip from "../narration/NarrationStrip";
import styles from "./BottomPanel.module.css";

export default function BottomPanel() {
  return (
    <footer className={styles.footer}>
      <section className={styles.storyZone} aria-label="Recovery story">
        <NarrationStrip />
        <Timeline />
        <ReplayControls />
      </section>
      <section className={styles.logZone} aria-label="Event log">
        <EventLog />
      </section>
    </footer>
  );
}
