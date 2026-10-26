// Tutorial — a guided, hands-on walkthrough of the console. Ordered steps
// because it IS a sequence (§13.2 bans numbering only on unordered content).
// Every button name in the copy is a real control label (SimulationControls,
// ReplayControls, ScenarioSelector, FailureInjectionPanel, RightPanel,
// EventLog); every number is a documented, measured value (IMPLEMENTATION_
// NOTES.md G4 re-tune, MASTER_PROMPT 3.5) — no invented mission facts
// (repo invariant 1). Color in the legend is state meaning only (§7.2/§13.1).
import PageShell from "../../pages/PageShell";
import styles from "./pages.module.css";

// §7.2 satellite states — the token reference, so the legend cannot drift
// from the tokens the scene itself reads (sceneColors.ts bridge).
const STATE_LEGEND = [
  { swatch: "var(--status-nominal)", label: "NOMINAL: healthy, holding slot" },
  { swatch: "var(--status-caution)", label: "RECONFIGURING: flying to a new slot" },
  { swatch: "var(--status-failed)", label: "FAILED: coasting ballistically" },
  { swatch: "var(--status-info)", label: "RECOVERED: stable after replanning" },
  { swatch: "var(--ink-faint)", label: "UNASSIGNED: no slot right now" },
  { swatch: "var(--status-leader)", label: "LEADER: gold outline" },
] as const;

// The exact shape the scenario modal validates (CustomScenarioModal
// EXAMPLE_SHAPE), filled with the committed 4-satellite pattern
// (data/scenarios/single_failure_n4.json: n_slots 4, radial_amp 8 km,
// a_max 0.1) — one DEAD imager instead of the leader.
const EXAMPLE_SCENARIO = `{
  "name": "my_first_failure",
  "seed": 42,
  "duration_s": 17028.0,
  "dt_s": 2.0,
  "chief": {"altitude_km": 500.0},
  "formation": {"n_slots": 4, "radial_amp_km": 8.0, "phase_offset_deg": 0.0},
  "a_max_mps2": 0.1,
  "gains": {"wn": 0.01, "zeta": 1.0},
  "sensor": {"fov_half_angle_deg": 1.5, "grid_step_km": 2.0, "grid_extent_km": 30.0},
  "roles": ["leader", "imager", "imager", "downlink"],
  "failures": [{"t": 1200.0, "sat_id": 1, "mode": "DEAD"}]
}`;

