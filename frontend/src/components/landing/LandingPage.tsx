// Landing page — route #/ (Router slot 'landing').
// Clean, normal product introduction for the CubeSat Swarm Self-Healing Console.
// Explains what the console does and provides direct entry points to the
// Unscripted Live Sandbox (#/live) and Pre-Recorded Scenario Replays (#/replay),
// while keeping deep mathematical derivations and benchmarks in Tutorial/Docs.
import styles from "./LandingPage.module.css";

const WORKFLOW_MODES: ReadonlyArray<{
  title: string;
  tag: string;
  description: string;
  bullets: ReadonlyArray<string>;
  ctaLabel: string;
  href: string;
}> = [
  {
    title: "Live simulation sandbox",
    tag: "Interactive physics engine",
    description:
      "Configure your own constellation from scratch, launch the live Clohessy-Wiltshire orbital physics engine, and inject satellite failures at any moment to test autonomous recovery on unseen states.",
    bullets: [
      "Choose satellite count (2 to 50), orbit altitude, and formation radius",
      "Switch between Global Earth orbit view and close-up Formation array view",
      "Click any satellite in 3D to inject a live fault and watch Hungarian slot reassignment",
    ],
    ctaLabel: "Open live sandbox",
    href: "#/live",
  },
  {
    title: "Scenario replays",
    tag: "Pre-recorded missions",
    description:
      "Stream and scrub through six canonical multi-failure scenarios — including dual imager loss, leader re-election, and cascading 8-satellite faults — with full telemetry playback.",
    bullets: [
      "Instant playback of two_failure, firefly_swarm, cascading_n8, and leader_failure runs",
      "Scrub directly to any timestamp or state transition on the recovery timeline",
      "Inspect ground coverage, minimum separation, and per-satellite propellant usage",
    ],
    ctaLabel: "Browse scenario replays",
    href: "#/replay",
  },
];

export function LandingPage() {
  return (
    <main className={styles.page}>
      <div className={styles.inner}>
        {/* Clean Hero Banner */}
        <section className={styles.hero} aria-label="Product overview">
          <div className={styles.heroContent}>
            <p className={styles.kicker}>CubeSat constellation operations</p>
            <h1 className={styles.headline}>
              Autonomous fault recovery for CubeSat swarms
            </h1>
            <p className={styles.subline}>
              When a satellite fails in low Earth orbit, the constellation detects missed
              heartbeats, solves for optimal survivor-to-slot reassignment, and executes
              thruster burns to close the ground coverage gap while avoiding the coasting
              debris hazard.
            </p>
            <div className={styles.ctaRow}>
              <a className={`${styles.cta} ${styles.ctaPrimary}`} href="#/live">
                Open live sandbox
              </a>
              <a className={`${styles.cta} ${styles.ctaSecondary}`} href="#/replay">
                Browse scenario replays
              </a>
            </div>
          </div>
        </section>

        {/* Clear Separation: Live Sandbox vs Scenario Replays */}
        <section className={styles.modesSection} aria-label="Console modes">
          <h2 className={styles.sectionTitle}>Choose a workspace mode</h2>
          <div className={styles.modesGrid}>
            {WORKFLOW_MODES.map((m) => (
              <div key={m.title} className={styles.modeCard}>
                <div className={styles.modeHeader}>
                  <h3 className={styles.modeTitle}>{m.title}</h3>
                  <span className={styles.modeTag}>{m.tag}</span>
                </div>
                <p className={styles.modeDesc}>{m.description}</p>
                <ul className={styles.modeList}>
                  {m.bullets.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
                <div className={styles.modeAction}>
                  <a className={`${styles.cta} ${styles.ctaSecondary}`} href={m.href}>
                    {m.ctaLabel}
                  </a>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Footer navigation to Tutorial, FAQ, and Documentation */}
        <footer className={styles.footer}>
          <p className={styles.footerText}>
            Use the top bar at any time to switch between Simplified and Advanced telemetry
            views, or toggle between Dark and Light mode.
          </p>
          <div className={styles.linkRow}>
            <a className={styles.link} href="#/tutorial">
              Interactive tutorial
            </a>
            <a className={styles.link} href="#/faq">
              FAQ
            </a>
            <a className={styles.link} href="#/docs">
              Technical documentation
            </a>
          </div>
        </footer>
      </div>
    </main>
  );
}

export default LandingPage;
