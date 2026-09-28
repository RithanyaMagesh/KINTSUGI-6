# MASTER BUILD PROMPT — CubeSat Swarm Self-Healing (Problem #b2ef60e9)

> Captured verbatim from the user's build prompt on 2026-09-28. The final section,
> "Research patches", is the user's source-verification update and **overrides the master
> prompt where they conflict**.

You are the lead engineer on a 3-day hackathon build. Read this whole file before writing any code.

## 0. Mission
Problem statement: **"When 2 of 6 satellites in a formation fail, dynamically reassign roles among survivors to maintain mission-critical coverage."**

Deliver a **deployed, reproducible, visual demo** of a 6-CubeSat swarm that detects two failures, replans, and recovers coverage, with **measured** results against a no-recovery baseline.

- Submission: **Oct 1**. Feature freeze: **Sep 30, 18:00 IST**. After freeze: bug fixes, README, video only.
- Judges see: a live URL, a 3D view, a telemetry dashboard, a README with a one-line reproduce command.

## 1. How you must operate (non-negotiable)
1. **Hypothesis → test → report.** Before each component: state what must be true, write the test that proves it, then implement. Never say "works" without a test or run log behind it.
2. **Phase gates.** Work gate by gate (section 6). Do not start gate N+1 until gate N's tests pass. If a gate fails after its time-box, STOP and report: what failed, evidence, 2 options with tradeoffs. Do not silently simplify or work around.
3. **No fabricated numbers.** Every metric in the README, dashboard, or pitch must come from a committed run log. If unmeasured, write "unmeasured".
4. **Locked decisions (section 2) are locked.** If you believe one is wrong, say so with evidence and wait. Never swap silently.
5. **Scope discipline.** Anything not in sections 2–6 is out of scope. No auth, no Kubernetes, no DB, no ML models, no React, no protobuf.
6. **Small diffs.** One gate = one commit series. Show diffs, not prose summaries. Run `uv run ruff check` and `uv run pytest` before every commit.
7. **Verify against sources, not memory.** Formulas below are from my knowledge and MUST be checked by the tests specified. Free-tier limits, library versions, and CLI flags: check current docs before relying on them.
8. **Report format after each gate:** `GATE n: PASS/FAIL | tests: x/y | key numbers | risks found | next`.

## 2. Locked decisions
| Area | Decision |
|---|---|
| Language/tooling | Python 3.12, **uv** (commit `uv.lock`), numpy, scipy, fastapi, uvicorn, pydantic v2; dev: pytest, ruff |
| Physics | Hill–Clohessy–Wiltshire relative motion, circular chief orbit ~500 km, hand-coded analytic STM. **No poliastro** (not a relative-motion tool; project archived) |
| Formation | Slots on **passive (drift-free) relative orbits**, phase-spaced, not a static hexagon |
| Control | PD on **full state error vs a moving reference** (position AND velocity), thrust saturation, Δv accounting |
| Allocation | Two-step: (1) choose survivor formation, (2) rectangular Hungarian via `scipy.optimize.linear_sum_assignment` |
| Collision | Min-distance metric logged every step and asserted in tests. No potential fields |
| Failures | Dead satellite **coasts ballistically** and stays a collision hazard. It does not freeze |
| Frontend | Plain Three.js, single page, **vendored locally** (no CDN at demo time) |
| Transport | JSON over WebSocket; JSONL run logs are the primary data format |
| Deploy | **One** FastAPI service (serves API + WS + static UI) in Docker, plus a static replay-only mirror |

## 3. Domain briefs (think like each of these experts)

