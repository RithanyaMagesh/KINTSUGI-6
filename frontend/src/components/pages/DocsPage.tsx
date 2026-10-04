// Docs — the reference page: architecture, physics, wire contract, recovery
// policies, AI model status, reproducibility. Reference tone; every claim
// names its source (docs/MASTER_PROMPT.md, docs/FRONTEND_SPEC.md, docs/
// IMPLEMENTATION_NOTES.md, docs/ENDGAME_PLAN.md §7, GATES.md decisions,
// AGENTS.md commands). Commands and state literals render mono (§13.2);
// definition-list rows, not cards (§13.3). Route names and file names are
// taken from the tree (cubesat/api.py routes verified 2026-10-04).
import PageShell from "../../pages/PageShell";
import styles from "./pages.module.css";

// The serve/run commands of record — AGENTS.md "Commands" section, verbatim.
const COMMANDS = `uv sync --locked
uv run ruff check .
uv run pytest -q
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
uv run uvicorn cubesat.api:app --port 8000`;

// The sealed pipeline's repro of record (GATES.md, P4 Gate 0).
const PREDICTOR_COMMAND = `uv run python files/predictor_pipeline.py run --out out2`;

export default function DocsPage() {
  return (
    <PageShell title="Docs">
      <p className={styles.lede}>
        The system behind the console, in reference form. Sources: docs/MASTER_PROMPT.md,
        docs/FRONTEND_SPEC.md, docs/IMPLEMENTATION_NOTES.md, docs/ENDGAME_PLAN.md, and the
        GATES.md decision ledger.
      </p>

      <section className={styles.section} aria-labelledby="docs-arch">
        <h2 className={styles.sectionTitle} id="docs-arch">
          Architecture
        </h2>
        <p className={styles.p}>
          One pipeline, one data format end to end: a scenario JSON drives the simulation
          core, the core writes a versioned JSONL log, and the console consumes the same
          frames live over a WebSocket or frozen from a log file.
        </p>
        <div className={styles.dl}>
          <div className={styles.dlRow}>
            <span className={styles.dt}>Scenario</span>
            <p className={styles.dd}>
              <span className={styles.lit}>data/scenarios/*.json</span> — pydantic-validated:
              chief orbit, formation slots, roles, failure schedule, controller gains,
              allocation settings. The console&apos;s{" "}
              <span className={styles.lit}>Add your own scenario…</span> uploads here (POST{" "}
              <span className={styles.lit}>/scenarios/upload</span>, server-side validation).
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>Sim core</span>
            <p className={styles.dd}>
              <span className={styles.lit}>cubesat/sim.py</span> — a pure step function
              (deterministic; the replanner runs between steps). Failure schedule, heartbeat
              detection, the mission state machine, and the two-step allocation live here with{" "}
              <span className={styles.lit}>cubesat/hcw.py</span>,{" "}
              <span className={styles.lit}>cubesat/pd.py</span> and{" "}
              <span className={styles.lit}>cubesat/allocate.py</span>.
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>Log</span>
            <p className={styles.dd}>
              One JSONL line per tick:{" "}
              <span className={styles.lit}>
                {"{v, t, state, sats[{id, role, status, r, v, dv_used}], coverage, min_sep}"}
              </span>{" "}
              plus INIT and SUMMARY lines. The schema is the single source both live and replay
              read — the frontend defines no second format.
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>Wire</span>
            <p className={styles.dd}>
              One FastAPI service (<span className={styles.lit}>cubesat/api.py</span>) serves
              REST control, the <span className={styles.lit}>/ws/state</span> stream, and the
              built console as static files. Replay playback is backend-owned and streams over
              the same socket.
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>Console</span>
            <p className={styles.dd}>
              React 18 + TypeScript + Zustand + Recharts + plain Three.js. One deserializer (
              <span className={styles.lit}>src/api/deserializer.ts</span>) serves live WS and
              replay alike; every displayed value traces to it, otherwise the UI renders{" "}
              <span className={styles.lit}>unmeasured</span>.
            </p>
          </div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="docs-physics">
        <h2 className={styles.sectionTitle} id="docs-physics">
          Physics
        </h2>
        <p className={styles.p}>
          Relative motion uses the Clohessy–Wiltshire equations in the LVLH frame — x radial,
          y along-track, z cross-track — with the chief at the origin and mean motion
          n = √(μ/a³). At ~500 km, n ≈ 1.107e-3 rad/s and one orbit is ≈ 94.6 min.
        </p>
        <pre className={styles.cmd}>{`x'' - 3n²x - 2n·y' = ax
y'' + 2n·x'        = ay
z'' + n²z          = az`}</pre>
        <p className={styles.p}>
          Formation slots sit on passive (drift-free) relative orbits — the drift-free
          condition is <span className={styles.lit}>vy0 = −2n·x0</span>, which makes the
          in-plane motion a closed 2:1 ellipse. Reconfiguration is PD control on full state
          error against the moving slot, with thrust saturated at{" "}
          <span className={styles.lit}>a_max</span>.
        </p>
        <p className={styles.p}>
          Stated plainly, the two known limitations: the CW linearization error grows with
          separation — measured at 3.1 m over 3 orbits for a 1 km ellipse but 2984.5 m at the
          11 km formation scale — and the engine limit is mission-shaping. The committed demo
          scenario carries <span className={styles.lit}>a_max</span> = 0.1 m/s² because the
          measured default 0.01 m/s² cannot complete the 8 km-scale transfers at all (CW
          dynamics cap what a saturated controller can chase); the resulting delta-v bill, up
          to 193.68 m/s per satellite, is shown as measured rather than tuned away.
        </p>
        <p className={`${styles.p} ${styles.muted}`}>
          Verification behind these numbers: STM vs numerical integration, ellipse closure,
          CW-vs-Kepler cross-checks, saturation and determinism tests — the commands are in
          docs/IMPLEMENTATION_NOTES.md.
        </p>
      </section>

      <section className={styles.section} aria-labelledby="docs-wire">
        <h2 className={styles.sectionTitle} id="docs-wire">
          Wire contract
        </h2>
        <div className={styles.dl}>
          <div className={styles.dlRow}>
            <span className={styles.dt}>WebSocket</span>
            <p className={styles.dd}>
              <span className={styles.lit}>/ws/state</span> streams{" "}
              <span className={styles.lit}>sim_state</span> (sim time, mission state,
              per-satellite id/role/status/position/velocity/delta-v, coverage, minimum
              separation), <span className={styles.lit}>event</span> (sim time, severity
              level, message), and <span className={styles.lit}>role_reassignment</span>{" "}
              records. The client pings every 30 s so free-tier hosting stays awake. Units are
              SI at this boundary; conversion happens only at the display edge.
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>REST</span>
            <p className={styles.dd}>
              <span className={styles.lit}>GET /health</span>,{" "}
              <span className={styles.lit}>GET /scenarios</span>,{" "}
              <span className={styles.lit}>POST /scenarios/upload</span>,{" "}
              <span className={styles.lit}>POST /simulation/start|pause|resume|speed|reset</span>
              , <span className={styles.lit}>POST /failure/inject</span>,{" "}
              <span className={styles.lit}>GET /replay/files</span>,{" "}
              <span className={styles.lit}>{"GET /replay/file/{filename}"}</span>,{" "}
              <span className={styles.lit}>POST /replay/load|pause|resume|seek|speed|stop</span>{" "}
              (routes as implemented in cubesat/api.py).
            </p>
          </div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="docs-policies">
        <h2 className={styles.sectionTitle} id="docs-policies">
          Recovery policies
        </h2>
        <p className={styles.p}>
          The engine&apos;s default is the two-step allocation: choose the survivors&apos;
          formation (feasible in separation and delta-v, maximizing coverage), then assign
          survivors to slots by Hungarian assignment on the cost matrix —{" "}
          <span className={styles.lit}>cubesat/allocate.py</span>.
        </p>
        <p className={styles.p}>
          Four benchmark policies exist for comparison — the measurement benchmark runs all 15
          possible two-failure pairs of the 6-satellite formation against each of them (
          <span className={styles.lit}>cubesat/benchmark.py</span>, policy order{" "}
          <span className={styles.lit}>do_nothing, even_split, greedy, hungarian,
          hungarian_keepout</span>):
        </p>
        <div className={styles.dl}>
          <div className={styles.dlRow}>
            <span className={styles.dt}>do_nothing</span>
            <p className={styles.dd}>
              Detection only — survivors hold their original slots. The baseline every
              recovery is measured against.
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>even_split</span>
            <p className={styles.dd}>
              Even redistribution — the naive rule from the RL-retasking literature,
              re-implemented as a benchmark and adapted to formation slots (
              <span className={styles.lit}>cubesat/benchmark_policies.py</span>). Cited, not
              claimed as ours.
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>greedy</span>
            <p className={styles.dd}>
              Nearest-seat fallback — survivors in order take their cheapest available slot;
              the engine&apos;s graceful-degradation toggle.
            </p>
          </div>
          <div className={styles.dlRow}>
            <span className={styles.dt}>hungarian_keepout</span>
            <p className={styles.dd}>
              The shipped Hungarian path plus one extra cost term: a per-seat keep-out penalty
              pushing assignments away from coasting dead satellites (
              <span className={styles.lit}>cubesat/benchmark_policies.py</span>).
            </p>
          </div>
        </div>
        <p className={styles.p}>
          What the comparison showed on the committed demo scenario (seed 42): no-recovery
          coverage drops 15.91 points after the two failures; recovery ends +4.93 points above
          the no-recovery baseline, with detection latency 4 s, recovery complete at
          t = 3114 s, worst separation 3095.1 m (threshold 2000 m), and delta-v up to 193.68
          m/s on the hardest-working satellite.
        </p>
      </section>

      <section className={styles.section} aria-labelledby="docs-ai">
        <h2 className={styles.sectionTitle} id="docs-ai">
          AI model status
        </h2>
        <p className={styles.p}>
          A LightGBM failure-risk model was trained as a proof of concept on synthetic
          degradation telemetry (bus voltage, state of charge, thrust duty, heartbeat latency
          and jitter) generated around the simulator&apos;s own deterministic failure
          schedule. The pipeline and the model artifact are sealed and hash-pinned —{" "}
          <span className={styles.lit}>files/predictor_pipeline.py</span> (source sha256
          self-enforced by <span className={styles.lit}>out2/test_manifest.json</span>) and{" "}
          <span className={styles.lit}>models/predictor.txt</span> (
          <span className={styles.lit}>models/predictor_manifest.json</span>, LightGBM 4.7.0).
          CI verifies the hashes; it never retrains.
        </p>
        <p className={styles.p}>
          Offline, on the held-out test runs, the model detects every slow-failure precursor
          and flags them earlier than the EWMA/CUSUM baselines — a paired median lead gain of
          260.0 s, 31 of 31 paired events earlier (sign-test p ≈ 9.3e-10) — but the caveats
          are part of the result: it does not generalize to unseen failure families (family
          holdout 0/15), and sudden death is unpredictable by construction (1 of 16 events; a
          satellite that dies without warning has no precursor — the reactive 4 s detection is
          the safety net).
        </p>
        <p className={styles.p}>
          It is not wired into the swarm. Before any integration, a pre-registered kill switch
          ran an oracle sweep — an idealized trigger that knows each failure time exactly,
          sweeping warning lead times — asking whether warning is worth anything to the
          mission. Maximum measured gain: 0.0235 percentage points of critical-seat health,
          far below the pre-declared 0.5 point threshold, so the verdict was CUT: the demo
          ships reactive-only, plus the measured value-of-warning curve. The Suspect
          annotation in the satellite detail is a rule-based drift detector, not this model.
        </p>
        <p className={`${styles.p} ${styles.muted}`}>
          Reproduce the sealed results (the outputs must stay byte-identical afterward):
        </p>
        <pre className={styles.cmd}>{PREDICTOR_COMMAND}</pre>
      </section>

      <section className={styles.section} aria-labelledby="docs-repro">
        <h2 className={styles.sectionTitle} id="docs-repro">
          Reproducibility
        </h2>
        <p className={styles.p}>
          Determinism is a tested invariant: no wall clock, no unseeded randomness, no
          order-dependent iteration anywhere on the log path. The same scenario and seed
          produce a byte-identical JSONL log — checked against a committed golden hash — so a
          replay is frozen evidence, and any run anyone reproduces matches the run that
          produced every number on this page.
        </p>
        <p className={styles.p}>The commands of record:</p>
        <pre className={styles.cmd}>{COMMANDS}</pre>
        <p className={`${styles.p} ${styles.muted}`}>
          The fourth command writes the demo log the console replays; the fifth serves the
          API, the WebSocket and the console on port 8000.
        </p>
      </section>
    </PageShell>
  );
}
