// Landing page — route #/ (Router slot 'landing'). The page that sells the
// console to judges in one screen: the recovery story, then the receipts.
//
// Copy sources (no invented mission facts, no displayed numbers at all — the
// unmeasured rule is satisfied by construction, repo invariant 1):
//   - FRONTEND_SPEC §2 (vision), §4 (recovery narrative)
//   - MASTER_PROMPT §2/§3.1-3.5 (physics, allocation, control, state machine)
//   - IMPLEMENTATION_NOTES "hypothetical swarm on a real chief orbit"
//     (FIREFLY-1 framing) and the P4 predictor section (LightGBM status)
//   - docs/FRONTEND_SPEC Appendix C via onboarding/helpContent.ts wording
//
// Exports: named `LandingPage` (Router slot export) plus a default export of
// the same function, so either import style works.
import { STATE_SPINE } from "../../types/satellite";
import styles from "./LandingPage.module.css";

/** The six formation slots on the 2:1 CW ellipse (along-track amplitude is
 * 2x radial — MASTER_PROMPT §3.1), phase-spaced 60 deg, drawn in SVG user
 * units around Earth at (320, 210). Index 3 (theta 180) is the failed seat. */
const SLOT_XY: ReadonlyArray<readonly [number, number]> = [
  [530, 210],
  [425, 119],
  [215, 119],
  [110, 210],
  [215, 301],
  [425, 301],
];
const DEAD = 3;
/** Survivors that cover the dead seat, and the reassigned target slots they
 * are arrowed to (re-phased into the gap — replanning picks a k-slot
 * formation, MASTER_PROMPT §3.3 step 1). */
const REASSIGN_FROM = [2, 4] as const;
const TARGET_XY: ReadonlyArray<readonly [number, number]> = [
  [138, 158],
  [138, 263],
];

/** Arrow geometry derived once at module scope (pure, deterministic): a line
 * that clears the survivor square and the target circle, plus a filled
 * triangle head oriented along the line. */
const ARROWS = REASSIGN_FROM.map((from, i) => {
  const [sx, sy] = SLOT_XY[from];
  const [tx, ty] = TARGET_XY[i];
  const dx = tx - sx;
  const dy = ty - sy;
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  return {
    x1: sx + ux * 10,
    y1: sy + uy * 10,
    x2: tx - ux * 13,
    y2: ty - uy * 13,
    hx: tx - ux * 9,
    hy: ty - uy * 9,
    angle: (Math.atan2(dy, dx) * 180) / Math.PI,
  };
});

/** State literal -> token color class. The chain strings come from the shared
 * STATE_SPINE so copy and the console's timeline spine cannot drift.
 * MissionState also carries DEGRADED (wire value, not in the spine); the
 * fallback covers it if the spine ever grows. */
const STATE_CLASS: Partial<Record<(typeof STATE_SPINE)[number], string>> = {
  NOMINAL: styles.stateNominal,
  FAILURE_DETECTED: styles.stateFailed,
  REPLANNING: styles.stateCaution,
  RECONFIGURING: styles.stateCaution,
  RECOVERED: styles.stateInfo,
};

const PILLARS: ReadonlyArray<{ name: string; body: string }> = [
  {
    name: "Physics with receipts",
    body:
      "The sim runs the same Clohessy-Wiltshire core that writes the " +
      "committed run logs. Every number on screen is traceable to a " +
      "committed log; anything the wire does not carry renders as " +
      "unmeasured.",
  },
  {
    name: "Self-healing",
    body:
      "A satellite that stops reporting heartbeats is declared failed, and " +
      "a Hungarian assignment reassigns the survivors across formation " +
      "slots. PD-controlled burns fly the swarm back into a stable " +
      "formation while the failed satellite coasts ballistically as a " +
      "collision hazard.",
  },
  {
    name: "AI early warning",
    body:
      "A LightGBM predictor scores failure risk and can trigger " +
      "reassignment earlier than the heartbeat path alone. It is trained " +
      "on synthetic degradation; the caveats are documented in the Docs " +
      "page.",
  },
];

