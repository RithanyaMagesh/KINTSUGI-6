import EventLog from "../events/EventLog";
import Timeline from "../events/Timeline";
import ReplayControls from "../controls/ReplayControls";
import styles from "./BottomPanel.module.css";

export default function BottomPanel() {
  return (
    <footer className={styles.footer}>
      <section className={styles.logSection} aria-label="Event log">
        <EventLog />
      </section>
      <div className={styles.rightColumn}>
        <Timeline />
        <ReplayControls />
      </div>
    </footer>
  );
}
