# Judge prep — read this the night before

Written 2026-10-31 for the person presenting this project. Everything here is either a number
from a committed log/report (with the command that produced it) or a check run first-hand this
session. Sources: `GATES.md` (the ledger), `docs/HANDOFF.md`, `audit_out/AUDIT.md`,
`docs/ENDGAME_PLAN.md`, `README.md`, the committed artifacts in `data/eval/`, and the four
analyst inputs from this session.

---

## Demo-readiness note (read first)

**No gate has failed.** G0–G4 are PASS and tagged, G5 (backend + frontend) is PASS but untagged
(tagging was left to the owner), G6 (deploy) and G7 (README/demo polish) are still `todo`
(GATES.md gate table). The G5 row honestly records two missed performance targets: a live run
took 2.92–3.24 s to compute at start on the 2026-09-30 Windows machine (target was ~2 s; re-timed on macOS arm64 M3, 2026-10-31: 1.74 s for two_failure, 2.07 s live_6sat, 5.35 s live_12sat, 16.1 s live_24sat — machine-dependent, GATES.md timing row), and failure injection stalled ~3 s while
it recomputes (Windows 2026-09-30; not re-timed: unmeasured). Both are one-time pauses, not failures — say so if asked.

**Repo health, re-verified 2026-10-31 (evidence re-measure pass, macOS arm64):**

- `uv run ruff check .` → **All checks passed!** (exit 0)
- Test suite: `uv run python -m pytest --collect-only -q` → **224 tests collected** (3 slow);
  `uv run python -m pytest -m "not slow" -p no:cacheprovider` → all **221 non-slow tests pass**
  (the 3 slow physics tests were not run in this pass). The earlier "185 tests" figure is
  superseded. Use `uv run python -m pytest`, not `uv run pytest` — the latter
  is spawn-blocked on the Windows machine (HANDOFF.md §5).
- The canonical demo command
  `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl`
  → printed `coverage_mean_last_orbit = 0.269797`. The committed log `data/logs/two_failure.jsonl`
  has SHA-256 `450d5371…` (written on Windows); on macOS arm64 the same command gives
  `cb7e2c2af27659d96397ac6224a92f544328b5f0640284386dce26d51d9f1989`, identical across two
  consecutive runs (same-machine determinism) but not equal to the Windows file — float last
  bits differ across platforms, so the cross-platform pin is `cubesat.canon.canonical_log_hash`
  (GATES.md, 2026-10-31 decisions). Say "byte-identical on one machine", not "identical everywhere".
- `frontend/dist/` exists on this machine (built 2026-10-30), so `uvicorn` will serve the 3D
  console locally. **But dist is gitignored** — it exists only on this machine.

**The three real risks for the demo:** (1) nothing is deployed and the multi-stage Dockerfile
has never been built (Docker daemon down at every check, GATES.md open risks) — the demo runs
on localhost on this one machine; (2) the README's quickstart never mentions
`npm ci && npm run build`, so a fresh clone serves a JSON placeholder instead of the console —
run the demo from this machine; (3) the end-to-end live demo (uvicorn + browser + injection)
was last verified in G5/round-2 sessions, not this session — **rehearse it tonight** (script in
§7). Pieces verified this session: tests green, log regenerates byte-identical, dist present.

---

## 1. What is this — the elevator pitch

Six CubeSats fly a formation around Earth, taking pictures of the ground. When satellites fail,
the survivors detect the loss and heal the mission themselves: they re-elect the leader,
re-assign every survivor to a new slot in the formation with the Hungarian algorithm, and fly
there on real orbital mechanics. Ground coverage comes back — a measured part of it.

Three things make this more than a demo:

1. **Everything is deterministic.** Same scenario + seed → a byte-identical log. Pinned by
   SHA-256 tests. That one property is why the live stream and the replay show the same frames,
   and why you can inject a failure mid-run and the sim recomputes the future with an
   unchanged past.
2. **Every number has a command behind it.** No number appears anywhere without a committed
   log and the command that produced it. Unmeasured things say "unmeasured" — in the UI too.
3. **We publish our negative results.** Our headline finding is that recovery *loses* coverage
   on average (−2.13 pts over 15 pairs) and wins (+4.93 pts) only on the three pairs where both
   dead satellites are imagers. We built an AI
   failure-predictor and pre-registered a pass/fail threshold before measuring; the 2026-10-04
   sweep cut it by that rule, and the later gradual-EPS sweep (§2.6) cleared the threshold —
   both verdicts are in the repo; the control loop stays reactive-only pending a user decision.

The one-sentence version: **a deterministic, fully-measured simulator of a self-healing CubeSat
swarm that streams its missions live into a 3D operator console — honest enough to report
where self-healing doesn't help.**

---

## 2. How it works — plain-language walkthrough