export function LandingPage() {
  return (
    <main className={styles.page}>
      <div className={styles.inner}>
        {/* 1 — Hero: the recovery story plus a schematic of it. */}
        <section className={styles.hero}>
          <div>
            <h1 className={styles.headline}>A satellite dies. The swarm heals.</h1>
            <p className={styles.subline}>
              This is a hypothetical 6-satellite swarm flying the real orbit
              of FIREFLY-1. Motion is Clohessy-Wiltshire relative dynamics in
              the LVLH frame.
            </p>
            <div className={styles.ctaRow}>
              <a className={`${styles.cta} ${styles.ctaPrimary}`} href="#/live">
                Start live simulation
              </a>
              <a
                className={`${styles.cta} ${styles.ctaSecondary}`}
                href="#/replay"
              >
                Watch a replay
              </a>
              <a
                className={`${styles.cta} ${styles.ctaSecondary}`}
                href="#/tutorial"
              >
                Learn the console
              </a>
            </div>
            <div className={styles.linkRow}>
              <a className={styles.link} href="#/faq">
                FAQ
              </a>
              <a className={styles.link} href="#/docs">
                Docs
              </a>
            </div>
          </div>
          <figure className={styles.figure}>
            <svg
              className={styles.figureSvg}
              viewBox="80 84 480 240"
              role="img"
              aria-label="Schematic of the recovery: on the formation ellipse around Earth, one satellite has failed and two survivors are reassigned to the vacated slots"
            >
              {/* Formation orbit — the 2:1 CW ellipse. */}
              <ellipse
                className={styles.orbit}
                cx={320}
                cy={210}
                rx={210}
                ry={105}
              />
              {/* Earth disc with a faint graticule. */}
              <circle className={styles.earth} cx={320} cy={210} r={64} />
              <ellipse className={styles.grat} cx={320} cy={210} rx={64} ry={24} />
              <ellipse className={styles.grat} cx={320} cy={210} rx={24} ry={64} />
              <text className={styles.svgLabel} x={320} y={292} textAnchor="middle">
                chief: FIREFLY-1
              </text>
              {/* The dead seat: empty slot outline, red X, mono label. */}
              <circle className={styles.deadSlot} cx={110} cy={210} r={11} />
              <line className={styles.deadX} x1={103} y1={203} x2={117} y2={217} />
              <line className={styles.deadX} x1={103} y1={217} x2={117} y2={203} />
              <text className={styles.svgLabelFail} x={110} y={236} textAnchor="middle">
                failed
              </text>
              {/* Survivors on their slots. */}
              {SLOT_XY.map(([x, y], i) =>
                i === DEAD ? null : (
                  <rect
                    key={i}
                    className={styles.sat}
                    x={x - 5.5}
                    y={y - 5.5}
                    width={11}
                    height={11}
                  />
                ),
              )}
              {/* Reassigned target slots + arrows from two survivors. */}
              {TARGET_XY.map(([x, y], i) => (
                <circle
                  key={i}
                  className={styles.targetSlot}
                  cx={x}
                  cy={y}
                  r={9}
                />
              ))}
              {ARROWS.map((a, i) => (
                <g key={i}>
                  <line
                    className={styles.arrow}
                    x1={a.x1}
                    y1={a.y1}
                    x2={a.x2}
                    y2={a.y2}
                  />
                  <polygon
                    className={styles.arrowHead}
                    points="0,0 -10,4 -10,-4"
                    transform={`translate(${a.hx} ${a.hy}) rotate(${a.angle})`}
                  />
                </g>
              ))}
            </svg>
          </figure>
        </section>

        {/* 2 — The three pillars, readout-row style (no card grid). */}
        <section className={styles.section} aria-label="What the console proves">
          <h2 className={styles.sectionTitle}>What the console proves</h2>
          <div>
            {PILLARS.map((p) => (
              <div className={styles.pillar} key={p.name}>
                <h3 className={styles.pillarName}>{p.name}</h3>
                <p className={styles.pillarBody}>{p.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 4 — How recovery works: the state machine, in mono + state colors. */}
        <section className={styles.strip} aria-label="How recovery works">
          <h2 className={styles.sectionTitle}>How recovery works</h2>
          <p className={styles.chain}>
            {STATE_SPINE.map((state, i) => (
              <span key={state}>
                {i > 0 && <span className={styles.chainSep}> → </span>}
                <span className={STATE_CLASS[state] ?? styles.stateInfo}>{state}</span>
              </span>
            ))}
          </p>
          <p className={styles.stripNote}>
            The mission state the console tracks from first missed heartbeat to
            a stable formation. Every transition is logged with sim time.
          </p>
        </section>

        {/* 5 — Footer: the honesty line. */}
        <footer className={styles.footer}>
          <p className={styles.footerText}>
            A simulation with receipts: the swarm is hypothetical, the
            limitations are documented, and no displayed number exists without
            a committed run log behind it.
          </p>
          <a className={styles.link} href="#/docs">
            Read the docs
          </a>
        </footer>
      </div>
    </main>
  );
}

export default LandingPage;
