// Landing page — route #/ (Router slot 'landing').
// KINTSUGI-6: an animated 3D stage (landingScene.ts) — CubeSats orbiting a 3D
// wordmark, then, on scroll, one satellite breaks and the survivors re-link in
// gold ("repaired with gold"). Copy sections scroll over the fixed canvas and
// keep the original landing content (workspace modes + Tutorial/FAQ/Docs).
// The animation is an illustration; every NUMBER on the page is a measured
// value with its source named next to it (repo invariant 1).
import { useEffect, useRef, useState } from "react";
import { createLandingScene, type TelemetryCard } from "./landingScene";
import styles from "./LandingPage.module.css";

// Floating hero cards — measured values only (README.md / GATES.md).
const CARDS: TelemetryCard[] = [
  { label: "SAT-1 · leader", value: "holding slot", tone: "green" },
  { label: "Failure detected", value: "in 4 s", tone: "ink" },
  { label: "Coverage restored", value: "27.0% vs 22.1%", tone: "gold" },
  { label: "Benchmarked", value: "75 recovery runs", tone: "ink" },
  { label: "Reruns", value: "byte-identical", tone: "ink" },
];

const BEATS = [
  {
    step: "01 · Failure detected",
    title: "One satellite breaks.",
    body:
      "SAT-3 goes silent. Three missed heartbeats later — 4 seconds — the swarm knows. The dead satellite keeps coasting, so it stays in every collision check.",
  },
  {
    step: "02 · Reconfiguring → recovered",
    title: "The swarm repairs itself — with gold.",
    body:
      "A Hungarian solver re-assigns the survivors to new slots and re-elects lost roles; thrust-limited control flies them there. No ground command. Kintsugi repairs broken pottery with gold — this swarm does the same.",
  },
];

// Original landing content, kept (round-2 workspace modes).
const WORKFLOW_MODES = [
  {
    title: "Live simulation sandbox",
    tag: "Interactive physics engine",
    description:
      "Configure your own constellation, launch the live Clohessy-Wiltshire orbital physics engine, and inject satellite failures at any moment to test autonomous recovery.",
    bullets: [
      "Choose satellite count, orbit altitude, and formation radius",
      "Switch between Global Earth orbit and close-up Formation array views",
      "Click any satellite in 3D to inject a live fault and watch Hungarian slot reassignment",
    ],
    ctaLabel: "Open live sandbox",
    href: "#/live",
  },
  {
    title: "Scenario replays",
    tag: "Pre-recorded missions",
    description:
      "Stream and scrub through canonical multi-failure scenarios — dual imager loss, leader re-election, cascading faults — with full telemetry playback.",
    bullets: [
      "Instant playback of committed scenario runs",
      "Scrub to any timestamp or state transition on the recovery timeline",
      "Inspect ground coverage, minimum separation, and per-satellite propellant use",
    ],
    ctaLabel: "Browse scenario replays",
    href: "#/replay",
  },
];

const STATS = [
  { value: "4 s", label: "Failure detection", source: "3 missed heartbeats · two_failure, seed 42" },
  { value: "27.0%", label: "Coverage restored", source: "vs 22.1% with no recovery · same run" },
  { value: "75", label: "Benchmarked recovery runs", source: "15 failure pairs × 5 policies" },
  { value: "SHA-256", label: "Byte-identical reruns", source: "same machine, same scenario + seed" },
];

const SECTION_COUNT = BEATS.length + 2;

