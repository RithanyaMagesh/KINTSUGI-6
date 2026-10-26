# CubeSat Swarm Self-Healing — full project handoff

Written 2026-10-26 for the AI agent taking over the frontend redesign (and for any future work on this repo).
It covers everything: what was built and why, every major decision, every mistake we know about, the current
state of each layer, and the future-improvements roadmap mapped against today's code.

Sources of record this doc summarizes: `GATES.md` (gate ledger, every number + its command), `docs/MASTER_PROMPT.md`
(the spec + research patches), `docs/FRONTEND_SPEC.md` v2.1 (frontend law, §13 design rules), `docs/BACKEND_SPEC.md`
v1.1 (wire/session/replay law), `docs/ENDGAME_PLAN.md` (measurement plan + AI-layer decisions), `audit_out/AUDIT.md`
(read-only technical audit with safe/do-not-claim lists), `docs/IMPLEMENTATION_NOTES.md` (per-gate build notes),
git history, and `graphify-out/graph.json` (code knowledge graph).

---

## 1. What the project is (60 seconds)

A **deterministic CubeSat-swarm self-healing simulator**: six satellites in a leader-follower formation take
imagery; when satellites fail, a heartbeat detector catches the silence and the swarm re-assigns roles and
re-phases the formation to restore coverage — all on real (linearized) orbital mechanics, with fuel accounting
and collision safety, measured over an exhaustive 15-pair × 5-policy benchmark. A FastAPI backend streams the
sim live over WebSocket and replays committed JSONL logs; a React + Three.js console is the operator seat.

The three honest differentiators (judge-facing, all measured):

1. **Every number has a command behind it** — same scenario + seed ⇒ byte-identical log (golden SHA-256 pin in `tests/test_cli.py`).
2. **Satellites move on orbital mechanics, not tweens** — Hill–Clohessy–Wiltshire dynamics with an analytic
   state-transition matrix, verified against numerical integration to ~1e-12 relative error and against
   two-body Keplerian propagation.
3. **The honesty section is a feature** — the over-thrust caveat, the negative mean-coverage result, and the
   AI kill switch are all reported plainly rather than hidden.

Timeline context: hackathon submission was **2026-10-03** (working freeze Oct 2, 18:00 IST — re-baselined from
Oct 1). Work continued post-deadline: the predictor was integrated (and cut by its own pre-registered kill
switch) and the frontend was rebuilt in three rounds. Last commit as of this doc: `7a7b043` (2026-10-04).
G6 (deploy) and G7 (README/demo polish) gates are still `todo` in `GATES.md`.

---

## 2. The law — what any AI working here must not break

In `AGENTS.md` (mandatory onboarding: read `graphify-out/GRAPH_REPORT.md`, query `graph.json` before grepping):

1. **No number without a log + command.** Unmeasured = write "unmeasured". This applies to README, UI, pitch.
2. **Byte-determinism** inside the sim: no wall-clock, no unseeded RNG, no set/dict-order iteration. Same
   scenario + seed ⇒ byte-identical JSONL. The golden pin is `tests/test_cli.py` (short-run sha `c95f31b8…`).
3. **SI units** internally; convert only at the UI edge (`hcw.py:3`, `sim.py:82`).
4. **LVLH frame**, x radial / y along-track / z cross-track (`hcw.py:4-5`).
5. **Dead satellites coast ballistically** (never freeze) and count as obstacles (`sim.py:372-377`).
6. `linear_sum_assignment`: **rows = survivors, cols = candidate slots**, index-epsilon tie-break (`allocate.py:42,217`).
7. **Locked decisions change only with user approval + evidence** (MASTER_PROMPT §2).
8. Research patches override the master prompt where they conflict.

Plus two structural rules the project learned the hard way:

- **No core diff, ever, for seams** (ENDGAME_PLAN Q2): recovery policies, the predictor, and benchmark variants
  enter by **module rebinding at the session layer** (`session.py:401-421` rebinds `cubesat.sim.replan`) or wire
  passthrough (`wire.py:148-149`) — `sim.py`/`allocate.py`/`hcw.py`/`pd.py`/`coverage.py` are off-limits
  (BACKEND_SPEC:21). A brittle seam means cut the feature, not touch the core.
- **Frontend stack + design law** (FRONTEND_SPEC v2.1 §5 + §13): React 18 + TS, Vite, plain Three.js in one React
  component (not R3F), CSS Modules + one `tokens.css` (raw hex ONLY there — grep gate in Appendix B), Zustand,
  Recharts, vendored IBM Plex woff2. "Nothing beyond this table without user sign-off" (spec:196). §13 design law:
  industrial ops console, color = state only, no metric-card grids, `unmeasured` rendered for unmeasured numbers,
  `avoid-ai-design` scanner (`detect.mjs`) must exit 0 on `frontend/src`.