### 3.1 Astrodynamics engineer
Frame: LVLH, x radial, y along-track, z cross-track. n = sqrt(mu/a^3); for a = 6878 km, n ≈ 1.107e-3 rad/s, period ≈ 94.6 min.
Equations: `x'' - 3n²x - 2n y' = ax`, `y'' + 2n x' = ay`, `z'' + n²z = az`.
STM (verify numerically, do not trust):
```
x(t)  = (4-3c)x0 + (s/n)vx0 + (2/n)(1-c)vy0
y(t)  = 6(s-nt)x0 + y0 - (2/n)(1-c)vx0 + (1/n)(4s-3nt)vy0
z(t)  = z0 c + (vz0/n) s
vx(t) = 3n s x0 + c vx0 + 2s vy0
vy(t) = 6n(c-1)x0 - 2s vx0 + (4c-3)vy0
vz(t) = -z0 n s + vz0 c          with c=cos(nt), s=sin(nt)
```
Drift-free condition: `vy0 = -2n x0`. In-plane bounded motion is a 2:1 ellipse (along-track amplitude = 2 × radial amplitude).
Known pitfalls: sign errors in the y row; treating a "stopped" satellite as stationary (in LVLH nothing is stationary without thrust); linearization error grows with separation.
**Must verify:** (a) STM vs RK45 integration of the ODEs, tolerance ≤1e-6 relative over 3 orbits; (b) drift-free ellipse closes after one period; (c) **nonlinear check**: for your chosen formation size, compare CW against a plain two-body Kepler integration over 3 orbits and report max position error. Do not cite validity ranges from papers you have not opened.

### 3.2 GNC / control engineer
A CubeSat under thrust is a double integrator plus CW coupling. P-only control does not damp. Use `u = -Kp(r - r_ref) - Kd(v - v_ref)`, with `Kp = wn²`, `Kd = 2·zeta·wn`, zeta ≈ 1.
Because slots move along their ellipse, the reference has velocity. `-Kd·v` alone (static-target form) fights the natural motion and wastes fuel. Use `v_ref`.
Real constraints: thrust saturation `a_max` (start ~1e-4 m/s² for a small CubeSat, make it a scenario parameter), so pick `wn` from `a_max` and reconfig time, not from a wishlist. Bang-bang lower bound on reconfig time for distance d: `t >= 2*sqrt(d/a_max)`. Report the Δv used per satellite. Discrete-time: fixed dt (1–5 s), RK4 or STM step plus control; no wall-clock inside the sim.
**Must verify:** step response of one chaser: overshoot <5%, settles in target time, never exceeds `a_max`; steady-state error on a passive slot ≈ 0 with near-zero Δv.

### 3.3 Optimization / task-allocation engineer
Roles have **criticality weights and capabilities** (e.g. 1 leader/relay, 4 imagers, 1 downlink), so role loss matters, not just position loss.
With k survivors and 6 roles, the real decision is which roles/slots to keep. Two steps:
1. **Survivor formation:** choose k slot positions (candidates: k evenly phase-spaced slots on the ellipse, sweep ellipse size and phase offset over a small grid) maximizing coverage, subject to min separation and reachability within Δv budget. Re-elect critical roles first.
2. **Assignment:** cost matrix `C[i,j] = w1*dist_norm + w2*dist_norm/fuel_i + w3*role_mismatch`, normalized per term. `linear_sum_assignment` on the (k × slots) matrix.
Determinism: break ties with a tiny index-based epsilon. Include the **timeout fallback** (greedy nearest-slot) with a toggle so the demo can show graceful degradation.
**Must verify:** same input → identical assignment over 100 runs; rectangular case returns k assignments; leader-failure scenario re-elects a leader; greedy fallback is worse-or-equal in cost than Hungarian.

### 3.4 Mission analyst (the coverage metric — define it FIRST)
Both earlier plans never defined coverage. Lock this:
- Ground target: a grid of points in the (y, z) along/cross-track plane.
- Each healthy imager covers points within footprint radius `r_f = h·tan(FOV/2)`. Choose a narrow FOV so `r_f` is comparable to slot spacing (e.g. ~10–15 km at 500 km with ~3° half-angle; tune). If footprints overlap completely, coverage is meaningless.
- Coverage = fraction of grid points covered by the union of healthy footprints; also log time-averaged coverage over the last orbit.
- Always compute three curves: **nominal**, **failed-no-recovery**, **failed-with-recovery**. The headline result is recovery vs no-recovery, not an absolute number.
- Do not promise a threshold (like 80%) until measured; then state the measured value.