### 2.1 The physics core

Satellites move on the Hill–Clohessy–Wiltshire (HCW) equations — the standard linearized
orbital mechanics for satellites flying near each other. We hand-coded the exact 6×6
state-transition matrix (`cubesat/hcw.py:28-54`) and verified it against independent numerical
integration to ~1e-12 relative error, and against full two-body Keplerian propagation (the
residual at our 8 km formation scale: 1578.5 m over 3 orbits — disclosed, not hidden).

Every formation slot is a point on one shared "passive ellipse" — a natural drift-free orbit
where a satellite loops forever using essentially zero fuel (measured: 1.41e-12 m/s per orbit).
So station-keeping is free; only reconfiguration burns fuel. Each satellite flies to its slot
with a PD controller (a spring-damper, like cruise control) with a hard thrust cap, and every
burn is metered into a per-satellite fuel total (`cubesat/pd.py`). Note on thrust: `cubesat/pd.py:27`
defaults to `A_MAX_DEFAULT = 1e-2` (0.01 m/s², cold-gas class, used in `nominal.json`), but
the benchmark scenarios like `two_failure.json` explicitly override to `a_max = 0.1 m/s²` because
at 8 km formation scale, the Coriolis barrier ($2n \cdot v_y \le a_{\max}$) makes transfers dynamically
infeasible at 0.01 m/s² (measured and documented in GATES.md G4 re-tune).

Coverage = the fraction of a fixed 961-point ground grid inside the union of the healthy
imagers' camera footprints, footprint radius = altitude × tan(half-FOV) = 13.09 km
(`cubesat/coverage.py`).

### 2.2 Failure detection

Every satellite emits a heartbeat each tick (ticks are 2 seconds). Three failure modes:

- **DEAD** — total silence. Detected after 3 missed heartbeats → **4 s detection latency**
  (by construction, (K−1)·dt with ideal comms — not a measured detector latency).
  (Arithmetic: tick 0 at $t_{\text{fail}}$ is missed heartbeat #1, tick 1 at $t+2\text{ s}$ is #2,
  tick 2 at $t+4\text{ s}$ is #3, so elapsed detection time is $4.0\text{ s}$ with $dt=2\text{ s}$;
  `cubesat/sim.py:280, 318, 326`.)
