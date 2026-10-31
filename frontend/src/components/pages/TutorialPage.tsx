// Tutorial — a short, hands-on walkthrough of the live page. Ordered steps
// because it IS a sequence. Button names match the live page's real labels;
// no result numbers here (the Docs page carries the sourced ones).
import PageShell from "../../pages/PageShell";
import styles from "./pages.module.css";

// Colour always means state; the legend reads the same tokens as the scene.
const STATE_LEGEND = [
  { swatch: "var(--status-nominal)", label: "Green: healthy, holding its slot" },
  { swatch: "var(--status-caution)", label: "Amber: moving to a new slot" },
  { swatch: "var(--status-failed)", label: "Red: lost, drifting but still tracked" },
  { swatch: "var(--status-repaired)", label: "Gold: recovered" },
] as const;

const STEPS = [
  {
    title: "Set up the swarm",
    body: (
      <>
        Open <a href="#/live">Live simulation</a> and press <strong>Setup</strong> (or{" "}
        <strong>S</strong>). Pick how many satellites to fly, then press{" "}
        <strong>Start live simulation</strong>.
      </>
    ),
  },
  {
    title: "Break a satellite",
    body: (
      <>
        Click any satellite in the 3D view, or use the failure section in Setup, and press{" "}
        <strong>Fail SAT-n</strong>. It turns red and keeps drifting, so the others still have
        to steer around it.
      </>
    ),
  },
  {
    title: "Watch the swarm repair itself",
    body: (
      <>
        The mission state walks through <strong>Failure detected</strong>,{" "}
        <strong>Replanning</strong>, <strong>Moving to new slots</strong> and finally{" "}
        <strong>Recovered</strong>, shown in gold. No one on the ground sends a command.
      </>
    ),
  },
  {
    title: "Look closer",
    body: (
      <>
        <strong>Telemetry</strong> (<strong>T</strong>) has every number: ground coverage,
        closest approach, fuel spent and the recovery log. <strong>Spectate</strong> (
        <strong>V</strong>) rides along with one satellite; the arrow keys switch between them.{" "}
        <strong>H</strong> hides the interface and <strong>F</strong> goes fullscreen.
      </>
    ),
  },
  {
    title: "Replay a saved run",
    body: (
      <>
        The <a href="#/replay">Replay</a> page plays back recorded runs. Pick one, then pause,
        change speed or drag the slider to any moment of the recovery.
      </>
    ),
  },
];

export default function TutorialPage() {
  return (
    <PageShell title="Tutorial">
      <p className={styles.lede}>
        Five steps: start a swarm, break a satellite, and watch the rest repair the formation on
        their own.
      </p>

      <section className={styles.section} aria-labelledby="tut-steps">
        <h2 className={styles.sectionTitle} id="tut-steps">
          The walkthrough
        </h2>
        <ol className={styles.steps}>
          {STEPS.map((step, i) => (
            <li key={step.title} className={styles.step}>
              <span className={styles.stepNum} aria-hidden="true">
                {i + 1}
              </span>
              <div>
                <h3 className={styles.stepTitle}>{step.title}</h3>
                <p className={styles.p}>{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.section} aria-labelledby="tut-colours">
        <h2 className={styles.sectionTitle} id="tut-colours">
          What the colours mean
        </h2>
        <div className={styles.swatches}>
          {STATE_LEGEND.map((s) => (
            <span key={s.label} className={styles.swatchRow}>
              <span className={styles.swatch} style={{ background: s.swatch }} />
              <span className={styles.swatchLabel}>{s.label}</span>
            </span>
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="tut-next">
        <h2 className={styles.sectionTitle} id="tut-next">
          Where to go next
        </h2>
        <p className={styles.p}>
          The <a href="#/faq">FAQ</a> answers the questions judges ask most; the{" "}
          <a href="#/docs">Docs</a> page covers the physics, the recovery logic and where every
          number comes from.
        </p>
      </section>
    </PageShell>
  );
}