### 3.5 Fault-tolerance / systems engineer
Failure detection: each sat emits a heartbeat; declare failure after K missed ticks; log detection latency = t_detect − t_fail. Failure modes: `DEAD` (no comms, no thrust, coasts) required; `THRUSTER_OUT` (reports, cannot maneuver) optional.
State machine: `NOMINAL → FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED`, with every transition logged with sim time.
Replan must not block the sim: sim core is a pure function `step(state, commands, dt) -> state`; the replanner runs between steps with a timeout guard.
Determinism: fixed seed, no `time.time()`, no unordered iteration, stable sort. Two runs of the same scenario must produce byte-identical JSONL (check by SHA-256 in a test).

### 3.6 Visualization engineer
Plain Three.js, one page. Scene: chief at origin, 6 cubes, slot ghosts, trailing orbit lines, footprint discs on a ground plane, coverage heat overlay.
States must be unambiguous from the back of a room: failed = red + label "FAILED t=…", still visibly coasting; replanning banner; new slot ghosts appear; survivors' paths animate to them.
Dashboard: coverage (3 curves), min separation, Δv per sat, state-machine timeline, detection latency. Font ≥18px. Target 60 FPS, must hold >30.
Time scaling: one orbit is ~95 min; play sim at adjustable speed (default ~100×) and show sim clock.
Vendor `three.module.js` into `static/vendor/`. Loading from a CDN at a venue is an avoidable risk.
UI controls: scenario dropdown, play/pause/speed, "kill satellite" click (live mode), **Replay** toggle, seed display.

### 3.7 DevOps / deployment engineer
Commands that must work from a clean clone:
```
uv sync --frozen
uv run pytest
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
uv run uvicorn cubesat.api:app --port 8000
```
Dockerfile: uv base image, `uv sync --frozen --no-dev`, non-root, healthcheck on `/health`, `PORT` from env.
Primary deploy: single Docker service (Render or Fly.io; check current free-tier limits and cold-start behavior BEFORE choosing; free tiers may sleep). FastAPI serves `/api`, `/ws`, and `static/`.
Fallback deploy: static mirror (GitHub Pages or Cloudflare Pages) containing the frontend plus committed `replay/*.json`. The frontend auto-falls back to replay if the WS fails. Ship both URLs in the README.
Precompute and commit replays for every scenario. Before the demo, hit the URL to warm it up.

### 3.8 QA / verification engineer
Test suite (each is a gate criterion):
- `test_hcw_stm_vs_ode`, `test_drift_free_ellipse_closes`, `test_cw_vs_kepler_error_report`
- `test_pd_step_response`, `test_saturation_respected`, `test_passive_slot_low_dv`
- `test_hungarian_deterministic`, `test_rectangular_assignment`, `test_leader_reelection`, `test_greedy_fallback_not_better`
- `test_coverage_monotonic_in_sats` (removing a satellite never raises coverage)
- `test_min_separation_never_below_threshold` (including dead sats as obstacles)
- `test_run_is_byte_deterministic`
- `test_scenario_schema_rejects_bad_input`
Regression: `nominal.json` short run compares against a committed golden hash.

## 4. Scenarios (`data/scenarios/*.json`, pydantic-validated)
`nominal`, `one_failure`, **`two_failure` (primary demo)**, `critical_role_failure` (leader dies + one more), `timeout_fallback` (forces greedy). Fields: sats, roles, slots, chief orbit, a_max, gains, sensor params, failures `[ {t, sat_id, mode} ]`, seed.

## 5. Log schema (JSONL, versioned)
One line per tick: `{v, t, state, sats:[{id, role, status, r, v, dv_used}], coverage, min_sep, event?}`. Events carry type and payload (`FAILURE_DETECTED`, `ASSIGNMENT`, …). Decimate for WS streaming (~30 Hz wall).