- **THRUSTER_OUT** — the satellite is alive but can't steer. It *self-reports* the dead
  thruster the moment it fires, so detection is instant. (Honest history: before 2026-10-26 the
  heartbeat couldn't see this failure at all — we fixed the semantics, GATES.md 2026-10-26.)
- **EPS_DEGRADE** — a gradual power fade. The satellite announces DEGRADE_START, keeps flying
  and imaging in DEGRADED status for a window, then dies.

Detection drives the mission state machine:
`NOMINAL → FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED`.

Dead satellites are never frozen: they coast ballistically under the same physics and stay in
the collision checks as moving obstacles for the rest of the run. Minimum separation is logged
over ALL pairs, including dead ones, every tick.

### 2.3 The allocator (the "self-healing" brain)

Two steps, in `cubesat/allocate.py`:

1. **Pick the new formation.** Sweep candidate formations; keep only feasible ones — feasible
   means (a) pairwise separation stays above the safety threshold over a full sampled orbit
   *with the coasting dead satellites included as obstacles*, and (b) every survivor can
   actually reach a seat within its remaining fuel budget. Among feasible candidates, keep the
   one with the highest measured coverage. If nothing beats holding position, the swarm holds
   ("do no harm").
2. **Assign survivors to seats** with the Hungarian algorithm (`scipy.linear_sum_assignment`,
   rows = survivors, cols = seats) on a cost blending travel distance, fuel state, and role
   mismatch. Dead leaders/downlink operators are re-elected onto healthy satellites first.

### 2.4 Backend: live and replay are one pipeline

The simulator core is pure — it computes the whole run and returns every log line, touching no
disk and no clock. The server wraps that in a web product: **live mode is one full recompute in
a background thread; replay mode is the same cursor over a previously committed log file.**
Both feed the same broadcaster, so what you see live IS what you would see in replay — by
construction, pinned by tests. A hub fans messages out over per-client queues that drop stale
position updates but never drop events. Mid-run failure injection works because of
determinism: the server recomputes the rest of the trajectory with everything before "now"
byte-identical, and continues seamlessly (`cubesat/session.py:380-425`).

### 2.5 Frontend: the operator console

React 18 + TypeScript, plain Three.js for the 3D view (procedural Earth, satellites as
constant-screen-size markers, labels that declutter). Pages split by job: **LIVE** is the
control seat (build a scenario — satellite count, roles, geometry, failure schedule, recovery
policy — upload, start, watch); **REPLAY** is playback-only over committed runs. A
plain-language narration strip explains what the swarm is doing; charts have explainer
tooltips; and any number with no committed measurement behind it renders as the literal word
"unmeasured".

### 2.6 The benchmark and the AI layer

- **Exhaustive benchmark:** all C(6,2) = 15 two-failure pairs × 4 policies, machine-written
  into committed JSON artifacts that each embed the command that produced them
  (`data/eval/benchmark_results.json`). Plus a Monte-Carlo mode (20 jittered runs per policy,
  byte-reproducible), physics validity curves, and a two-impulse Δv lower-bound study.
- **The AI story:** we built a LightGBM failure-predictor (132 rolling features, PR-AUC 0.9916
  on its test split, `out2/results.json`; test false-alarm rate 0.4806 per sat-orbit; on the 31 gradual
  test events it alarms a median 260 s earlier than an EWMA baseline, 31/31 earlier — that 260 s
  is a gain over EWMA, not the model's own lead time). Before measuring its control-loop value, we
  pre-registered a kill switch: it ships only if it gains ≥ 0.5 pp of critical-seat health. The
  Gate-2 sweep of 2026-10-04 (imager-death and leader-failure scenarios) measured **+0.0235 pp**
  (= 4 s / 17028 s, the detection window) with fuel up to **2.9×** (leader_failure_6sat,
  484.00 → 1408.80 m/s across the L grid; GATES.md 2026-10-04 entry, not re-run at HEAD) → **CUT**; it survives as a display-only risk overlay.
  The later sweep on gradual-EPS families (`data/eval/oracle_sweep_v2.json`, `uv run python
  files/oracle_sweep_v2.py`) says verdict **CLEAR**: **+1.7968 pp** at L = 300 s, **+10.6048 pp**
  best (L = 1800 s), on a metric that counts the still-working fade window as outage (functional
  metric: +0.047 pp). Pre-registration: nothing integrates into the control loop without a user
  decision, so the loop stays reactive. A rule-based successor exists as an opt-in scenario field
  (swap the failing leader's critical seat when DEGRADE starts): committed `oracle_sweep_v3.json`
  trigger arm = pinned +10.617 pp, functional +0.047 pp, coverage +0.1507 pp; re-running at HEAD
  flips its `recommend` to false (GATES.md 2026-10-31) — treat it as measured-unrecommended.

---

## 3. What we built — assets, numbers, and the commands behind them

Every row: the number, where it lives, and the command of record (run from the repo root).

### Physics core (gates G1–G3, all PASS)

| What | Number | Command |
|---|---|---|
| STM vs numerical integration | 1.353e-12 (Windows) / 1.358e-12 (macOS) rel err (position) | `uv run pytest tests/test_hcw.py -s -q` |
| CW vs full Keplerian, 1 km scale | 3.101 m over 3 orbits | same |
| CW vs full Keplerian, current 8 km scale | **1578.5 m** over 3 orbits | `uv run python -m cubesat.benchmark --mode cw-curve --base data/scenarios/two_failure.json --report data/eval/cw_error_report.json --csv data/eval/cw_error_curve.csv --svg data/eval/cw_error_curve.svg` |
| 1 km rest-to-slot transfer | 746 s, 6.411 m/s Δv, overshoot **4.99%** | `uv run pytest tests/test_pd.py -s -q` |
| Holding a passive slot | ~1.41e-12 m/s per orbit (free) | same |
| Nominal 6-sat coverage | 0.4387 mean tick | `uv run python -m cubesat.run --scenario data/scenarios/nominal.json --seed 42 --out data/logs/nominal.jsonl` |
| Killing 2 of 4 imagers, no recovery | −16.65 to −19.99 pts | `uv run pytest tests/test_coverage.py -s -q` |

### The recovery demo (gate G4, PASS)

`uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl`
→ detection **4 s** (= (K−1)·dt by construction); RECOVERED at **t = 3114 s**; last-orbit coverage **0.2698 with recovery
vs 0.2205 without (+4.93 pts, ~31% of the destroyed coverage restored)**; all-pairs min separation
**3095.1 m** for this pair (threshold 2000 m); per-satellite Δv up to **193.68 m/s**; log is **8517 lines,
SHA-256 `450d5371…`** on Windows (`cb7e2c2a…` on macOS arm64; same-machine reruns identical).

### The exhaustive benchmark (P0–P3 + Δv, all committed in `data/eval/`)

Command of record: `uv run python -m cubesat.benchmark --base data/scenarios/two_failure.json --out data/eval/benchmark --report data/eval/benchmark_results.json --policies do_nothing,even_split,greedy,hungarian`

- Hungarian: coverage **0.26980 mean AND worst** (constant — recovery always ends on the same
  re-phased 4-seat formation); mean total Δv 444.30 m/s; worst per-sat 251.24 m/s; critical roles held 15/15 (`policies_summary`).
- Do-nothing: **0.29106 mean / 0.22045 worst**; critical roles held only 6/15 (`policies_summary.do_nothing.pairs_critical_roles_held`).
- **The honest headline: gain vs do-nothing is +4.93 pts on the three pairs where both dead
  satellites are imagers ((1,2),(1,4),(3,4)), −2.13 pts on average over 15 pairs, negative on the 9
  pairs containing sat 0 or sat 5.** Recovery buys critical roles held (15/15 vs 6/15) and
  determinism, not mean coverage.
- Even-split baseline is obstacle-blind by construction: worst survivor-to-dead clearance **722.8 m**,
  worst per-sat Δv **1308.36 m/s** (`policies_summary.even_split`).
- Monte Carlo (20 jittered runs × both policies, byte-reproducible): mean gain **+4.886 pts**,
  worst **+5.201**, minimum paired gain **+4.545 — all 20 runs positive**, recovery std 0.0025 vs
  0.0045. Scope: ONE failure pair (1,2) — the best case — with four jittered scalars (failure times,
  phase, radial amplitude), so this is parameter-jitter on the best pair, not robustness over failure
  pairs or modes; seed 7 crashes ("no feasible survivor formation", audit C-5).
- Keep-out policy: **CUT** — run-window min clearance **1852.5 m for hungarian** vs **1322.6 m for
  hungarian_keepout** (`data/eval/keepout_report.json`): the exclusion worsened the worst clearance;
  caveat: hungarian_keepout also lacks the do-no-harm hold, so the A/B is confounded.
- Δv reference: the headline 193.68 m/s satellite spent 155.09 m/s on its completed transfer
  vs a **47.81 m/s fixed-time two-impulse reference = 3.24×** (mean 2.95×, worst 5.72×;
  `data/eval/dv_lower_bounds.json`; it is a fixed-time solve, not a proven lower bound).

### The web layer (gate G5, PASS 2026-09-30, untagged)

FastAPI + WebSocket (18 routes: `grep -cE "@app\.(get|post|put|delete|websocket)" cubesat/api.py`), async hub, wire normalizer, replay engine with binary-search
seek; React + Three.js console (11,785 lines TS/TSX in this tree: `find frontend/src -name '*.ts' -o -name '*.tsx' | xargs cat | wc -l`; the frontend branch differs), LIVE/REPLAY/Tutorial/FAQ/Docs pages,
ScenarioBuilder, 3D scene, telemetry charts, display-only risk panel. Replay load of the
8517-line log: **0.337 s** (Windows 2026-09-30; 0.24 s macOS arm64 M3, 2026-10-31). Full run compute:
**2.92–3.24 s** on Windows (target ~2 s, missed, recorded); 1.74 s on the M3 — machine-dependent.
Tests pinning the architecture: `test_live_equals_replay_frames`,
`test_inject_prefix_byte_identical`, `test_hub_slow_consumer_drops_state_keeps_events`.

### Failure semantics, evasion, robustness (2026-10-26 rounds)

- 17 tracked scenario files (`git ls-files data/scenarios | wc -l`, 2026-10-31): nominal,
  two_failure, single_failure_n4, cascading_n8 (8 sats), leader_failure_6sat, firefly_swarm (real
  CelesTrak orbit import), proximity_stress, eps_leader/eps_downlink/eps_imager (EPS fade),
  thruster_leader, and six live_* demo scenarios (2/6/8/12/16/24 sats).
- Evasive collision avoidance demo: 30 EVASIVE_MANEUVER events (HEAD, 2026-10-31), first at t = 0 at 848.53 m
  range, 0.5 m/s per evading satellite per episode (test-pinned) — `uv run python -m cubesat.run --scenario data/scenarios/proximity_stress.json --seed 7 --out data/logs/proximity_smoke.jsonl`.
- Security round (2026-10-29): vite 5→7.3.7, `npm audit` 0 vulnerabilities; CLI output-path
  confinement, schema resource caps, upload caps, host allowlist, malformed-frame close.
- Test suite on the 2026-10-31 tree: 224 collected, all 221 non-slow pass (3 slow not run in this pass).

---

## 4. Is this new — prior art and honest differentiation

**Never say "novel", "first", or "state-of-the-art".** Our position: *measurement, not
novelty.* Every claim names its baseline. (Claims policy: `docs/ENDGAME_PLAN.md` §2.)

- **NASA Starling** (four 6U CubeSats, launched 2023) is the closest flight analog: autonomous
  maneuver planning (ROMEO), self-healing network rerouting (B.A.T.M.A.N.), swarm science
  tasking (DSA). Failure-triggered role reassignment with a measured recovery benchmark is not
  among its listed objectives. We make no flight claim — ours is simulation, and we publish the
  negative headline a flight demo can't.
- **MuSCAT (NASA JPL), Basilisk, NASA 42** — real, verifiable open-source simulators. A
  CW-propagating formation simulator is standard practice; we don't claim the simulator is new.
  What they don't claim (per their public docs): byte-determinism pinned by tests, and a
  purpose-built failure-recovery measurement harness (exhaustive pair sweep with committed
  per-run SHA-256s).
- **Princeton senior thesis (2025, public code)** — the closest single prior work: fuel-optimal
  CW reconfiguration with fault-aware role reassignment, validated on eight scenarios. We
  propose no new allocator; we *benchmark* such policies — all 15 pairs, published baselines
  included — and add what an eight-scenario validation can't show: the mean gain is negative
  while critical roles are held 15/15 versus 6/15, plus a fixed-time Δv-reference study.
- **Hungarian retargeting and fault-tolerant formation-flying control** — mature, published.
  Our reactive path IS that published idea; we cite it and measure it. Our difference is the
  evaluation practice: exhaustive sweeps at matched conditions, negative results shipped, our
  own stack's failure modes disclosed (4.99% overshoot, over-thrust, the obstacle-blind
  baseline).
- **Do not cite "SSPIDR" or "GRAVSIM"** — our prior-art check could not verify either as a
  swarm self-healing mission/tool. If pressed for examples, use Starling, MuSCAT, Basilisk.

**The one-line differentiation, sayable:** "The algorithms are published; what's ours is the
measurement discipline — every number regenerates from one command, and we report where
recovery doesn't help."

---

## 5. What is missing — know this before the judges find it

### Must-fix (before any demo)

1. **README is stale.** It still says G5/G6 are "in progress — not landed" (README.md:10-12),
  so it undersells the entire web layer, the benchmark, and the newer failure modes; the
  promised post-G4 numbers live only in GATES.md. The G7 gate (README with measured numbers +
  demo instructions) is unmet.
2. **A fresh clone cannot run the demo.** `frontend/dist/` is gitignored and the README's
  serve step never mentions `npm ci && npm run build` — a fresh clone serves a JSON
  placeholder. The real recipe: `uv sync --locked` → `cd frontend && npm ci && npm run build`
  → `uv run uvicorn cubesat.api:app --port 8000`. Run the demo from this machine, where dist
  is built.
3. **Nothing is deployed; the multi-stage Dockerfile has never been built** (Docker daemon
  down at every check; G6 is `todo`). There is no live URL — the demo is localhost on this
  machine. Say that plainly; do not imply a deployment.
4. **`data/scenarios/live_12sat.json` and `live_16sat.json` are tracked in git but have no committed
  logs or ledger rows** (only a compute-time measurement for live_12sat, GATES.md timing row). If you
  show a 12-sat or 16-sat run, every coverage/Δv number in it is "unmeasured" by the project's own
  law. Either don't show them, or say exactly that.

### Nice-to-have

- `docs/ARCHITECTURE.md` still says the API "has not started" — stale since G5; don't point
  judges at it, point them at GATES.md and HANDOFF.md.
- Verification debt: the 3 slow tests were not run in the 2026-10-31 pass; the ledger's
  test counts are as recorded on their dates (current: 224 collected, 221 non-slow green). The 2026-10-30
  frontend work has no recorded design-gate/browser pass.
- The older `simulationStart` control posts only `{scenario, seed}` (no policy/predictor) —
  **start live runs from the ScenarioBuilder**, which sends the full payload; a run started
  from the old control may show the policy as "unmeasured".
- A full browser render pass on every page is owed since round 2 — rehearse the demo tonight.

### Disclose if asked (don't hide, don't volunteer everything)

- `eps_leader_6sat.json` now sets `reassign_on_degrade: true` (commit 5fb535c, verified this
  session), so its committed file fires the proactive swap — its ledger row (written before
  that commit) said "no committed scenario sets the field" (GATES.md corrected 2026-10-31). The
  flag also changes this family's oracle/trigger sweep baselines, which flips the v3 `recommend` at
  HEAD (GATES.md 2026-10-31); admit it if cross-checked.
- The container sets `CUBESAT_ALLOWED_HOSTS="*"` and binds 0.0.0.0 — fine for localhost,
  must be tightened before any public URL.
- The 2026-09-28 security scan was partial coverage ("must NOT be claimed fully audited");
  the gate-5 tag was never created; G6/G7 are todo.
- The master prompt's `timeout_fallback` greedy-degradation demo was never built as a
  committed scenario — if a judge asks for the greedy fallback, it exists in the benchmark
  (greedy policy rows), not as a one-command scenario.
- The repo's own clock-of-record (submit 2026-10-03) predates the Oct-26–30 work; the docs
  don't record a deadline change.

---

## 6. The 60-second pitch — say this, word for word

### Option A: Standard Pitch (~155 words, ~70–75 s at a measured pace)

> "We built a simulator that answers a real question: when satellites in a swarm die, does
> reassigning the survivors actually help? Six CubeSats fly a formation on real orbital
> mechanics — the Clohessy-Wiltshire equations, hand-derived and verified against numerical
> integration to one part in a trillion. When a satellite dies, the swarm detects the silence
> in four seconds, re-elects a leader, and a Hungarian assignment re-seats every survivor —
> with the dead satellites still coasting as collision obstacles. Everything is deterministic:
> the same command gives a byte-identical log, pinned by SHA-256 tests. We benchmarked all
> fifteen two-failure pairs against four policies, and the honest result is: recovery loses
> two coverage points on average — but gains almost five when both dead satellites are imagers.
> Recovery buys critical roles held, not average coverage. We even built an AI failure predictor,
> pre-registered its pass threshold, and measured it; the loop stays reactive. Every claim we
> make has a command behind it."

### Option B: Tightened 50-Second Pitch (~115 words, recommended for strict timers & nervous speakers)

> "When satellites in a swarm die, does reassigning survivors actually help? We built a
> deterministic simulator to measure this on real Clohessy-Wiltshire orbital mechanics. Six
> CubeSats orbit Earth; when two die, survivors detect the silence in four seconds, re-elect
> their leader, and re-seat everyone using Hungarian assignment — while dead satellites coast as
> moving obstacles. Same command, byte-identical log, pinned by SHA-256 tests.
>
> We benchmarked all fifteen failure pairs. The honest finding: recovery loses two coverage
> points on average, but gains five points when both dead satellites are imagers. It buys
> critical roles held, not average coverage. We even built an AI failure predictor, pre-registered
> its kill switch, and measured it; the loop stays reactive. Every number has a command behind it."

If you have only 30 seconds, say: "Six CubeSats fly on real orbital mechanics. When satellites die, survivors detect silence in 4 seconds, re-elect the leader, and re-seat via Hungarian assignment while dead sats coast as obstacles. Our benchmark of all 15 failure pairs showed an honest result: recovery loses 2 points of coverage on average, but gains 5 points when both dead satellites are imagers. Recovery buys critical roles held, not average coverage. Every number has a command behind it."

---

## 7. Demo script — what to run, in order

**Tonight (pre-flight, ~10 min).** From the repo root:

```powershell
uv sync --locked
cd frontend; npm ci; npm run build; cd ..               # dist already built; this re-verifies
uv run ruff check .                                     # expect: All checks passed!
uv run python -m pytest -q --tb=no -p no:warnings      # expect: 224 collected, all pass (the 2026-10-31 run: 221 non-slow green)
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
```

**Launch local server (Terminal 1 — leave running):**
```powershell
uv run uvicorn cubesat.api:app --port 8000
```

Open `http://127.0.0.1:8000/` in the browser and click through Landing → Live → Replay once.

**In front of the judges (~5 min). Use Terminal 2 for CLI commands while Terminal 1 serves.**

1. **Determinism proof (terminal, 30 s).** Run the two_failure command twice; then
   `sha256sum data/logs/two_failure.jsonl` twice — same hash both times (on the Windows machine
   `450d5371…`; on macOS arm64 `cb7e2c2a…`).
   *Say:* "Same command, byte-identical log — this is pinned by a test, and it's why the live
   view and replay are the same pipeline."
2. **Replay the committed run (safest, works offline).** In the browser: `#/replay` → load
   `two_failure.jsonl` → play. Point at: the state pill flipping NOMINAL → FAILURE_DETECTED →
   … → RECOVERED; the coverage chart dipping at t = 1200/1500 s and recovering; the min-sep
   chart never breaching the 2000 m floor on this pair; a dead satellite still coasting (click it).
   *Say:* "Two imagers die. Four seconds later the swarm knows. The survivors are re-seated,
   and coverage comes back to 0.2698 versus 0.2205 if nothing is done."
3. **LIVE run + injection.** `#/live` → ScenarioBuilder → start `two_failure` (policy:
   hungarian) → raise speed. Use the failure-injection control to kill a satellite mid-run.
   *Say:* "Injection recomputes the rest of the trajectory with the past held byte-identical —
   only possible because the core is deterministic." (Expect a pause while it recomputes — the full run_scenario takes 1.74 s on the M3, 2.9–3.2 s on the
   Windows machine; the injection recompute itself is not separately timed: unmeasured.)
4. **The benchmark (open the artifact).** Open `data/eval/benchmark_results.json` — show the
   policies summary and the embedded command. *Say:* "Mean gain is minus 2.13 points; best
   case plus 4.93. Monte Carlo: all 20 jittered runs of that one pair positive. We ship the negative."
5. **Close (terminal).** `uv run python -m pytest -q --tb=no -p no:warnings` tail, or just say
   "224 tests collected, the fast 221 green on 2026-10-31 — rerun this morning."

**Fallbacks.** No browser / UI broken → steps 1 + 4 + 5 in the terminal alone. No network →
everything is local. Docker → do not attempt live (never built); say "the Dockerfile is
committed but the image is unverified — the demo is localhost by design."

---

## 8. Judge Q&A crib sheet — 15 questions, short honest answers

**Words to never say:** novel, first, state-of-the-art, overshoot-free, flight-ready,
deployed, AI-driven control loop, distributed consensus.

1. **"So what is this, in one sentence?"**
   A deterministic, fully-measured simulator of a self-healing CubeSat swarm, with a live 3D
   operator console — honest enough to report where self-healing doesn't help.

2. **"Why does recovery *lose* coverage on average?"**
   When the dead satellites are non-imagers, the survivors were already well-placed; re-phasing
   the formation moves everyone and lands on a slightly lower-coverage 4-seat geometry. The
   gain is on the three pairs where both dead satellites are imagers: +4.93 points (0.2698 versus
   0.22045); critical roles are held 15/15 versus 6/15. Measured across all 15 pairs — that's why
   we ran the exhaustive sweep.

3. **"Is the Hungarian algorithm your contribution?"**
   No — failure-triggered Hungarian retargeting is published; our reactive path IS that idea.
   We cite it and measure it. What's ours is the evaluation: all 15 pairs at matched
   conditions, committed logs and hashes, negatives published.

4. **"193.68 m/s of Δv — is that realistic?"**
   No, and we say so. Our thrust cap in `two_failure.json` is 0.1 m/s² (~800 mN) — about 22× a VACCO
   cold-gas module's entire budget (8.8 m/s, a cited figure not re-fetched in the 2026-10-31 pass). We
   also computed a fixed-time two-impulse reference for the same transfer: 47.81 m/s, so our
   controller spends 3.24× that reference (not a proven lower bound). It's a control-algorithm
   measurement, not a hardware claim. (Note: `cubesat/pd.py` defaults to `1e-2` m/s² for cold-gas,
   but 8 km formation spacing requires 0.1 m/s² to clear the Coriolis barrier $2n \cdot v_y \le a_{\max}$.)

5. **"What physics is missing?"**
   No J2, drag, eccentricity, or attitude; ideal comms and sensing; linearized CW equations.
   We measured the linearization error itself: 1578.5 m over 3 orbits at our formation scale —
   it's in the README and the eval artifacts.

6. **"How do you know the physics is right?"**
   The analytic matrix matches independent numerical integration to 1.35e-12 relative error,
   and full two-body propagation to the disclosed residual. Cross-checks run as tests.

7. **"You built an AI — where is it, and what is 'critical-seat health'?"**
   Built, measured, and cut — by a rule we wrote before measuring: ship only if it gains ≥ 0.5
   points of critical-seat health. "Critical-seat health" is the operational uptime of leader and
   downlink roles. Coverage cannot evaluate early failure prediction because leaders/downlink
   satellites do not carry imaging sensors; their value is command/telemetry link continuity.
   The LightGBM model scored PR-AUC 0.9916 with a 0.4806 false-alarm rate per sat-orbit, and alarms a
   median 260 s earlier than an EWMA baseline (a gain over EWMA, not its own lead time). The
   Gate-2 sweep (2026-10-04, imager-death and leader-failure scenarios) gained only +0.0235 pp
   (= 4 s / 17028 s) with fuel up to 2.9× → CUT. The later gradual-EPS sweep
   (`data/eval/oracle_sweep_v2.json`) says CLEAR: +1.7968 pp at L = 300 s, +10.6048 pp best — but on
   a metric that counts the working fade window as outage (functional metric +0.047 pp); the
   pre-registration says nothing integrates into the control loop without a user decision, so the
   loop stays reactive and the predictor display-only. For battery fades, the satellite's own
   degrade announcement is the warning: an opt-in rule swaps the critical seat at DEGRADE_START
   (committed v3 trigger arm: pinned +10.617 pp, functional +0.047 pp, coverage +0.1507 pp; the
   regenerated v3 at HEAD says `recommend: false`, GATES.md 2026-10-31).

8. **"How do you avoid colliding with dead satellites?"**
   Dead sats are never frozen — they coast ballistically and are treated as moving obstacles in
   the feasibility sweep and the separation checks, logged over all pairs every tick. In
   `two_failure.json`, the all-pairs separation never goes below 3095.1 m (that pair only). Across the
   exhaustive 15-pair benchmark, the worst survivor-to-dead clearance reached 1852.5 m: it breaches the 2000 m candidate-formation
   replan buffer (`Allocation.min_sep_km`) due to natural post-replan orbital drift, but stays above
   our 1000 m collision evasion trigger (`Safety.evade_radius_m`) on the 15-pair benchmark (eps_leader_6sat
   dips to 868.0 m at HEAD and does trigger evasion). We also measured a keep-out policy (hungarian_keepout): its worst clearance was 1322.6 m, worse than
   hungarian's 1852.5 m (confounded: it also lacks the do-no-harm hold), so we cut that policy. Discrete
   evasion maneuvers exist as a safety floor.

9. **"Prove it's deterministic."**
   Run the same command twice — identical SHA-256. It's pinned by tests, including
   "a run with the predictor overlay on is byte-identical to a bare run". The core has no
   clock, no RNG, no order-dependent iteration.

10. **"How is this different from Starling / MuSCAT / the Princeton thesis?"**
    Starling flew autonomy experiments; failure-triggered reassignment with a measured
    benchmark isn't among its listed objectives, and we claim no flight heritage. MuSCAT and
    Basilisk are general simulators; ours is a recovery-measurement harness with
    byte-determinism pinned. The Princeton thesis validated fault-tolerant reconfiguration on
    eight scenarios; we benchmark such policies on all pairs and publish the negative mean.

11. **"Is this deployed? Can we open it?"**
    It runs on localhost on this machine — no cloud deployment, and we won't claim one. The
    Dockerfile is committed but the image is unverified; that's our open G6 gate.

12. **"Is the swarm actually decentralized?"**
    No — replanning is centralized and computed in zero time; comms and sensing are ideal.
    Decentralized consensus is explicitly on our do-not-claim list. The seam to benchmark
    distributed policies exists (policies swap in at runtime without touching the core).

13. **"What if only the thruster dies — can you detect that?"**
    A heartbeat can't see it — the satellite keeps transmitting. So we changed the semantics:
    a satellite that detects its own dead thruster self-reports immediately and triggers the
    same recovery path, with zero detection latency. Before that fix it was a real gap in our
    system, and it's documented as one of our mistakes.

14. **"Does it scale beyond six satellites?"**
    The core isn't hardcoded to six — we have committed 8-satellite scenarios (cascading_n8:
    three failure detections, three replans, recovered at t = 5152 s at HEAD). A 16-satellite
    scenario (`live_16sat.json`) is committed but has no committed log or ledger row — by our own
    rule we can't quote numbers from it.