- **Agents never commit.** The user orchestrates commits, and always with explicit paths (`git add -A` once swept
  the user's spec draft into a gate commit). Push only on request.

---

## 3. Chronology — what happened, when, and why

All dates 2026. Commits are on master unless noted.

### Phase A — the sim core, as gates (2026-09-28)

| Gate | What it built | Key measured result |
|---|---|---|
| G0 (`460f73c`) | uv skeleton, ruff+pytest, Dockerfile, CI, research patches applied | 9 tests |
| G1 (`20b6d41`) | CW dynamics: analytic 6×6 STM, passive ellipse, cross-checks | STM-vs-ODE rel err **1.353e-12**; CW-vs-Kepler max error **3.101 m** over 3 orbits (1 km ellipse) |
| G2 (`2c61fe6`) | PD controller + thrust saturation + Δv accounting | 1 km step: overshoot **4.99%**, settle 746 s, **6.411 m/s** (bang-bang lower bound 6.32); occupied slot costs ~1e-12 m/s |
| G3 (`7253418`) | Coverage metric (r_f = h·tan(FOV/2), footprint union), 6-sat nominal, deterministic JSONL logger + golden hash | nominal coverage **0.4387**; 2-imager no-recovery drop **16.65–19.99 pts** (target ≥15) |
| G4 (`ddd88cb`, re-tuned `066a7f1`) | Heartbeat detection + state machine + two-step allocation (formation sweep → Hungarian) + two_failure demo | recovery vs no-recovery **+4.93 pts** last-orbit coverage (0.2698 vs 0.2205, ~31% of destroyed coverage restored); detection latency **4 s**; worst min_sep **3095.1 m**; per-sat Δv up to **193.68 m/s** |

The **G4 re-tune** was the first big correction: the user rejected a_max=0.1 as unratified; restoring the
cold-gas 1e-2 was then *measured* infeasible (Coriolis barrier 2n·v_y ≤ a_max caps transfers at ~2 km — the PD
diverges at every spacing 4–11 km). Resolution: a_max stays 0.1, documented plainly everywhere, and the formation
was re-tuned 11→8 km (gap +3.33→+4.93 pts, Δv 280→194 m/s). Also fixed here: logged coverage had been frozen at
startup roles — latent until leader-death re-election.

Also in this phase: **cluster import** (`6a5cb17`, workflow dwfrun-12f66628) — stdlib OMM importer from CelesTrak
snapshots → hypothetical swarm on a real chief's orbit (FIREFLY-1, 589.309 km, e-gate demo). Honest framing: a
*hypothetical* swarm on a real orbit, never "recovering X" (no real cluster is HCW-tight). And the **knowledge
graph** (`1ddd4b3`) + mandatory AI onboarding rule (`67189ab`).

### Phase B — endgame re-plan: measurement first (2026-09-29)

The user's prior-art review killed any "novel AI" framing. `docs/ENDGAME_PLAN.md` (`30ea77f`, review passes
`6ea5974`, `dba8fa2`) pinned: exhaustive benchmark before any model; AI = risk→**role placement** (never
assignment prediction); oracle-first kill switch; critical-seat health metric (coverage can't show predictor
value — leader/downlink seats don't count toward it); two-impulse CW Δv lower bound to resolve the
"why 193.68 m/s" question. Claims policy: Princeton "validated in simulation, 8 scenarios" (not "only
proposes"); policy 2 = "even redistribution, adapted from", with the non-uniform gap adaptation disclosed;
Starling phrased verifiably. Canonical demo logs committed (`4f2d81b`).

### Phase C — P0–P3 endgame measurements (2026-09-29, workflow dwfrun-01082b84)

Every result below is machine-written into committed `data/eval/` artifacts with commands (GATES.md endgame rows):

- **P0 benchmark** (`8a303a7`): 15 pairs × 5 policies, 75 runs. **Headline: Hungarian's mean gain vs do-nothing
  is −2.13 pts** — recovery buys **worst-case protection (+4.93 pts on the worst pairs) + determinism, not mean
  coverage**. even_split is obstacle-blind by construction (seat 3.4e-9 m from a coasting dead sat). Hungarian
  coverage is constant 0.26980 on all 15 pairs (recovery always ends on the re-phased 4-seat formation).
- **P1 Pareto** (`d828645`): front is **degenerate** — coverage flat across the 12-point grid, Δv set by the
  formation sweep, not the assignment weights. Shipped as-is (user pre-decision Q4).
- **P2 keep-out** (`fe6d68f`): the keep-out exclusion **never fired** (min clearance 1322.6 m with = without) —
  the 2 km sphere is entered by *post-replan* dead-sat drift, which seat selection cannot prevent. **Policy 5 CUT**.
- **P3 CW validity** (`b93c473`): fresh 8 km pin **1578.543 m** CW-vs-Kepler over 3 orbits (1 km: 3.101 m;
  G3-era 11/22 km: 2984.5 m, re-tuned away). Every benchmark number inherits ~1.6 km linearization error.
- **Δv resolution** (`1c94901`): the 193.68 m/s sat spent 155.09 m/s vs a **47.81 m/s two-impulse bound = 3.24×**
  (mean 2.58×, worst 5.64×). The physics floor itself is km-scale. vs VACCO CuSP MiPS cold gas (8.8 m/s @ 8 kg)
  the headline is **~22× the module's entire budget** — the benchmark is a control-algorithm measurement, not a
  flight claim.
- **Deploy** (`302d0e7`): Dockerfile COPYs scenarios + canonical logs; smoke image cubesat-smoke 836 MB, /health 200.

### Phase D — G5, the web layer (2026-09-30, on branch g5-local, workflow dwfrun-8b40fe74)

Built by a teammate's handoff spec (BACKEND_SPEC v1.1 + FRONTEND_SPEC v2.1) via a 7-builder workflow:
wire.py normalizer (one log line → sim_state + optional event/role_reassignment), replay.py (defensive parse,
bisect seek), session.py (Hub with per-client queues, drop-oldest sim_state / never-drop-events, driver pacing,
LiveSource = one recompute in to_thread, ReplaySource = cursor), api.py (18 routes), React console v1.
**100 tests** incl. `test_live_equals_replay_frames` and `test_inject_prefix_byte_identical` (injection recomputes
with a byte-identical prefix — the determinism property that makes live+replay one pipeline). G5 row: PASS-untagged.
Honestly missed targets: full `run_scenario` 2.92–3.24 s (target ~2 s); replay load 0.337 s ✓.
Known UX bug found live: `simStore.reset()` clobbered `connection` on every replay load → lying "Disconnected"
badge + overlay over a working replay (`b33a9fa` fixed it; verified live with a real SAT-1 DEAD injection).

### Phase E — the predictor arc (2026-09-29 → 2026-10-04)

Designed (oracle-first, gradual-family holdout, critical-seat metric) → cut-first when the window closed →
**revived post-deadline**: the user delivered a **trained, sealed LightGBM bundle** (`files/`, 2026-10-03).
Gates 0–2 landed (`59cdf81`, `12298c9`, `6f5bbe6`, `18fd61a`):

- Gate 0: pipeline hardened **I/O-edge-only** (Mimosa hook hard-blocks variable-path `open()` commits) and
  re-sealed (`deefeae1…`); model seal `37900918…` untouched; repro reproduced every semantic number exactly
  (tau to 17 digits, LGB-ships verdict, 260.0 s paired median lead gain) except 1-ulp scipy digit + model bytes
  (lightgbm build drift) — shipped artifact stays the record, CI hash-only.
- Gate 1: `predictor/runtime.py` — telemetry re-synthesized from the sim's own failure schedule; past-only scoring;
  offline on two_failure: alerts at t=600 s vs failures at 1200/1500 s.
- **Gate 2: PRE-REGISTERED KILL SWITCH TRIGGERED — VERDICT CUT.** Max critical-seat gain **+0.0235 pp** vs the
  pre-registered **0.5 pp** threshold; early warning *increased* Δv up to **2.9× (484→1408 m/s)**. The predictor
  is formally out of the control loop; oracle hooks in `sim.py` are dormant (default-off, byte-inert);
  `tests/test_predictor_wire.py:253` pins that a predictor-on live run is byte-identical to a bare core run.

What survived as *display-only*: session-layer risk scoring attached to `sats[].risk` on the wire (opt-in
`predictor:true`), RiskPanel + satellite risk column in the UI. Model record: 132 rolling features, tau 0.02568,
K_ALARM=3, STRIDE=10, L3600; gradual-fault recall **31/31**, median lead gain **260 s** on trained families;
sudden-death recall **6.25%**; comms-family holdout **0/15 = no generalization** — never claim otherwise.

### Phase F — the frontend rebuild (2026-10-03/04)

The user rejected the G5 console wholesale ("no landing page, live=replay, replay broken, 3D is shit blobs,
nothing explains, where is the model"). Three rounds via workflows:

- **Round 1** (`e7a4884`, dwfrun-75399998, 7 builders): procedural Earth globe + starfield, constant-screen-size
  markers (the zoom-blob bug dead), label declutter + auto-fit camera, MissionBrief overlay, NarrationStrip +
  recoveryStore state-machine spine, per-sat role/task history (roleHistoryStore), tabbed telemetry with
  explainer tooltips, replay transport with seek, CustomScenarioModal → `POST /scenarios/upload`, rule-based
  suspect detector. Verified first-hand in a real browser at 1920×1080. HIGH review finding fixed: NarrationStrip
  was narrating non-movers (filtered via prevSlot≠targetSlot).
- **Round 2** (`7a7b043`, dwfrun-c4341551, 8 builders + direct integration): hash-router pages (#/ landing,
  #/live, #/replay, #/tutorial, #/faq, #/docs) with tabbed sidebar; **REPLAY = playback-only** (one top bar, one
  transport); **LIVE = the control seat** (ScenarioBuilder → upload → start, 3D on the same page); Earth restaged
  as the orbit CENTER (projection-verified 14/14); recovery-policy select with honest 422 fallback; predictor
  display path end-to-end. Mid-run the provider quota died; 7/8 builders' work was salvaged and integration
  finished directly. Owed per the commit message: full-suite re-run, browser render pass on every page.
- **Uncommitted working tree (2026-10-26, 11 files +337/−100)**: scenario-draft validator clamp (BOUNDS mirror of
  the pydantic constraints — fixes altitude-min demo blocker), Earth-centred camera fit as default, **simStore
  now stores `policy`** (the dropped-field wart fixed here), **frontend now sends `predictor`** with the AI
  toggle, allocator WHY-line in RecoveryLog/NarrationStrip, role-history cap 50, marker size bump.
- **Pitch-deck audit** (2026-10-04, `audit_out/AUDIT.md`, 457 lines): 109/109 tests green, tsc build clean,
  determinism re-proven 3×; safe-claims + 8 do-NOT-claims lists (see §7.3).

---

## 4. Physics engine — the sim core, and why it is the way it is

Pure, fixed-dt core: `run_scenario(Scenario) -> list[dict]` (INIT header + ticks + SUMMARY), ~1–2 s per run,
touches no disk and no clock.

- **`cubesat/hcw.py`** — linear Hill–Clohessy–Wiltshire, circular chief. Hand-coded analytic 6×6 STM
  (`stm(t,n)`, hcw.py:28-54), `propagate`, `propagate_controlled` (exact for constant LVLH accel = zero-order
  hold, hcw.py:109-116), `drift_free_state` (the passive 2:1 ellipse), `slot_initial_state` — slots sit on ONE
  common passive ellipse with **along-track amplitude = 2× radial** (hcw.py:119-142). Why CW not high-fidelity:
  hackathon scope + analytic STM is exactly testable + determinism is trivial; the measured CW-vs-Kepler error
  at formation scale (1578.5 m over 3 orbits) is carried as an honesty number, not hidden.
- **`cubesat/pd.py`** — PD on full state error vs the *moving* slot reference; saturation ‖u‖≤a_max;
  `dv_used += ‖u‖·dt`; `A_MAX_DEFAULT = 1e-2` (cold-gass assumption, research patch #1); bang-bang time lower
  bound logged per reconfig. Why the reference velocity matters: commanding against the slot's own ellipse
  velocity is what makes passive holding ~free (1e-12 m/s).
- **`cubesat/allocate.py`** — two-step allocation. Step 1 `select_formation` sweeps amp×phase candidates,
  feasible iff pairwise separation ≥ min_sep over 72 orbit samples (coasting dead sats as obstacles) AND a
  perfect matching exists within the 2√(d·a_max) per-transfer budget; objective = measured coverage, first-wins
  on ties. Step 2 `build_cost_matrix` = w1·dist + w2·dist/fuel + w3·role-mismatch (+ index-ε); rectangular
  Hungarian via `linear_sum_assignment`; greedy fallback by scenario toggle or the deterministic 4096-cell cap.
  Role re-election: dead critical roles → majority-role seat, imagers interleaved onto even indices.
- **`cubesat/sim.py`** — tick loop (dt=2 s), state machine `NOMINAL → FAILURE_DETECTED → REPLANNING →
  RECONFIGURING → RECOVERED`; heartbeat: only DEAD stays silent (sim.py:141-146), declaration at missed ≥ K=3
  (⇒ 4 s latency at dt=2 s); dead/THRUSTER_OUT sats coast via `propagate` and stay min_sep hazards; min_sep over
  ALL pairs incl. dead; coverage from *current* roles excluding DEAD. Dormant oracle hooks (ORACLE_ALERT /
  ORACLE_SWAP, default-off, byte-inert, sim.py:214-242/287-321) are the pinned design for any future proactive
  behavior.
- **`cubesat/coverage.py`** — fixed by fiat (coverage.py:8-9): grid of (y,z) targets, r_f = h·tan(FOV/2),
  boolean-OR union of healthy imagers' discs; SUMMARY = mean over last orbit. **Never retune the metric — tune
  spacing/FOV** (research patch #2).
- **`cubesat/scenario.py`** — full JSON schema (name/seed/duration/dt/chief/formation/a_max/gains/sensor/roles/
  failures/recovery/detection/allocation/oracle). Validators: failures reference existing sats;
  `n_slots == len(roles)`.

**Constants of record** (verified 2026-10-26): dt 2 s; a_max 0.1 in two_failure vs 1e-2 default; formation
8 km radial → 16 km along-track (2:1) + 8 km cross-track; min_sep threshold 2000 m; detection 4 s.

**Known physics limitations** (README + ARCHITECTURE, all deliberate disclosures): linearized CW only (no J2,
drag, eccentricity; dead-sat boundedness holds unperturbed only); ideal comms/sensing; centralized replanner;
a_max=0.1 exceeds the cold-gas class (measured infeasible to restore — Coriolis barrier; proper fix = MPC/impulsive
planner, future work); THRUSTER_OUT is invisible to the heartbeat path (see §8).

---

## 5. Backend — API, session, wire, replay

- **One pipeline, two sources** (BACKEND_SPEC §4): `run_scenario` is pure and returns all lines at once, so
  **live = one recompute in `asyncio.to_thread`** wrapped as a `LiveSource` cursor; **replay = `ReplaySource`**
  over committed JSONL; both feed the same driver → `wire.to_messages` → Hub → WS. Consequences that are load
  -bearing: live equals replay by construction; injection = recompute with byte-identical prefix; no schema drift.
- **`cubesat/session.py`** — Hub: per-client `asyncio.Queue(maxsize=128)`, publish O(1), full queue drops the
  oldest queued `sim_state` and **never** an event (session.py:46-83). Driver is the only pacing loop
  (wall-clock for pacing only, never message content); WS cadence capped at 30 Hz with event/final frames always
  emitted; late joiners get the latest snapshot. Compute timeout 60 s → 504 + session stopped.
- **Policy seam** — `sim.py` does `from cubesat.allocate import replan`, so the call resolves the module global
  `cubesat.sim.replan`; the session rebinds it (`_install_seam`/`_restore_seam`, session.py:401-421) to swap
  recovery policy with zero core diff. `_POLICY_REPLANNERS` maps only `even_split` and `hungarian_keepout` —
  `"hungarian"` is deliberately absent so a default start never rebinds and stays byte-identical to the golden
  pin. The seam is held open across the run so failure-injection recomputes under the same policy. Process-global
  by nature: **one Session per process is a load-bearing assumption**.
- **Predictor overlay (display-only)** — session builds a t→sat→risk map from the sealed `predictor/runtime`
  (repo-root package `predictor/`, NOT `cubesat/predictor/`), attaches `sats[].risk` with bisect carry-forward,
  echoes `predictor: true` in hello only when active; any scoring failure = exactly one warning event. NOTHING in
  sim/allocation consumes risk (pinned by `tests/test_predictor_wire.py:253`).
- **`cubesat/wire.py`** — one log line → `[sim_state, (event?), (role_reassignment?)]`. sim_state: type,
  sim_time, state, scenario, seed, [policy], sats[], coverage, min_sep, metrics. sats[]: id "SAT-n" (1-based),
  role, status (DEAD/THRUSTER_OUT→"failed"), r, v (SI passthrough), dv_used, failure_type, target_slot, optional
  risk. **Policy echo is deviation-only** (only when ≠ hungarian) to keep default wire bytes pinned. INIT maps to
  `state:"NOMINAL"` with empty sats; SUMMARY → "Run complete" event. `replanning_latency_ms` is always null by
  design → frontend renders "unmeasured".
- **Routes** (api.py): GET /health (enriched; key set pinned by test_smoke), GET /scenarios,
  POST /scenarios/upload (422 invalid / 409 collision, server-side schema validation), GET /replay/files,
  GET /replay/file/{f} (traversal guard), POST /simulation/{start,pause,resume,speed,reset},
  POST /failure/inject (409 with reason on all conflicts), POST /replay/{load,pause,resume,seek,speed,stop},
  WS /ws/state (hello → snapshot → stream; ping→pong), static mount of frontend/dist when built.
  Error semantics (§7.1): empty scenarios → 200 [], stopped → 409, unknown replay → 404, corrupt replay → 200
  skipped=N, timeout → 504.
- **Tests**: 25 files, **123 tests collected** (2026-10-26) — incl. wire golden fixture (committed
  `tests/fixtures/wire_golden.json`), policy selection (7), predictor seal/runtime/wire, oracle sweep,
  scenario upload/zoo. Last *full-suite green* run on record: 109 passed (2026-10-04 audit); a full re-run after
  round 2 is still owed. Env note: use `uv run python -m pytest` (`uv run pytest` is spawn-blocked on this
  machine, os error 4551) and `--basetemp=.pytest_tmp` is pinned in pyproject (default tmp path access-denied).
- **Docker**: single-stage image, smoke-tested 836 MB, /health 200. The **multi-stage amend** (node build stage +
  dist copied in) demanded by BACKEND_SPEC §8.2 is still owed on the main line.
- **Module map (analysis layer, all zero-core-diff)**: `benchmark.py` (modes: default 15-pair sweep, pareto,
  keepout-report, cw-curve), `pareto.py`, `keepout.py` (pure log analysis — must not import sim), `cw_curve.py`,
  `dv_bound.py` (two-impulse CW lower bounds with a singularity guard), `cluster_import.py` (OMM → scenario).

---

## 6. AI/ML layer — what exists, what was cut, and the rules

- **What the model is**: LightGBM early-warning failure predictor over synthetic per-sat telemetry (6 channels,
  132 rolling features at 15/60/300 s windows). Frozen artifact `models/predictor.txt` (sha `37900918…`), sealed
  pipeline `files/predictor_pipeline.py` (src sha `deefeae1…`, self-enforcing via its own manifest), tau 0.02568,
  K_ALARM=3, STRIDE=10, label L3600. CI verifies hashes and **never retrains**; thresholds never tuned on test
  seeds 9500–9559.
- **Measured**: PR-AUC 0.9916 vs EWMA 0.9495; gradual-fault recall **31/31** with **260 s** paired median lead
  gain (sign-test p 9.3e-10); sudden-death recall **6.25%** (1/16 — by construction, no precursor);
  comms-family holdout **0/15 = no generalization to unseen families**. Offline on two_failure: alerts 600 s
  before each failure.
- **The kill switch**: pre-registered in GATES.md *before* any sweep number — GO iff ≥0.5 pp critical-seat health
  gain at L=300 s. Measured max **+0.0235 pp** (it only removes the 8 s detection lag), and early warning
  *multiplied* propellant up to 2.9× (484→1408 m/s). **VERDICT = CUT** — the predictor is out of the live control
  loop. This verdict stands; re-opening it is a locked-decision change needing user approval + a GATES entry +
  BACKEND_SPEC amendment *before* any diff.
- **What remains wired (display-only, opt-in)**: `StartRequest.predictor` / `ReplayLoadRequest.predictor`
  (default off = byte-identical wire) → session risk map → `sats[].risk` passthrough → RiskPanel + satellite list
  risk column + ScenarioBuilder "AI risk overlay" toggle. As of the uncommitted working tree the frontend
  actually sends the toggle (it previously didn't).
- **The design on the shelf for later** (ENDGAME_PLAN §7): risk → **post-Hungarian critical-seat swap**
  (deterministic, one swap, lowest-sat-id tie-break, no allocate.py diff) — dormant as the Oracle hooks. Note
  the structural facts any revival must respect: committed scenarios' dying sats are imagers → critical-seat
  health is structurally flat → value needs NEW scenarios with failures on leader/downlink seats; THRUSTER_OUT
  keeps heartbeats so the reactive path never reassigns it (a proactive path is the only thing that can move its
  role — that ~65 pp observation is labeled, never used as gate input).

---

## 7. Frontend — architecture, what exists, what's wrong

### 7.1 Architecture (~13.5k lines TS/TSX, current working tree)

- **Stack**: React 18.3 + TS 5.6 + Vite 5.4, Zustand 5, Recharts 2.15, plain Three.js 0.171, CSS Modules +
  `src/styles/tokens.css` (65 lines, the ONLY file allowed raw hex), vendored IBM Plex woff2. No test framework.
- **Data flow**: `App.tsx` mounts `useWebSocket()` once → every WS message goes through **one shared
  deserializer** (`api/deserializer.ts`, 163 lines — hello/sim_state/event/role_reassignment/pong; malformed
  dropped) → fanned into `simStore` (console state) + `recoveryStore` (recovery narrative: phases, failure
  records, assignments) + `roleHistoryStore` (per-sat role history + suspects, cap 50) + `historyStore`
  (chart samples @2 Hz). Auto-reconnect 1 s→10 s cap + mandatory 30 s ping.
- **Pages** (hash router, no new deps): `#/` landing, `#/live`, `#/replay`, `#/tutorial`, `#/faq`, `#/docs`;
  `Router.tsx` globs only `src/pages/*Page.tsx` — pages built in `components/{landing,live,replay,pages}/` get
  one-line re-export slots in `src/pages/`. Unknown hash → landing.
- **LIVE vs REPLAY** (the product definition the user gave, verbatim in spirit): LIVE = you control the
  satellites — choose count, roles, formation geometry, failures (sat/time/mode), recovery policy, seed/speed/
  duration, AI-risk toggle → upload → start, 3D plays on the same page. REPLAY = pick a committed run from the
  gallery and just play/seek it — one top bar, one transport, no control chrome.
- **3D scene** (`components/three/`): `swarmScene.ts` controller (372) + `sceneEarth` (procedural globe +
  atmosphere + graticule, "stylized, not to scale"), `sceneSatellites` (constant-screen-size markers),
  `sceneLabels` (declutter with priority hiding + leader ticks), `sceneSlots`, `sceneCamera` (auto-fit with
  "earth" default in the working tree), `sceneLines` (ghost slots/trails/failure lines toned down), `sceneColors`
  (token bridge). Earth sits at the ring center of the formation frame (round-2 staging, projection-verified).
- **Panels**: tabbed sidebar (Mission/Satellites/Recovery/Events/Builder); NarrationStrip = plain-language
  state-of-now + recovery story; RecoveryLog (436) = replan steps + allocator WHY-line; SelectedSatellitePanel =
  role semantics, LVLH r/v, slot, Δv, suspect; telemetry charts (coverage money chart, derived deviation, min-sep
  with measured reference, per-sat Δv, health) with explainer tooltips; EventLog defaults to latest 3 + Show-all;
  Timeline capped at 2 stamps.
- **Gates that any UI change must pass**: `cd frontend && npm run build` (tsc+vite), hex grep gate
  (`grep -rn "#[0-9a-fA-F]{3,8}" frontend/src | grep -v styles/tokens.css` → nothing), avoid-ai-design scanner
  (`node detect.mjs frontend/src frontend/index.html` → exit 0; last recorded run: 116 files, 0 findings), §13
  checklist, browser render pass.

### 7.2 Uncommitted work in the tree (2026-10-26) — do not lose this

11 files, +337/−100: scenario-draft validator clamp (mirrors every pydantic bound; fixes the altitude-min
demo blocker), Earth-centred camera fit default, **simStore stores `policy`**, **frontend sends `predictor`**,
allocator WHY-line, role-history 50-entry cap, TopStatusBar user-select:none, marker size 0.08→0.11. These
address known warts — land them before or as part of the next round.

### 7.3 The honest "what's wrong" list

User's verdict driving the redesign rounds: cluttered, nothing explains, live/replay confusion, 3D quality.
Round 2 landed the structural fixes; what follows is what's *still* true:

From `audit_out/AUDIT.md` — **do NOT claim** (each one was measured wrong or doesn't exist):
"overshoot-free" (4.99% measured); runs on standard cold-gas hardware (~800 mN, up to 193.68 m/s Δv, >20×
commercial capacity); AI/ML in the live control loop (CUT — +191% fuel for negligible gain); THRUSTER_OUT
detected autonomously (heartbeat sees DEAD only); reconfiguration raises average coverage (mean −2.13 pp vs
do-nothing); full physics (J2/drag unmodeled); cloud-deployed (localhost only); decentralized consensus
(centralized Hungarian). Safe-claims list is in the same file (:436-446).

Known open warts (see §9 for the full list): predictor/policy 422 fallback silently starts without both; three
copies of fetch/error-format logic (backend.ts / scenarios.ts / runApi.ts); `backend.simulationStart` older
path posts only {scenario, seed}; a hungarian run's policy readout still shows "unmeasured" unless hello carried
it; role-history 50-entry cap truncates long runs; right-panel tab overflow at 1920 + possible tooltip clipping
in scroll panels; **full suite + per-page browser render pass owed since round 2**.

---

## 8. Mistakes we made — the honest suite

Engineering mistakes (each one was measured and disclosed, not hidden):

1. **a_max=0.1 over-thrust** — every benchmark Δv inherits ~800 mN (above the 150 mN cold-gas class); restoring
   1e-2 was measured infeasible (Coriolis barrier caps transfers at ~2 km). Proper fix (MPC/impulsive planner)
   is future work. Lesson: when a patch's assumption fails, measure the whole envelope before re-tuning.
2. **Coverage metric frozen at startup** — logged coverage followed the original roles, latent until
   leader-death re-election (G4). Lesson: follow *current* state, not a snapshot.
3. **"Recovery improves coverage" was wrong on average** — the 15-pair benchmark measured mean gain −2.13 pts;
   only worst-case pairs gain. Lesson: exhaustive sweeps overturn plausible single-demo stories — this is why
   P0 exists.
4. **Pareto front degenerate** — Δv is set by the formation sweep, not assignment weights. The planned
   "fuel-vs-coverage trade" chart had no trade in it; shipped as measured.
5. **Keep-out policy CUT** — the exclusion never fired; the 2 km sphere is entered by post-replan drift, which
   seat selection can't prevent. (This is exactly what the future "continuous collision avoidance" item fixes.)
6. **THRUSTER_OUT invisible to detection** — it keeps heartbeats, so the reactive path never reassigns its role.
   A sim-core semantic gap, disclosed, not fixed (fixing it = core diff = user approval).
7. **Predictor kill switch fired** — pre-registered 0.5 pp vs measured 0.0235 pp, and early warning *cost* fuel.
   Lesson: pre-registering the threshold before seeing numbers is what made the CUT honest and cheap.

Frontend mistakes (the "it's shit" history, in order):

8. **G5 console v1** — cluttered, nothing explained, live=replay indistinguishable, 3D blobs. User rejected it
   wholesale; three rebuild rounds followed.
9. **zoom-blob bug** — satellite markers grew with zoom; fixed with constant-screen-size markers.
10. **NarrationStrip narrated non-movers** — HIGH review finding; fixed via prevSlot≠targetSlot filter.
11. **simStore.reset() clobbered the connection state** — "Disconnected" badge + overlay lying over a working
    replay. Fixed in `b33a9fa`; lesson: don't reset derived/live state wholesale.
12. **Nav markup without CSS** (round 2) — an agent added nav HTML and no styles; default blue links. Lesson:
    markup and its CSS land in the same commit.
13. **Replay double chrome** (round 3 trigger) — double top bar + double transport with a stale dropdown; fixed
    by making replay strictly playback-only.
14. **simStore dropped the parsed `policy` field** and **the frontend never sent `predictor`** — both fixed only
    in the current uncommitted tree. Lesson: wire fields nobody stores are fields nobody sees.
15. **3-curve coverage chart not built** — the wire carries no reference runs; the chart says so instead of
    faking it. (Honest, but it was also a spec item that silently became "not built".)

Process/tooling mistakes:

16. **`git add -A` swept the user's draft** (FRONTEND_SPEC, 2,138 lines) into gate commit `20b6d41`. Rule since:
    explicit paths only; agents never commit.
17. **Committing mid-run broke workflow resume** — a WIP commit during dwfrun-58665a3e made the journal
    non-replayable (InputHashMismatch); the run had already died on provider quota, and 7/8 builders' work was
    salvaged by hand. Rule: never commit while a workflow may resume.
18. **`pytest -m` argv split in workflow `world.run`** — `["-m","not","slow"]` made pytest read `-m not` (exit 4).
    Must be one element. Subagents can't fix this themselves; it needs an amend.
19. **Mimosa security hook hard-blocks** Bash writes of `.py` files and any commit with variable-path `open()`
    writes; the frozen predictor pipeline needed a user-approved I/O-edge-only hardening (the user applied the
    final patch by hand). Flagged line numbers can be stale.
20. **Windows/env quirks that cost hours**: `uv run pytest` spawn-blocked (os error 4551) → `uv run python -m
    pytest`; pytest basetemp access-denied → `.pytest_tmp` pin; CRLF breaks byte-determinism → new file writers
    must force LF; `>nul` redirect under Git Bash creates a literal `nul` file; backslashes get mangled in
    heredocs; graphify multiprocessing dies from stdin heredocs (sequential fallback); ruff caches after a
    flagged file is deleted (`--no-cache`); uv image has no versioned python-variant tags (pin by digest);
    Docker Desktop is a per-user install.
21. **Browser-automation quirks**: locator clicks time out against 30 Hz WS re-renders (use coordinate clicks
    from screenshots); a wedged capture after reload needs a fresh tab; cached 304 bundles lie after rebuilds
    (hard-refresh Ctrl+Shift+R).
22. **Stale claims had to be re-verified**: an explorer pass claimed "no Dockerfile in tree" (wrong — GATES risk
    row was right); an early "CelesTrak is blocked" note was outdated (curl works fine). Lesson: the tree wins
    over every cached claim, including our own.

---

## 9. Open warts (unfixed, by layer)

Backend/physics:
- THRUSTER_OUT never reactively reassigned (heartbeat-visible) — semantic gap, core diff to fix.
- `replanning_latency_ms` always null (unmeasured) — honest, but still a hole in the wire.
- run_scenario 2.9–3.2 s vs ~2 s target (one-time start latency, disclosed).
- ARCHITECTURE.md is stale in spots (dated 2026-09-28, "G5 not started"; some line refs predate the oracle block).
- Dockerfile single-stage; §8.2 multi-stage amend owed. G6/G7 gates still todo.
- Mimosa full security audit still owed (partial coverage flagged on every commit; recurring benign medium at
  benchmark.py:278).

Frontend:
- Predictor/policy 422 fallback silently starts without both (one combined note).
- Three copies of fetch/error-format logic (api/backend.ts, api/scenarios.ts, runApi.ts).
- `backend.simulationStart` legacy path posts only {scenario, seed} (no speed/policy/predictor).
- Hungarian-run policy readout can show "unmeasured" (frames echo policy only on deviation; hello covers live
  but the round-2 commit's simStore fix is uncommitted).
- roleHistoryStore 50-entry drop-oldest truncates long runs' role story.
- Right-panel tab overflow at 1920; tooltip clipping possible in scroll panels.
- Dormant `uiStore.mimosa...`/mission-brief remnants; `.mimosa/` hook-state dirs littered under frontend/src.
- Owed: full-suite re-run + browser render pass on every page since round 2.

---

## 10. Future improvements — the roadmap we are adding, mapped to today's code

The nine items below are the user's list (pasted verbatim in the request). For each: what exists today, what it
touches, and the approval/seam reality. **Everything that touches `sim.py`/`allocate.py`/`hcw.py`/`pd.py`/
`coverage.py` is a core diff → user approval + GATES entry first** (invariant 7, BACKEND_SPEC:21, ENDGAME Q2).
Items 1/2/3 are the previously recommended top-3 (audit_out roadmap) and are the cheapest honest wins.

| # | Improvement | Exists today | Touches | Seam / approval reality |
|---|---|---|---|---|
| 1 | **Decentralized swarm control (CBBA)** | Hungarian + greedy fallback only (audit do-NOT-claim) | new allocator beside `allocate.py`; benchmark policies | Add as a **benchmark/session policy** via the existing seam pattern (`benchmark_policies.py`, `_POLICY_REPLANNERS`) — no core diff. Honest comparison needs #6 (comm delays). |
| 2 | **Realistic failure modes** (battery degradation, comm loss, OBC, partial thruster) | DEAD + THRUSTER_OUT only; EPS/battery = 44% of real smallsat failures, unmodeled | `sim.py` failure semantics, `scenario.py` FailureMode, wire status mapping, frontend status colors/narration | Core diff (approval). Strongest pitch line available: "we model the failure mode that actually kills 44% of smallsats — and recover from it." Gradual degradation is exactly what the cut predictor detects (31/31 recall) — synergy. |
| 3 | **Monte Carlo robustness testing** | Deterministic 15-pair benchmark; no noise model | benchmark harness + optional sensor-noise channel in scenario schema | Seed sweeps over existing scenarios need **zero core diff** (determinism makes them cheap). Sensor-noise injection = core diff. |
| 4 | **Continuous collision avoidance** | Replan-time min-sep only; keep-out CUT (2 km sphere entered by post-replan drift, 1322.6 m) | `sim.py` tick loop monitor + evasive maneuver logic | Core diff (approval). This is the fix for the measured keep-out failure; also directly addresses the 3/15 pairs dipping below 2 km in transients. |
| 5 | **Larger swarm scaling** | Sim core never hardcoded to 6 (`n_sats = len(roles)`); OMM importer exists; 4096-cell allocation cap | `allocate.py` cap, scaling benchmark, frontend slot rendering/perf | Scaling study = benchmark work (no core diff). Past the cap the code silently uses greedy — measure before raising it. |
| 6 | **Communication-aware coordination** | Ideal comms (disclosed limitation) | `sim.py` comms/link model; needed for honest CBBA (#1) comparisons | Core diff (approval). Do together with #1 or CBBA comparisons are dishonest. |
| 7 | **Hardware-in-the-loop testing** | Nothing; the session-layer seam (module rebinding) is the natural boundary | GNC plugin API at the session edge | The seam pattern is the architecture for it; HIL rig is a separate workstream entirely. |
| 8 | **High-fidelity orbital dynamics** | Linearized CW, 1578.5 m error at formation scale, disclosed everywhere | `hcw.py` (J2/drag/eccentricity) | **Locked decision** (MASTER_PROMPT §2: HCW, no poliastro) — user approval + evidence required; would invalidate/require re-pinning the golden determinism hashes and the CW-vs-Kepler framing. |
| 9 | **Autonomous mission replanning** | Single replan per failure episode; dormant Oracle hooks (alert + one post-Hungarian critical-seat swap) = the pinned design | `sim.py`/`allocate.py` objective + the Oracle path | The Oracle machinery is already in-core (default-off, byte-inert) — the designed entry point. Re-opening predictor-driven placement = locked-decision change (see §6). |

Design-law note for whoever builds the UI side of these: any new panel/control obeys FRONTEND_SPEC §13 (tokens,
scanner, `unmeasured` for unmeasured numbers, color = state only), the wire gains only optional/additive fields
(BACKEND_SPEC App B pattern), and every new displayed number needs a committed log + command or the word
"unmeasured" (invariant 1).

---

## 11. Commands

```bash
uv sync --locked                                   # deps
uv run ruff check .                                # lint
uv run python -m pytest -q                         # full suite (123 tests)   # NOT `uv run pytest` (spawn-blocked here)
uv run python -m pytest -q -m "not slow"           # fast loop
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
uv run uvicorn cubesat.api:app --port 8000         # one process: UI + API + WS
cd frontend && npm run build                       # tsc + vite gate
# design gates: hex grep (Appendix B) + avoid-ai-design detect.mjs (§13.7)
```

Benchmark commands of record live in GATES.md endgame rows and inside each committed `data/eval/*.json`.

## 12. Where everything lives

- Physics core: `cubesat/hcw.py`, `pd.py`, `allocate.py`, `sim.py`, `coverage.py`, `scenario.py`
- Web layer: `cubesat/api.py`, `session.py`, `wire.py`, `replay.py`, `run.py`
- Analysis: `cubesat/benchmark.py`, `pareto.py`, `keepout.py`, `cw_curve.py`, `dv_bound.py`, `cluster_import.py`
- AI (offline): `predictor/runtime.py` (repo-root package), `models/predictor.txt` + manifest, `files/`
  (sealed pipeline, integration prompts, oracle sweep results), `out2/` (reference outputs)
- Frontend: `frontend/src/{api,stores,pages,components}`; design law: `docs/FRONTEND_SPEC.md` §13
- Data: `data/scenarios/*.json` (nominal, two_failure, firefly_swarm, single_failure_leader_n4,
  cascading_n8, leader_failure_6sat), `data/logs/` (two canonical logs committed), `data/eval/` (benchmark/
  pareto/cw/dv artifacts), `data/celestrak/`
- Law & ledger: `AGENTS.md`, `GATES.md`, `docs/MASTER_PROMPT.md`, `docs/{FRONTEND,BACKEND}_SPEC.md`,
  `docs/ENDGAME_PLAN.md`, `docs/IMPLEMENTATION_NOTES.md`, `audit_out/AUDIT.md`, `graphify-out/graph.json`