## 6. Phase gates and time-boxes
| Gate | Deliverable | Pass criteria | Box |
|---|---|---|---|
| G0 | uv project, ruff, pytest, CI, repo skeleton, one Dockerfile that builds | `uv run pytest` green in clean clone | 1h |
| G1 | HCW STM + passive ellipse + Kepler cross-check | 3.1 tests pass, error number recorded | 3h |
| G2 | PD controller with saturation and Δv | 3.2 tests pass | 3h |
| G3 | Coverage metric + 6-sat nominal run + JSONL logger | coverage curve sane, deterministic hash | 3h |
| G4 | Failure injection, detection, formation selection, Hungarian, state machine, baseline comparison | two_failure: recovery curve > no-recovery curve, min-sep held, all 3.3/3.5 tests pass | 6h |
| G5 | FastAPI + WS + replay endpoint + Three.js UI + dashboard | runs locally live AND from replay | 6h |
| G6 | Deploy primary + static mirror | both URLs work from a phone on mobile data | 3h |
| G7 | README, ARCHITECTURE.md (limitations!), reproduce command, demo video, pitch numbers pulled from logs | every README number traceable to a log | 3h |
Slack is deliberate. If G4 slips, cut UI polish, never cut the baseline comparison or the tests.

**Schedule:** Sep 28 (today): G0–G3 and start G4. Sep 29: finish G4, G5. Sep 30 until 18:00: G6, G7, rehearsal. Freeze at 18:00. Oct 1: submit.

## 7. Honesty section (must appear in README)
State plainly: linearized HCW with circular chief; no J2, drag, or attitude dynamics; ideal comms and sensing; centralized replanner; coverage defined as X; results are simulation-only; nonlinear cross-check error = (measured value).
If asked "is it hardcoded?" the answer is: scenarios are external JSON, allocation is computed, logs are reproducible by one command.

## 8. Anti-goals
No CBBA, no APF, no poliastro, no React, no Parquet, no Prometheus, no OAuth, no msgpack, no GPU, no real hardware. Do not build a general orbital simulator.

## 9. First action
Do G0 now. Reply with the G0 report in the format from section 1.8, plus a list of any locked decision you think is wrong and why. Then proceed to G1 only after I say go.

---

## Research patches (UPDATE from source-verification, 2026-09-28 — overrides conflicting items above)

VERIFIED (user opened the sources):
- The HCW STM matches USU Phillips Eq. 9 and Xue et al. (Sci Rep 2025) Eq. 2. Still test vs ODE in G1.
- Drift-free vy0 = -2n*x0 and the 2:1 ellipse are confirmed (Schaub AAS 03-115, Eq. 4).
- scipy linear_sum_assignment supports rectangular matrices; docs are silent on ties, so keep the determinism test.
- poliastro was archived Oct 2023, so it stays excluded.

CHANGES:
1. a_max default: 1e-4 -> 1e-2 m/s^2 (cold-gas class, ASSUMED ~8 kg / ~150 mN, label it an assumption). Keep it a scenario param. Reason: t >= 2*sqrt(d/a) gives ~2 orbits for a 10 km move at 3e-4 but ~0.3 orbit at 1e-2. Log the lower bound per reconfig.
2. Footprint: half-angle ~1-2 deg (r_f ~9-17 km at 500 km), not 3-5 deg. Design target: with 2 sats dead and NO recovery, coverage drops visibly (aim for >=15 percentage points). If it doesn't, change slot spacing or FOV, never the metric definition. Add test_two_failures_reduce_coverage_visibly.
3. Render free tier spins down after 15 min without incoming HTTP or incoming WebSocket messages from an existing connection. Server-to-client streaming does NOT count. The frontend must send a ping every 30s. This doesn't help the first cold load, so add a /health warm-up step to the README demo checklist.
4. Docker: use `uv sync --locked` (not --frozen) and pin the uv image tag.
5. README limitations: "dead sat stays bounded" holds only in linear unperturbed HCW; J2 and drag cause drift. Include the measured CW-vs-Kepler error.

NOT verified, so don't cite: CW validity ranges from papers, thruster mass figures, any hackathon rule about simulators.