15. **"What's next?"**
    An impulsive/MPC transfer planner (the measured fix for the over-thrust — the PD spends
    up to 5.7× the fixed-time two-impulse reference: per-sat completed ratios 1.28–5.72), J2/drag in the dynamics, sensor noise, and benchmarking
    distributed allocators (e.g. CBBA) through the existing policy seam. The roadmap with the
    code seams is in HANDOFF.md §10.

16. **"Your CW linearization error is 1,578 m over 3 orbits at 8 km, but your safety buffer is 2,000 m and evasion floor is 1,000 m. How can you claim collision safety?"**
    For active satellites, the closed-loop PD controller tracks reference slots at every tick,
    correcting relative drift against truth. But for coasting *dead* satellites, nonlinearities and
    unmodeled J2/drag will indeed cause real trajectories to drift further than linearized HCW
    predicts. We measured and published the exact 1578.5 m curve (`cw_error_curve.csv`) specifically
    to document this limitation: linearized collision keep-out is a control-baseline proof, not a
    flight safety certification.

17. **"How sensitive is your Hungarian allocation to distance (w1), fuel (w2), and role (w3) weights?"**
    Our P1 Pareto study found the front *degenerate on coverage*: coverage is flat (0.26980) across the
    weight grid, while mean total Δv moves from 425.76 to 469.34 m/s (w2 = 2.0 vs 0.1;
    `data/eval/pareto_results.json`, regenerated 2026-10-31). We shipped this finding as-is.

18. **"Why is 3 missed heartbeats at dt = 2s reported as 4s detection latency instead of 6s?"**
    Tick 0 (at $t_{\text{fail}}$) registers missed heartbeat #1. Tick 1 ($t+2\text{ s}$) registers #2.
    Tick 2 ($t+4\text{ s}$) registers #3 and triggers `FAILURE_DETECTED`. The elapsed wall time from
    failure event to declaration is exactly $4.0\text{ s}$ by construction, $(K-1)\cdot dt$ (`sim.py:280, 318, 326`) — not a measured detector latency.

---

*If a judge asks something this document doesn't cover: "I don't have a measured number for
that — I'd rather say unmeasured than guess." That sentence is the project's whole culture,
and saying it will never be wrong.*
