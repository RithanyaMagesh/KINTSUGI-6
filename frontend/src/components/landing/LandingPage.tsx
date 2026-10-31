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
  { label: "SAT-1, leader", value: "Holding slot", tone: "green" },
  { label: "Failure detected", value: "in 4 s", tone: "ink" },
  { label: "Coverage restored", value: "27.0% vs 22.1%", tone: "gold" },
  { label: "Benchmarked", value: "75 recovery runs", tone: "ink" },
  { label: "Reruns", value: "Byte-identical", tone: "ink" },
];

const BEATS = [
  {
    step: "Failure detected",
    title: "One satellite breaks.",
    body:
      "SAT-3 goes silent. Three missed check-ins later, 4 seconds in, the swarm knows. The dead satellite keeps coasting, so it stays in every collision check.",
  },
  {
    step: "Moving to new slots",
    title: "The swarm repairs itself, with gold.",
    body:
      "The swarm works out the cheapest new slot for every survivor and hands the lost roles to someone else; each satellite then flies itself there. No ground command. Kintsugi repairs broken pottery with gold, and this swarm does the same.",
  },
];

// Original landing content, kept (round-2 workspace modes).
const WORKFLOW_MODES = [
  {
    title: "Live simulation sandbox",
    tag: "Interactive",
    description:
      "Build your own swarm, run it in a live orbital physics simulation, and break any satellite at any moment to test the self-repair.",
    bullets: [
      "Choose satellite count, orbit altitude, and formation radius",
      "Switch between a view of Earth and a close-up of the formation",
      "Click any satellite to fail it and watch the survivors move into new slots",
    ],
    ctaLabel: "Open live sandbox",
    href: "#/live",
  },
  {
    title: "Replays",
    tag: "Recorded runs",
    description:
      "Play back and scrub through recorded failure runs: two imagers lost, a lost leader replaced, failures one after another. Every number comes along.",
    bullets: [
      "Instant playback of saved runs",
      "Jump to any moment or step of the recovery",
      "Inspect ground coverage, closest approach and fuel spent per satellite",
    ],
    ctaLabel: "Browse replays",
    href: "#/replay",
  },
];

const STATS = [
  { value: "4 s", label: "Failure detection", source: "Two-failure demo, seed 42" },
  { value: "27.0%", label: "Coverage restored", source: "Versus 22.1% with no recovery, same run" },
  { value: "75", label: "Benchmarked recovery runs", source: "15 failure pairs, 5 recovery strategies each" },
  { value: "SHA-256", label: "Byte-identical reruns", source: "Same machine, same scenario and seed" },
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
          <p className={styles.tagline}>The swarm that heals itself, and repairs with gold.</p>
          <div className={styles.ctaRow}>
            <a className={styles.ctaPrimary} href="#/live">
              Launch live demo
            </a>
            <a className={styles.ctaGhost} href="#/replay">
              Watch a replay
            </a>
          </div>
          <button type="button" className={styles.scrollHint} onClick={() => goTo(1)}>
            <span className={styles.scrollLine} aria-hidden="true" />
            Scroll to watch a satellite break and the swarm repair itself
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
            <p className={styles.step}>Recovered</p>
            <h2 className={styles.beatTitle}>Every number comes from a recorded run.</h2>
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
                    {m.ctaLabel}
                  </a>
                </div>
              ))}
            </div>

            <footer className={styles.footer}>
              <a href="#/tutorial">Interactive tutorial</a>
              <a href="#/faq">FAQ</a>
              <a href="#/docs">Technical documentation</a>
              <span className={styles.footerNote}>Simplified orbit model, simulation only. Limits are in the docs.</span>
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