export default function TutorialPage() {
  return (
    <PageShell title="Tutorial">
      <p className={styles.lede}>
        A five-step walkthrough: read the scene, watch a recovery, then run one yourself. The
        console flies a hypothetical 6-satellite swarm on the real orbit of FIREFLY-1 (Pixxel)
        — the swarm does not exist; only the chief&apos;s orbit is real.
      </p>

      <section className={styles.section} aria-labelledby="tut-steps">
        <h2 className={styles.sectionTitle} id="tut-steps">
          The walkthrough
        </h2>
        <ol className={styles.steps}>
          <li className={styles.step}>
            <span className={styles.stepNum} aria-hidden="true">
              1
            </span>
            <div>
              <h3 className={styles.stepTitle}>What you are looking at</h3>
              <p className={styles.p}>
                The center view is the swarm in the LVLH frame: x is radial (away from Earth),
                y is along-track, z is cross-track. Satellites fly slots on a shared passive
                ellipse; the faint ghost markers are the target slots. Earth is stylized — not
                to scale. Color always means state, and the label is always written next to it:
              </p>
              <div className={styles.swatches}>
                {STATE_LEGEND.map((s) => (
                  <span key={s.label} className={styles.swatchRow}>
                    <span className={styles.swatch} style={{ background: s.swatch }} />
                    <span className={styles.swatchLabel}>{s.label}</span>
                  </span>
                ))}
              </div>
              <p className={`${styles.p} ${styles.muted}`}>
                A failed satellite never freezes — it coasts ballistically and stays an
                obstacle the survivors must respect.
              </p>
            </div>
          </li>

          <li className={styles.step}>
            <span className={styles.stepNum} aria-hidden="true">
              2
            </span>
            <div>
              <h3 className={styles.stepTitle}>Run your first failure — the two_failure replay</h3>
              <p className={styles.p}>
                Open the <a href="#/replay">Replay</a> page from the top navigation bar (or press{" "}
                <span className={styles.lit}>Switch to replay</span> on the Live page). Click{" "}
                <span className={styles.lit}>two_failure.jsonl</span> in the left{" "}
                <span className={styles.lit}>Committed replay runs</span> gallery. The log starts
                playing at 10×; use <span className={styles.lit}>Pause</span>,{" "}
                <span className={styles.lit}>Restart</span>, the speed select, or the scrub
                slider in the transport bar to move around.
              </p>
              <p className={styles.p}>
                What you should see, in order: the top-bar state chip runs the spine{" "}
                <span className={styles.lit}>NOMINAL</span> →{" "}
                <span className={styles.lit}>FAILURE_DETECTED</span> →{" "}
                <span className={styles.lit}>REPLANNING</span> →{" "}
                <span className={styles.lit}>RECONFIGURING</span> →{" "}
                <span className={styles.lit}>RECOVERED</span>, with each tick stamped in mono
                on the timeline. At t=1200 s the first imager turns red with a{" "}
                <span className={styles.lit}>FAILED</span> label and keeps coasting; the
                coverage readout dips and the chart drops. The survivors replan (Hungarian
                assignment) and fly amber to re-spaced slots — the two surviving imagers end up
                180° apart. A second imager dies mid-reconfiguration at t=1500 s and the swarm
                replans again.
              </p>
              <p className={`${styles.p} ${styles.muted}`}>
                Measured on the committed run (seed 42, log two_failure.jsonl): detection
                latency 4.00 s per failure, recovery complete at t≈3114 s, recovery ends +4.93
                coverage points above the no-recovery baseline. The full run is 17028 s — about
                28 minutes at 10× — so scrub or seek instead of waiting.
              </p>
            </div>
          </li>

          <li className={styles.step}>
            <span className={styles.stepNum} aria-hidden="true">
              3
            </span>
            <div>
              <h3 className={styles.stepTitle}>Read the charts</h3>
              <p className={styles.p}>
                The Telemetry panel shows the readout rows — Ground coverage, Minimum
                separation, Mission health score, Detection latency, Delta-v used — and five
                chart tabs: <span className={styles.lit}>Coverage</span>,{" "}
                <span className={styles.lit}>Deviation</span>,{" "}
                <span className={styles.lit}>Separation</span>,{" "}
                <span className={styles.lit}>Delta-v</span>,{" "}
                <span className={styles.lit}>Health</span>.
              </p>
              <ul className={styles.muted} style={{ margin: 0, paddingLeft: 20 }}>
                <li>
                  Coverage is the money chart: stable, sharp drop at each failure, recovery
                  after replanning. It plots the measured swarm curve — the spec&apos;s
                  three-curve comparison (nominal reference / no recovery / with recovery)
                  needs reference runs the live wire does not carry, and the chart says so
                  instead of inventing them.
                </li>
                <li>
                  Separation plots the smallest distance between any two satellites against
                  the session&apos;s first measured clearance as a labeled reference line.
                </li>
                <li>
                  Delta-v is the thrust each satellite has spent (m/s). In the committed
                  two_failure run the heaviest satellite spends 193.68 m/s — reconfiguration at
                  an 8 km formation scale is expensive, and the console shows it rather than
                  hiding it.
                </li>
                <li>
                  Health is one derived number: 0.5 × coverage + 0.3 × formation quality + 0.2
                  × safety, computed only from measured inputs.
                </li>
              </ul>
            </div>
          </li>

          <li className={styles.step}>
            <span className={styles.stepNum} aria-hidden="true">
              4
            </span>
            <div>
              <h3 className={styles.stepTitle}>Read the recovery log</h3>
              <p className={styles.p}>
                The Event log in the bottom panel is the traceability record: mono rows with
                mono sim-time stamps and a severity word per row, newest last (
                <span className={styles.lit}>Collapse log</span> keeps just the latest line).
                Every failure, state transition and assignment lands here as it happens —
                nothing is added off-stream.
              </p>
              <p className={styles.p}>
                Two more views tell the same story: the{" "}
                <span className={styles.lit}>Role reassignment</span> section under the chart
                tabs lists who moved to which slot, and clicking a satellite (in the scene or
                the Satellites list) opens its detail panel with a role history in plain words
                — took over a slot, failed, recovered.
              </p>
            </div>
          </li>

          <li className={styles.step}>
            <span className={styles.stepNum} aria-hidden="true">
              5
            </span>
            <div>
              <h3 className={styles.stepTitle}>
                Try live — run a preset or customize a 4-satellite scenario
              </h3>
              <p className={styles.p}>
                Open <a href="#/live">Live simulation</a>. In the{" "}
                <span className={styles.lit}>Live mission control</span> seat on the left, pick{" "}
                <span className={styles.lit}>single_failure_n4.json</span> in the{" "}
                <span className={styles.lit}>Scenario preset</span> dropdown (or expand{" "}
                <span className={styles.lit}>Configure swarm, failures &amp; physics</span> to
                edit satellite count, roles, and scheduled failures):
              </p>
              <pre className={styles.cmd}>{EXAMPLE_SCENARIO}</pre>
              <p className={styles.p}>
                Press <span className={styles.lit}>Run simulation</span> (seed defaults to 42).
                Once live frames arrive, use the{" "}
                <span className={styles.lit}>Failure injection</span> section right below the run
                controls: pick a satellite, leave Mode on{" "}
                <span className={styles.lit}>DEAD</span> — &quot;Goes silent and coasts.&quot; —
                and press <span className={styles.lit}>Inject failure</span>. The satellite goes
                red, the swarm declares <span className={styles.lit}>FAILURE_DETECTED</span>{" "}
                within 4 s (3 missed heartbeats at 2 s per tick), replans and recovers — the same
                spine you watched in replay, computed live.
              </p>
              <p className={`${styles.p} ${styles.muted}`}>
                The values above match the committed 4-satellite scenario
                data/scenarios/single_failure_n4.json; its failure kills sat_id 0 — the leader
                — which forces a leader re-election instead. The 0.1 m/s² engine limit is what
                the 8 km formation needs to complete its transfers (see Docs).
              </p>
            </div>
          </li>
        </ol>
      </section>

      <section className={styles.section} aria-labelledby="tut-next">
        <h2 className={styles.sectionTitle} id="tut-next">
          Where to go next
        </h2>
        <p className={styles.p}>
          The <a href="#/faq">FAQ</a> answers the questions judges ask most; the{" "}
          <a href="#/docs">Docs</a> page carries the architecture, the physics, the recovery
          policies and the exact reproduce commands.
        </p>
      </section>
    </PageShell>
  );
}