export function LandingPage() {
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<Array<HTMLElement | null>>([]);
  const [active, setActive] = useState(0);

  useEffect(() => {
    const root = rootRef.current;
    const canvas = canvasRef.current;
    const scroller = scrollerRef.current;
    if (!root || !canvas || !scroller) return;

    let scene: ReturnType<typeof createLandingScene> | null = null;
    try {
      scene = createLandingScene(canvas, root, CARDS);
    } catch {
      scene = null; // no WebGL: the copy still reads fine on the black stage
    }

    // Story progress is SECTION-based, not raw scroll distance: section i's
    // top reaching the top of the viewport maps to p = i / (N - 1), so each
    // 3D beat plays on its own copy section however tall the proof panel is.
    const onScroll = () => {
      const tops = sectionRefs.current.map((el) => (el ? el.offsetTop : 0));
      const y = scroller.scrollTop;
      const last = SECTION_COUNT - 1;
      let p = 1;
      for (let i = 0; i < last; i += 1) {
        const span = Math.max(1, tops[i + 1] - tops[i]);
        if (y < tops[i + 1]) {
          p = (i + Math.max(0, (y - tops[i]) / span)) / last;
          break;
        }
      }
      scene?.setProgress(p);
      setActive(Math.min(last, Math.round(p * last)));
    };
    const onMove = (e: PointerEvent) => {
      const r = root.getBoundingClientRect();
      scene?.setPointer(((e.clientX - r.left) / r.width) * 2 - 1, ((e.clientY - r.top) / r.height) * 2 - 1);
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    root.addEventListener("pointermove", onMove);
    onScroll();

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          (entry.target as HTMLElement).dataset.visible = entry.isIntersecting ? "true" : "false";
        }
      },
      { root: scroller, threshold: 0.3 },
    );
    for (const el of sectionRefs.current) if (el) io.observe(el);

    return () => {
      scroller.removeEventListener("scroll", onScroll);
      root.removeEventListener("pointermove", onMove);
      io.disconnect();
      scene?.dispose();
    };
  }, []);

  const goTo = (i: number) => {
    sectionRefs.current[i]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const setSection = (i: number) => (el: HTMLElement | null) => {
    sectionRefs.current[i] = el;
  };

  return (
    <div ref={rootRef} className={styles.root}>
      <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />
      <div className={styles.scrim} data-story={active > 0 ? "true" : "false"} aria-hidden="true" />

      <div ref={scrollerRef} className={styles.scroller}>
        {/* Hero — the wordmark itself is drawn in 3D; the h1 is for screen readers */}
        <section ref={setSection(0)} className={`${styles.section} ${styles.hero}`} data-visible="true">
          <p className={styles.kicker}>Autonomous CubeSat swarm recovery</p>
          <h1 className={styles.srOnly}>KINTSUGI-6</h1>
          <div className={styles.wordmarkSpace} aria-hidden="true" />
          <p className={styles.tagline}>The swarm that heals itself — and repairs with gold.</p>
          <div className={styles.ctaRow}>
            <a className={styles.ctaPrimary} href="#/live">
              Launch live demo <span aria-hidden="true">→</span>
            </a>
            <a className={styles.ctaGhost} href="#/replay">
              Watch a replay
            </a>
          </div>
          <button type="button" className={styles.scrollHint} onClick={() => goTo(1)}>
            <span className={styles.scrollLine} aria-hidden="true" />
            Scroll — watch a satellite break and the swarm repair
          </button>
        </section>

        {BEATS.map((beat, i) => (
          <section key={beat.step} ref={setSection(i + 1)} className={styles.section}>
            <div className={styles.copy}>
              <p className={styles.step}>{beat.step}</p>
              <h2 className={styles.beatTitle}>{beat.title}</h2>
              <p className={styles.lede}>{beat.body}</p>
            </div>
          </section>
        ))}

        <section ref={setSection(SECTION_COUNT - 1)} className={`${styles.section} ${styles.proof}`}>
          <div className={styles.proofPanel}>
            <p className={styles.step}>03 · Recovered</p>
            <h2 className={styles.beatTitle}>Every number has a command behind it.</h2>
            <dl className={styles.stats}>
              {STATS.map((s) => (
                <div key={s.label} className={styles.stat}>
                  <dt className={styles.statLabel}>{s.label}</dt>
                  <dd className={styles.statValue}>{s.value}</dd>
                  <dd className={styles.statSource}>{s.source}</dd>
                </div>
              ))}
            </dl>

            <div className={styles.modes}>
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
                  <a className={styles.modeLink} href={m.href}>
                    {m.ctaLabel} <span aria-hidden="true">→</span>
                  </a>
                </div>
              ))}
            </div>

            <footer className={styles.footer}>
              <a href="#/tutorial">Interactive tutorial</a>
              <a href="#/faq">FAQ</a>
              <a href="#/docs">Technical documentation</a>
              <span className={styles.footerNote}>Linearized CW dynamics, simulation only — limits in the docs.</span>
            </footer>
          </div>
        </section>
      </div>

      <nav className={styles.dots} aria-label="Story sections">
        {Array.from({ length: SECTION_COUNT }, (_, i) => (
          <button
            key={i}
            type="button"
            className={styles.dot}
            data-active={active === i ? "true" : "false"}
            aria-label={`Go to section ${i + 1}`}
            aria-current={active === i ? "step" : undefined}
            onClick={() => goTo(i)}
          />
        ))}
      </nav>
    </div>
  );
}

export default LandingPage;
