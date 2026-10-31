# KINTSUGI-6 v2 — Master Upgrade Map

(Verbatim from the user, 2026-10-31. Saved from the pasted message because the file was not on disk. This map supersedes the phase ordering of docs/superpowers/specs/2026-10-31-physics-v2-brief.md; that brief's §4 formulas stay valid and are referenced here as "PV2 §4.x".)

## 0. HOW TO WORK

You are the ORCHESTRATOR for the KINTSUGI-6 v2 upgrade: a CubeSat swarm self-healing simulator for a hackathon final (live demo + pitch). Problem statement: "When 2 of 6 satellites in a formation fail, dynamically reassign roles among survivors to maintain mission-critical coverage."

You own everything now. Antigravity is stopped.

Run `git fetch origin`.
If origin/phase0-fixes exists: create v2 from it and verify Phase 0 (§5).
If it doesn't: create v2 from origin/master and do Phase 0 yourself. It's small:
- the one-line like-for-like fix in allocate.replan (cov_curr scored with seats);
- remove the sys.platform hash maps in tests/test_cli.py, tests/test_failure_modes.py and tests/test_oracle_sweep_v3.py, replacing them with one canonical-hash helper;
- the critical-role metrics plus critical_vacancy_s;
- the flaky-test fix;
- the frontend CI step;
- the GATES.md rows.

Your existing docs/superpowers/plans/2026-10-31-physics-v2-plan.md is good. Keep it as the physics track and apply the changes in §10 below. This map adds the other tracks and sets the overall order.
One git worktree per track when two tracks run in parallel: ../wt-backend, ../wt-frontend.
Never push to master. Never merge without the user's OK.
Commit message: `v2: <track><phase> — <summary>`.

Skills / plugins to use.
- superpowers workflow: brainstorming → writing-plans → subagent-driven-development → test-driven-development → systematic-debugging → verification-before-completion → requesting-code-review.
- frontend-design for UI.
- Playwright (already a dev tool on this machine via the frontend toolchain, or the Playwright MCP if installed) for screenshots and visual QA.
- The Ponytail ladder for every change: YAGNI → reuse existing code → standard library → already-installed dependencies → guard clauses → minimal code, files ≤ 300 lines, small diffs.

Subagents. Fresh context each. Reviewers see only the diff, this map and the test output, never the implementer's reasoning.

| Agent | Job | May edit code? |
|---|---|---|
| PLANNER | Turns this map into docs/superpowers/plans/2026-10-31-v2-plan.md: tasks, files, tests, acceptance | no |
| IMPLEMENTER-BE / IMPLEMENTER-FE | One phase at a time, tests first | yes |
| SIMPLIFIER | Executes Track S removals with the Ponytail ladder; proves nothing breaks | yes (deletions/merges only) |
| PHYSICS-VALIDATOR | Re-derives every formula in the phase from first principles in its own scratch script; reports numbers | no |
| ADVERSARIAL-REVIEWER | Tries to break the phase: simultaneous failures, all-but-one dead, zero fuel, 100% packet loss, cancel/seek mid-run, offline network, 24 sats. Checks every claimed number. Returns a defect list | no |
| VISUAL-QA | Playwright screenshots/video at 1920×1080 and 1280×720 (projector). Answers: "Can a judge 4 m from the screen see what failed, what the swarm decided, and that it recovered — in under 10 s, without narration?" | no |
| BENCHMARK-RUNNER | Runs pre-registered benchmarks exactly as written; cannot change thresholds | artifacts only |

Phase loop.
1. PLANNER task list.
2. IMPLEMENTER, tests first: watch each test fail for the right reason.
3. Gates: `uv run ruff check .`, `uv run python -m pytest -q -m "not slow"`, `cd frontend && npm run build`, hex grep clean.
4. PHYSICS-VALIDATOR + ADVERSARIAL-REVIEWER (+ VISUAL-QA for UI) in parallel.
5. Fixes, then gates again.
6. Commit, then STOP and report: diff stat, test tail, reviewer reports, screenshots, every new number with its command.

Non-negotiable rules (AGENTS.md, plus these):
- No number without a committed artifact and the command that produced it. Unmeasured → "unmeasured". Never pre-state a result. Never pick a "headline" case after seeing the results.
- Determinism. Same scenario + seed + injection list ⇒ identical log. No wall clock inside the sim. The only randomness is one numpy.random.Generator(PCG64(SeedSequence(seed))) owned by the engine, drawn in a documented order.
- v1 stays reproducible. Scenario field engine: "v1" | "v2", default "v1". v1 canonical hashes stay unchanged until the user approves retiring v1.
- SI units internally; LVLH frame (x radial, y along-track, z cross-track).
- Don't touch files/** or models/**, or the landing page files (frontend/src/components/landing/*).
- No new dependencies except those the user approves in §9 "Decisions".
- Hex colours only in frontend/src/styles/tokens.css.
- The demo must work offline. Every network feature has a committed snapshot fallback.

## 1. VERIFIED GROUND TRUTH (as of 2026-10-31)

All figures come from independent runs on master eb6c9f1, plus the one-line like-for-like do-no-harm fix (cov_curr scored with seats).

| Fact | Value |
|---|---|
| 15 two-failure pairs, hungarian final-orbit coverage | 0.2698 in all 15 |
| do_nothing mean coverage | 0.2911 |
| Critical roles (leader AND downlink on a NOMINAL sat) held at the end | hungarian 15/15, do_nothing 6/15 |
| Imaging coverage-hours: wait-for-ground (5400 s) vs autonomous | ground ≥ autonomous in 10/15 pairs. The metric rewards keeping imagers and ignores command/downlink |
| Hungarian worst in-flight min separation | 1,852.5 m, pairs (3,4) and (3,5), under the 2 km rule |
| Hungarian max per-sat Δv | 251.2 m/s against a 200 m/s budget |
| Wait-for-ground baseline | max Δv 389.6 m/s; min separation 1,560.9 m |
| eps_leader_6sat (the leader-handover demo) | two healthy sats (4, 5) pass 868 m apart at t = 2746 s; evasion fires |
| cascading_n8 | max Δv 258.5 m/s; the final do-no-harm hold moves the leader 0→3 and the downlink to sat 5 although sat 0 is healthy |
| two_failure with dv_budget_mps: 30 | crash: RuntimeError: no feasible survivor formation, no log |
| 5 of 6 dead | final state RECOVERED with coverage 0.0 |
| Time before the first live frame (full precompute) | 6 sats 4.6 s · 12 sats 11.6 s · 24 sats 32.2 s. Paid again on every injection |

## 2. PROBLEM MAP

Severity: P0 demo-breaking or invalidates a claim · P1 wrong result · P2 quality. "→" names the phase that fixes it (see §5).

### A. Dynamics / physics
| ID | Sev | Where | Problem | → |
|---|---|---|---|---|
| A1 | P1 | hcw.py, sim.py | Linear CW is used as truth. Dead sats never drift away (no drag); no J2 | P1 |
| A2 | P1 | sim.py:134 build_slots | z in phase with x → not passively safe (5.9–11.8 m worst under drift) | P5 |
| A3 | P1 | scenarios | a_max 0.1 m/s² in failure scenarios contradicts pd.py's own stated assumption (~8 kg, 150 mN ≈ 0.019 m/s²). PD needs it; physics doesn't | P5 |
| A4 | P1 | pd.py | Fuel is Σ‖u‖dt with no propellant mass, no rocket equation, no fuel-out | P2 |
| A5 | P2 | hcw.py:116 | stm() and forcing_matrix() are rebuilt on every call (per sat per tick, plus per slot reference, plus the settle check). This is the main CPU cost | L1 |

### B. Recovery / allocation
| ID | Sev | Where | Problem | → |
|---|---|---|---|---|
| B1 | P0 | allocate.py:179 | No feasible formation → RuntimeError kills the run and a live session. Realistic fuel (~20 m/s) makes v1 unrunnable | R1 |
| B2 | P1 | allocate.py:260 | Reachability uses the full dv_budget_mps, not remaining fuel | R1 |
| B3 | P1 | allocate.py:115 | Δv estimate 2√(d·a_max) is free-space bang-bang: it grows with thrust (backwards) and underestimates PD 5–10× | P5 |
| B4 | P1 | sim.py:469 | except TypeError: re-calls replan without current_slots. Any TypeError bug silently disables do-no-harm | S |
| B5 | P1 | allocate.py:267 + sim.py:487 | Do-no-harm hold relabels roles by list index onto sats in their old seats. Causes needless leader/downlink handovers (cascading_n8) | R1 |
| B6 | P1 | allocate.py:60 | "Critical" = any role unique in the original roster (implicit). One survivor can't hold leader + downlink; they overwrite each other → 4 dead = 0 coverage | R2 |
| B7 | P1 | sim.py:510 | A DEGRADED sat's preserved seat is appended without a separation check | R1 |
| B8 | P1 | sim.py:606 | Evasion: away from the nearest sat only (can push into a third), no return-to-seat, can chain forever beside drifting debris, never triggers a replan; 1 km trigger vs 2 km planning floor | R1 |
| B9 | P1 | allocate.py:82 | Separation is checked on destination seats only, not on transfer paths (1,852 m in flight) | P5 |
| B10 | P1 | sim.py (THRUSTER_OUT) | Failed sats keep their role label → duplicate leader/downlink (thruster_leader_6sat, cascading_n8) | R2 |

### C. Detection / state machine
| ID | Sev | Where | Problem | → |
|---|---|---|---|---|
| C1 | P0 | sim.py:573 | RECOVERED is position-only at 5% of the largest transfer: 1,092 m off at 7.75 m/s still counts. RECOVERED is also declared with 0 coverage (mission lost) | R1 |
| C2 | P1 | sim.py:265 | Degrade-trigger "no oracle" is false: failing_soon reads scenario.failures (the future schedule) | S/R3 |
| C3 | P1 | sim.py:395 | Oracle hook reads the true failure schedule. The research sweep showed ~0 coverage benefit at +191% fuel | S |
| C4 | P1 | predictor | LightGBM predictor reads scenario.failures (leakage); display-only; EWMA also scores 31/31 | S (decision D2) |
| C5 | P1 | sim.py:318 | Heartbeat-only detection, K=3: with 5% packet loss → 0.34 false declarations per sat per orbit | P4 |
| C6 | P2 | sim.py:383 | Event FIFO pops one event per tick, so simultaneous events are logged seconds late | L1 |
| C7 | P2 | scenario.py | seed is logged but never used | P0/L1 |

### D. Evaluation / claims
(+ evaluation-audit findings, merged below in §2-bis)
| ID | Sev | Problem | → |
|---|---|---|---|
| D1 | P0 | "Headline pair (1,2)" coverage-hours pick is post-hoc; ground wins 10/15 | Phase 0 |
| D2 | P0 | Coverage metric is a flat-disc union in the LVLH y–z plane (13.1 km footprints, 8 km formation, fixed 60×60 km grid). It measures imager spread, not area imaged; no Earth rotation, no ground track, no downlink | P6 |
| D3 | P1 | There is no metric for what the problem statement asks ("mission-critical"). Fix: critical_vacancy_s, critical_roles_held | Phase 0 |
| D4 | P1 | The "44% EPS" misquote, "72 formations" (it's 12), "8 seconds", "AI predicts and heals" | D |

### E. Live / server / performance
(+ server-audit findings, merged below in §2-bis)
| ID | Sev | Problem | → |
|---|---|---|---|
| E1 | P0 | "Live" is not live: the whole run is precomputed before the first frame, and every injection recomputes from t = 0 (4.6 s / 11.6 s / 32.2 s at 6 / 12 / 24 sats) | L1 |
| E2 | P1 | CelesTrak import uses only mean motion (altitude). Inclination, RAAN and epoch are dropped, so "real orbit" is cosmetic | L2 |
| E3 | P1 | The live-import fit puts real objects that are 100+ km apart (GRACE-FO 2 at ~190 km along-track) into CW. CW curvature error alone ≈ y²/2r ≈ 2.6 km | L2 |

### F. Frontend / visual
| ID | Sev | Where | Problem | → |
|---|---|---|---|---|
| F1 | P0 | sceneSatellites.ts:58 lvlhToScene global | The Earth view maps each sat's phase on its 8 km ellipse to a position around the entire orbit. The formation is never shown; a re-seat looks like a tiny slide along a planet-sized ring. Judges cannot see recovery | V1 |
| F2 | P1 | — | No visual for: the planned transfer, old vs new slots, who took which role, the certificate, the time-to-recover | V2 |
| F3 | P1 | dashboard/*.tsx | Charts re-render from full growing arrays on every WS frame (30 Hz). Profile, then throttle and decimate | L3 |
| F4 | P2 | pages/Docs/Faq/Tutorial | Copy repeats claims that are now wrong (THRUSTER_OUT "does not replan", predictor claims) | S |

### G. Repo hygiene / redundancy (Track S)
Listed in §6.

## 2-bis. PHASE A — FINISH THE AUDIT YOURSELF (run in parallel with Phase 0; read-only)

The server/live layer and the evaluation/claims layer haven't been fully audited yet. Spawn three read-only subagents with fresh context. Each writes to docs/audit/2026-10-31-<a|b|c>.md.

**A — Frontend + wire.** Scope: frontend/src/** vs cubesat/wire.py and session.py. Find:
- type/wire mismatches, and statuses or events the UI can't render;
- store bugs: stale frames, seek, reconnect;
- UI numbers with no committed artifact, and hard-coded claims in copy;
- 3D memory leaks on route change;
- build warnings.

**B — Live + deploy.** Scope: cubesat/api.py, session.py, live_import*.py, cluster_import.py, _live_network.py, predictor/runtime.py, the Dockerfile and CI.
Run the server, open 3 sessions, inject 4 failures each, cancel mid-run, reconnect, and upload malformed and huge scenarios.
Report crashes, hangs, memory growth, wrong 4xx/5xx codes, upload or path-traversal holes, and anything that breaks on a deployed host (TrustedHost, wss, PORT).

**C — Evaluation + claims.** Scope: benchmark*.py, monte_carlo.py, pareto.py, dv_bound.py, cw_curve.py, keepout.py, coverage.py, data/eval/*.
Flag metric definitions that are biased, baselines that are strawmen, and Monte Carlo seeds that aren't really varied.
Re-derive the formulas.
Re-run the cheap commands of record.
Fill a table for every number in README, GATES, JUDGE_PREP, PHYSICS_ENGINE_EXPLAINED and the frontend copy: claim | file:line | command | reproduces? | actual.

Rules for all three:
- Every finding needs a severity, file:line, a reproduction command + output snippet, and a one-line fix.
- Skip anything already in §2 (cite its ID if you add evidence).
- Merge all three into §2 of your plan as new IDs (E4…, F5…, D5…) and assign each to a track.

## 3. DECISIONS THAT HAVE BEEN OUTGROWN → REPLACEMENT

| # | Old decision | Why it's outgrown | Replace with |
|---|---|---|---|
| 1 | Linear CW is the world | Can't show drag drift, J2 or realistic fuel; dead sats never leave | CW / Schweighart–Sedwick = planning model; ECI two-body + J2 + drag RK4 = truth (PV2 §4 Phase 1) |
| 2 | PD flies transfers | Needs 0.1 m/s², ~155 m/s per transfer | LP fuel-optimal plan + MPC; PD only for terminal hold (PV2 §4 Phase 5.4) |
| 3 | Precompute whole run, then "stream" | Slow, injection = full recompute | Stepping engine with step() / inject() / snapshots (L1) |
| 4 | Heartbeat-only detection | False alarms, can't tell a glitch from death | Heartbeat + telemetry + χ² motion residual (PV2 §4 Phase 4) |
| 5 | Roles = strings; critical = unique | Implicit; no stacking; 4 dead = 0 | Role spec + capability matrix (R2) |
| 6 | Binary RECOVERED | Says healed when mission is lost | Mission states + recovery ladder L0–L5 (R1) |
| 7 | Coverage fraction on a plane | Not what a customer buys | critical_vacancy_s, delivered coverage, SLA minutes, fuel-lifetime (P6) |
| 8 | One in-plane ellipse | Not passively safe | Cross-track phase ψ = 30° (PV2 §4 Phase 5.3) |
| 9 | ML predictor in the product | Leaks ground truth; EWMA ties it; display-only | Retire from the product; the physics detector replaces it (decision D2). Pitch: "we removed our ML model because a physics residual does the job with no training data and every alarm explainable" — only after P4 measures it |
| 10 | Oracle hooks in the sim | Reads the future; no measured value | Remove from sim v2 and UI; keep the research scripts in files/ |
| 11 | Global view mapping | Fake geometry | True two-scale view (V1) |
| 12 | Per-platform golden hashes | Unmaintainable | Canonical hashes (Phase 0) |
| 13 | Live = a hypothetical swarm on an altitude only | Cosmetic "real" | Real chief elements via SGP4, real-sky view, real incidents (L2, I) |

## 4. v2 ARCHITECTURE

```
cubesat/
  engine.py        SimEngine: step(), inject(failure), snapshot()/restore(), run() -> lines   [L1]
  v1_step.py       v1 tick logic moved verbatim out of sim.py (byte-identical)                  [L1]
  truth.py         ECI RK4: two-body + J2 + drag (PV2 §4 Ph1)                                 [P1]
  frames.py        ECI<->LVLH, chief propagation, SGP4 seeding (if D1 approved)               [P1/L2]
  spacecraft.py    propellant (rocket eq.), power/eclipse, modes, capability flags (PV2 Ph2)  [P2]
  hazards.py       seeded SEU / impact / aging (PV2 Ph3)                                      [SHOULD]
  detect.py        heartbeat + telemetry + chi^2 residual classifier (PV2 Ph4)                [SHOULD]
  roles.py         RoleSpec + capability matrix + stacking + rotation                        [R2]
  ladder.py        recovery ladder L0..L5 policy, picks the cheapest certified option         [R1]
  transfer.py      LP fuel-optimal transfer + MPC (PV2 Ph5.4)                                 [P5]
  certify.py       truth-model forward check -> CERTIFICATE event (PV2 Ph5.5)                [P5]
  metrics.py       critical_vacancy_s, delivered coverage, SLA, fuel-lifetime (PV2 Ph6)       [P6]
  incidents.py     load data/incidents/<id>/, build "as-flown" + "KINTSUGI" runs              [I]
  sim.py           thin: run_scenario(s) = list(SimEngine(s).run())  (keeps v1 API)
```

SimEngine contract (L1). This is the backbone of fast Live, seek and incidents.
- SimEngine(scenario, injections=[]).
- .step() -> line: advance one tick.
- .inject(failure): applies at the current tick and is recorded in self.injections.
- .snapshot() -> bytes and .restore(bytes): full state including RNG state.
- .run(): generator.

Determinism contract: replaying SimEngine(scenario, injections) from t = 0 gives the identical log. That is how a live session is saved and replayed.

Wire additions (all optional fields; old clients keep working).
- Per-sat: fuel_mps_left, soc, mode, caps, roles: [..].
- ASSIGNMENT carries plan_samples (planned transfer positions every 60 s, ≤ 120 points per sat), old_slots and new_slots.
- New events: CERTIFICATE, RECOVERY_LEVEL, MISSION_STATE, ROLE_HANDOFF {role, from, to, reason}.

## 5. TRACKS AND PHASES (in order, with cut lines)

MUST = needed for the demo. SHOULD = do if time allows. ROADMAP = slide only.

### Phase 0 — Antigravity's phase0-fixes (verify, don't redo)
Check that it contains:
- the like-for-like do-no-harm fix;
- canonical hashes;
- critical_roles_held_end / critical_seat_frac / imagers_end / critical_vacancy_s;
- the flaky-test fix and the frontend CI step;
- GATES.md known issues.

Re-run, then add what's missing:
- Re-run the 15-pair benchmark yourself; expect hungarian 0.2698 ×15 and critical roles 15/15 vs 6/15.
- Add the F3 duplicate-role fix: a sat that leaves NOMINAL drops its critical role label (keep original_role for display). Assert exactly one leader and one downlink among NOMINAL sats after every ASSIGNMENT. (See §10 Q5: do this in v2 only; v1 keeps its labels.)

### S — Simplify first (MUST, before building; SIMPLIFIER agent)
Removals are in §6. Gate: every v1 canonical hash unchanged, all tests green, the frontend builds. Each removal is its own commit with a one-line reason.

### L1 — Stepping engine + performance (MUST)
Engine refactor.
- Move the tick body of run_scenario into SimEngine.step() without behaviour change.
- Golden test: v1 logs byte-identical for every committed scenario.

Speed-ups, each with a before/after benchmark (--mode perf, committed JSON):
- Cache Φ(dt) and G(dt) once per engine.
- Propagate all sats as one (N×6) matrix product.
- Use scipy.spatial.distance.pdist for min_sep.
- Slot references: Φ(t) once per tick applied to all slots.
- Replan sweep: vectorize the 72-sample loop.

Session rewrite.
- Live sessions drive SimEngine incrementally in a worker thread, a fixed number of ticks ahead of playback (≈ 10 s buffer).
- Injection = engine.inject() at the playback tick; discard the buffered ticks after it.
- Seek back = restore the nearest snapshot (every 300 ticks) and re-step.
- Fixes the EPS live-injection bug for free (the fade starts at t_now and plays forward).

Targets (measure, then report actuals):
- First frame < 300 ms at 6 and 24 sats.
- Sustained ≥ 100 ticks/s at 24 sats.
- Injection-to-first-new-frame < 200 ms.

Fix C6. Allow multiple events per tick line (events: [...], keep event = first for old clients).

### L3 — Frontend performance (MUST)
- Profile first: Chrome Performance, record 30 s of live at speed ×100. Report long tasks and fps.
- Then:
  - keep 3D updates outside React (refs, one rAF);
  - throttle charts to ≤ 4 Hz;
  - decimate series to ≤ 600 points (LTTB or stride);
  - cap trail lengths;
  - memoize panels.
- Target: 60 fps at 1920×1080 on the demo laptop; no long task > 50 ms.

### P1 — Truth model (MUST) — PV2 §4 Phase 1 verbatim
Chief elements become real: inclination_deg, raan_deg, epoch_utc. When imported from CelesTrak, take them from the OMM (L2).

### P2-lite — Resources (MUST: propulsion + fuel-out; SHOULD: power/eclipse/modes) — PV2 §4 Phase 2
Defaults: a realistic 3U (Isp 40 s, 0.2 kg propellant → 20.1 m/s), F_max 0.04 N.

### P5 — Geometry + transfers + certificate (MUST) — PV2 §4 Phase 5.3–5.7
- ψ = 30° default in v2.
- LP + MPC transfers with keep-out.
- Certificate over 2 orbits, including dead-sat drag drift.
- RECOVERED v2 = ‖Δr‖ ≤ 50 m AND ‖Δv‖ ≤ 0.05 m/s for 60 s.
- The planned transfer samples go into the ASSIGNMENT payload for V2.

### R1 — Recovery ladder + mission states (MUST)

Mission states: NOMINAL → FAILURE_DETECTED → PLANNING → RECONFIGURING → RECOVERED | DEGRADED_MISSION | MISSION_LOST.

Recovery ladder: try the levels in order and pick the first whose plan passes the certificate and keeps the role-priority requirements. Emit RECOVERY_LEVEL {level, reason, rejected: [{level, why}]}.

| Level | Name | Action | Typical cost |
|---|---|---|---|
| L0 | Hold | Suspected glitch/reboot: wait T_grace, no maneuver (needs P4 SUSPECT; until then K-tick confirm) | 0 Δv |
| L1 | Role swap | Reassign roles among sats in place (leader is software; stacks) | 0 Δv |
| L2 | Local re-seat | Move only the sats whose seats are needed; others stay | low Δv |
| L3 | Re-formation | Full k-slot formation search (ψ sweep) | higher Δv |
| L4 | Degraded mission | No certified plan meets the requirement → best certified reduced mission; state DEGRADED_MISSION, reported honestly | — |
| L5 | Retire / dispose | A failing sat with fuel left burns to lower its orbit before death (graceful retirement); report its decay time vs the FCC 5-year rule | sat's own Δv |

Also in R1:
- Never crash (fixes B1): no feasible plan → L4 / hold + MISSION_STATE event.
- Do-no-harm becomes part of the ladder (L1/L2 compared like-for-like against L3).
- The ladder fixes B5 (no needless handovers: L1 keeps incumbents unless a capability requires a change) and B7/B8 (the certificate covers preserved seats; evasion → triggers replan + return-to-seat via the ladder).

"Move to the cripple" (MUST, the Starling-1 story). When a sat is THRUSTER_OUT/FUEL_DEPLETED but otherwise healthy, the L3 candidate set includes formations centred on the cripple's natural relative orbit (the cripple keeps its seat; the others come to it). Compare its Δv vs abandoning the cripple. The certificate picks.

### R2 — Roles as specs + capability matrix (MUST)
RoleSpec {name, critical: bool, stackable: bool, needs: {payload|radio|thrust|power_w}, priority} lives in the scenario. Defaults:

| Role | critical | stackable | needs |
|---|---|---|---|
| leader | yes | yes (software) | radio |
| downlink | yes | no | radio + power |
| imager | no (but counts toward the SLA) | no | payload + power |
| relay | no | yes | radio |
| spare | no | — | — (hot standby, takes any role) |

- Inspector is SHOULD: flies within N km of a dead sat to image it (the Proba-3 story).
- One survivor can hold leader + downlink (fixes B6, A-F6).
- Power-aware rotation (SHOULD): the downlink duty rotates to the sat with the highest SoC after each ground pass.
- Fuel balancing (SHOULD): the cost term penalizes lowest-remaining-fuel; metric days_to_first_reserve.
- Fixes B10: failed sats lose role labels; ROLE_HANDOFF events carry the reason.

### P6 — Mission metrics (MUST: vacancy + SLA; SHOULD: delivered coverage) — PV2 §4 Phase 6
- critical_vacancy_s (Phase 0) is the headline metric.
- sla_violation_min: minutes during which the imaging requirement (default: ≥ 2 nadir imagers AND a downlink-capable sat) is unmet.
- Delivered coverage needs ground passes (Bengaluru default, elevation ≥ 10°).

### V1 — Make the formation visible (MUST)
- Delete the fake global mapping in lvlhToScene.
- New two-scale view:
  - Earth globe with the true chief orbit: inclination/RAAN from the scenario, chief position from the truth model or SGP4 at the sim epoch. Show the ground track and the next ground-station pass.
  - A Formation Lens: a magnified inset anchored to the chief with a leader line to its position on the globe, drawn in true LVLH geometry. It has a scale bar (km), "↓ Earth" and "→ along-track" arrows, and a 2 km keep-out ring per sat.
  - The camera auto-transitions globe → lens when an event fires.
  - Reduced-motion fallback.

### V2 — Make the recovery visible (MUST)
On ASSIGNMENT, freeze-frame for 1.5 s (in sim-time warp) and draw:
- Old slots as dashed ghosts and new slots solid.
- Planned transfer arcs from plan_samples, coloured per sat.
- Role batons: the leader crown / downlink antenna icon flies from the old holder to the new one, with a ROLE_HANDOFF caption.
- Dead-sat drift cone: predicted drift over the certificate horizon.
- Certificate card: ✓ min separation X km · fuel margin Y m/s · roles OK · level L2.

Also:
- Director mode (toggle, default ON in presentation view):
  - auto camera cuts: failure close-up → pull back to the plan → time-warp through the transfer;
  - adaptive playback: slow near events, fast in cruise;
  - settle shot with a card "RECOVERED in mm:ss sim · Δv total Z m/s · leader on SAT-n · downlink on SAT-m".
- KPI strip:
  - critical-role vacancy timer (counts up in red while vacant, freezes green);
  - per-sat fuel bars;
  - min-separation gauge with the 2 km line;
  - mission-state pill.
- Before / after footprints: three small panels (before failure, after failure, after recovery) showing imager footprints on the ground.
- VISUAL-QA gate: three judges' questions, answered from screenshots alone.

### L2 — Live page that is actually live (MUST: real-orbit swarm + offline snapshot; SHOULD: real-sky view)
Rename the modes in the UI:

| Mode | What it shows |
|---|---|
| Live · Real orbit | Pick a real satellite (NORAD ID / name search over the CelesTrak cubesat and active groups) or enter custom elements → it becomes the chief. The sim epoch = now (UTC); the clock runs in real time ×1 by default with a time-warp slider, always labelled "sim ×N". The swarm (hypothetical, labelled so) flies around it in the truth model; you inject failures live. |
| Live · Sky (SHOULD) | Real current positions of real CubeSat clusters (e.g. TROPICS, Starling if still tracked, any group) on the globe from SGP4, refreshed from CelesTrak at most every 2 h (their etiquette). Read-only, honest "km-level public data". |
| Custom | The existing ScenarioBuilder, plus role specs, capabilities and fuel. |

Data rules:
- Commit data/celestrak/snapshot_<date>.json for offline demos.
- Cache in data/celestrak/cache/.
- Never block the UI on the network.

Honesty rules: never say we track a real formation live. Public orbit data (TLE/OMM) is ~km accurate. Real objects are only chiefs or context.

### I — Incidents (replaces the "Replay" page; MUST: 2 incidents; SHOULD: 4)
Each incident lives in data/incidents/<id>/, containing:
- incident.md: timeline, each line with a cited public source URL;
- orbit.json: GP/OMM snapshot, from the CelesTrak archive (free request form, emailed, 10 requests/day) or the current GP for still-flying objects;
- scenario_asflown.json: what happened, reconstructed;
- scenario_kintsugi.json: the same initial state and failure, our v2 policy;
- the two logs and metrics.json.

UI:
- split screen with a synchronized timeline: left "What happened (reconstruction)", right "KINTSUGI v2";
- event cards with source links;
- a metrics diff: critical vacancy, time to recover, Δv, min separation, mission state.

Banner on every incident: "Reconstruction from public sources. Simulated counterfactual — not a claim about what the real mission would have achieved."

| Incident | Real event (sources in incident.md) | Our counterfactual shows |
|---|---|---|
| starling-2023 (MUST) | NASA Starling: a propulsion leak left Starling-1 unable to maneuver and >3,000 km away; the other three maneuvered to it; ops took weeks | Move-to-the-cripple: certified plan, Δv comparison of rejoin vs abandon, time to formation |
| proba3-2026 (MUST) | ESA Proba-3 (launched on PSLV from Sriharikota, Dec 2024): Coronagraph lost attitude on 14 Feb 2026, failed to enter safe mode, drained its battery, went silent and drifted; the team studied steering the Occulter closer to diagnose it; contact was restored 18 Mar | Model-based detection (SUSPECT vs DEAD), power-safe hold, partner as inspector at a certified safe range, recovery when the sat returns. 2-sat case: honest that there are no roles to reassign; the point is detection and a safe approach |
| tropics-2022 (SHOULD) | NASA TROPICS: 2 of 6 CubeSats lost in the Astra launch failure (12 Jun 2022); the constellation was re-planned with 4 | The problem statement in the wild. Replay 2-of-6 at formation scale; clearly labelled as an analogue (theirs is multi-plane) |
| starlink-storm-2022 (SHOULD) | Feb 2022 geomagnetic storm raised drag; up to 40 of 49 newly launched satellites lost | A drag-density spike in the truth model; the certificate rejects plans that the storm drift invalidates; safe-mode/raise policy |

### P4 — Model-based detector + retire predictor (SHOULD; needs decision D2) — PV2 §4 Phase 4
- Measure detector vs predictor on the same runs: latency, false alarms, missed detections.
- Only then remove the predictor from the UI.

### P3 / P7 / P9 — Hazards, failure packs, pre-registered benchmark (SHOULD) — PV2 §4 Phases 3, 7, 9
- Add packs starling_cripple, proba3_blackout, storm_drag.
- Policies: do_nothing, wait_for_ground (delay from the ground-pass model, not a constant), hungarian_v1, kintsugi_v2.

### D — Deploy + docs + pitch numbers (MUST, last)
- Build the multi-stage Dockerfile; deploy (Render/Railway/Fly); set CUBESAT_ALLOWED_HOSTS; wss works.
- Rehearse the demo twice on the deployed URL and offline locally; record a backup video.
- README "Measured numbers" and docs/PITCH_NUMBERS.md: only numbers that passed, each with file + command.
- Remove: "72 formations", "8 seconds", "AI predicts and heals", "44% EPS", coverage-hours headline.

### ROADMAP (slide only)
Pc-based conjunction screening against the real catalog; inspector flyby imaging; SLA-driven tasking; decentralized leader election / consensus (NASA Starling's distributed autonomy); differential-drag station-keeping.

**Order if time is short:** Phase 0 → S → L1 → V1 → V2 → P1 → P2-lite → P5 → R1 + R2 → I (2 incidents) → L2 → L3 → D. Stop adding scope 24 h before the event; from then on only D.

## 6. TRACK S — REMOVE / MERGE (SIMPLIFIER; each item its own commit)

Verify each with git grep before deleting.

| Item | Action | Why |
|---|---|---|
| data/scenarios/live_6sat_2/_3/_4.json | delete | byte-identical to live_6sat except the name |
| cubesat/live_import_e2e.py, test_gate_fix.py, cubesat/_pytest_gate_fix.py | delete if unreferenced (grep pyproject.toml, CI, Dockerfile, tests first) | dead / one-off |
| sim.py duplicated comment block (≈ lines 390–394) and the except TypeError duplicate replan call | delete | dead code that hides bugs (B4) |
| Oracle hook + Oracle scenario block + ORACLE_ALERT from sim v2 and the UI | remove from v2; leave v1 code frozen until v1 is retired | reads the future (C3) |
| Degrade-trigger's failing_soon = scenario.failures | replace with "sats currently DEGRADED or SUSPECT" | leak (C2) |
| Predictor wiring in the UI (RiskPanel, suspect.ts, predictor toggles), session._install_predictor* | remove after P4 measurement + decision D2 | leakage, no value |
| docs/ prompts and one-off plans: FRONTEND_REDESIGN_PROMPT, KINTSUGI-6_*_prompt, hooks-proposal.json, physics-reviewer.md, frames/, superseded plans | move to docs/archive/ | 1.1 MB of overlapping text confuses agents |
| Docs/FAQ/Tutorial pages | merge into one "How it works" page whose numbers are read from PITCH_NUMBERS | stale claims (F4) |
| One-off eval modules no longer cited (check pareto, dv_bound, cw_curve, monte_carlo, keepout against PITCH_NUMBERS) | keep those that back a pitch number; move the rest to research/ | scope |
| graphify-out/ + the AGENTS.md rule requiring it | regenerate at the end, or drop the rule (decision D4) | stale graph misleads agents |
| AGENTS.md header (old dates, "only nominal.json exists today") | rewrite to the current state | stale onboarding |

## 7. PRE-REGISTERED CLAIMS

Commit to GATES.md before running.

- C1. kintsugi_v2 holds both critical roles in ≥ 95% of pack runs where ≥ 2 capable sats survive.
- C2. kintsugi_v2 never exceeds any sat's propellant (100% of runs).
- C3. 0 certified plans violate 2 km in truth-model replay.
- C4. two_dead: critical_vacancy_s with kintsugi_v2 vs wait_for_ground vs do_nothing (report all three, means + worst).
- C5. Run never crashes: 0 exceptions across all packs × seeds.
- C6. Live performance targets from L1/L3 (report actuals).
- C7. Incidents: report the metrics diff as measured, whichever way it goes.

## 8. PITCH-SAFE WORDING
- Say "certified self-healing: every plan is checked for fuel, collision and roles in a higher-fidelity model before it flies".
- Say "we couldn't find an open tool that does X". Never say "first", "novel" or "state-of-the-art".
- Failure statistics, exactly:
  - "Langer & Bouwmeester: EPS and communications together ≈ 44% of losses at 30 days";
  - "Swartwout: ~40% of university-class missions fail".
- Incidents: "reconstruction" and "simulated counterfactual" every time.

## 9. DECISIONS FOR THE USER (ask before acting)
- D1. Approve adding sgp4 (Python, MIT). Needed for real chief elements and the Sky view. Without it, Live uses Keplerian + J2-secular propagation from OMM mean elements (less accurate, but labelled).
- D2. Retire the LightGBM predictor from the product after P4 measures the χ² detector against it.
- D3. Retire the v1 engine after v2 passes C1–C5. Until then v1 stays byte-identical.
- D4. Drop or regenerate graphify-out/ and its AGENTS.md rule.

## 10. CHANGES TO YOUR PHYSICS PLAN + ANSWERS TO ITS OPEN QUESTIONS

**Architecture reconciliation (L1 vs "sim.py frozen").**
- Keep sim.py frozen with your 3-line seam. Don't refactor v1 into a stepper.
- Make sim_v2 stepper-native from Task 1.5: class EngineV2 with step(), inject(failure), snapshot()/restore() and run(). run_scenario_v2 = list(EngineV2(s).run()).
- Track L1 then applies to v2 only. Live sessions use v2 by default once Phase 5d is green; v1 stays precompute-only for reproducibility.
- Still do the L1 speed-ups (cached Φ(dt)/G(dt), vectorized propagation, pdist) inside v2.

**Order: interleave the plan's phases with the other tracks.**
Phase 0 → Phase A audit (parallel) → S → 1.1–1.5 (with EngineV2) → L1-v2 session streaming → V1 → 2.1 + 2.3 + 2.4 (2.2 power: SHOULD) → 5a + R2 roles → 5b ψ → 5c LP/MPC → 5d certificate + R1 ladder + move-to-cripple → V2 → 6.1 + vacancy/SLA → I (starling-2023, proba3-2026) → L2 → L3 → 8 (wire/frontend, merged with V1/V2) → 7 + 9 (packs + pre-registered benchmark, adding starling_cripple, proba3_blackout, storm_drag packs and the wait_for_ground policy, with its delay from the ground-pass model) → D.

Phases 3 (hazards) and 4 (detector) are SHOULD. If time is short they go after D, and the predictor stays hidden rather than removed.

**Answers to the open questions.**
- Q1. Pair (2,3): do_nothing 0.26981 vs hungarian 0.26980 is a 1e-5 tie. Compare with tolerance 1e-4 and state that in the test. After the fix it doesn't matter: hungarian is 0.2698 in all 15 pairs.
- Q3. The fix is one line in allocate.py. Verified independently: it alone reproduces 0.2698 ×15, critical roles 15/15 vs 6/15, and Antigravity's coverage-hours to 4 decimals. Any extra sim.py change needs its own failing test.
- Q4. Yes, remove all three hash maps. Use one helper, canonical_log_hash(lines, sig=9).
- Q5. Do the role-clearing in v2 only: failed sats get roles: [] and role: "none", plus original_role for display. The frontend shows "none" as grey "no role". v1 keeps its labels; the benchmark already counts NOMINAL holders only. No v1 golden churn.
- Q6. Agreed: harness RNG and engine RNG stay separate.
- Q7. Don't clamp. Implement the full Vallado exponential table, then cross-check every row against Vallado, Fundamentals of Astrodynamics and Applications, Table 8-4, and cite it in PHYSICS_V2.md.

| h0 km | ρ0 kg/m³ | H km |
|---|---|---|
| 150 | 2.070e-9 | 22.523 |
| 180 | 5.464e-10 | 29.740 |
| 200 | 2.789e-10 | 37.105 |
| 250 | 7.248e-11 | 45.546 |
| 300 | 2.418e-11 | 53.628 |
| 350 | 9.518e-12 | 53.298 |
| 400 | 3.725e-12 | 58.515 |
| 450 | 1.585e-12 | 60.828 |
| 500 | 6.967e-13 | 63.822 |
| 600 | 1.454e-13 | 71.835 |
| 700 | 3.614e-14 | 88.667 |
| 800 | 1.170e-14 | 124.64 |
| 900 | 5.245e-15 | 181.05 |
| 1000 | 3.019e-15 | 268.00 |

Above 1000 km use the 1000 km row; the schema's 2000 km max is far beyond any CubeSat formation here. Add a storm multiplier truth.density_factor (default 1.0; can be time-scheduled) for the starlink-storm incident.

- Q8. Agreed. Assert after :492, after :519, and after every swap, counting NOMINAL only. In v2, assert after every ASSIGNMENT and ROLE_HANDOFF.
- Q9. Yes, v2 default K = 5. With the P4 detector, K applies to "silence + ballistic" only.
- Q10. CI: run the full suite on ubuntu, the fast suite on windows; canonical hashes fix the divergence. Mark RK45 cross-checks slow.
- Q11. Re-verify every line number after Phase 0. Regenerate PHYSICS_ENGINE_EXPLAINED.md at the end, or archive it in Track S.
- Q12. Consistent: 0.337.

**Start:**
1. Phase 0 and the Phase A audit in parallel.
2. Then show me: the Phase 0 report, the merged problem map, and the updated plan with the order above.
3. No code past Phase 0 until I say go.

## 11. FRONTEND AUDIT + v2 CONSOLE SPEC (Track UI — merges V1, V2, L3 and plan Phase 8)

(Verbatim from the user, 2026-10-31, appended after the first save. Load the frontend-design skill before any UI work. The physics plan's Phase 8 ("minimal, no restyle") is replaced by this section.)

### 11.1 Backend data that never reaches the screen (verified in cubesat/wire.py)
| Backend has | Wire today | Fix |
|---|---|---|
| ASSIGNMENT method (hungarian / greedy / do_no_harm_hold), formation (amp, phase), transfer_lower_bound_s | dropped (only cost_total + assignments) | pass through; the UI shows "kept formation (no move)" for a hold, never as a re-plan |
| Previous role of each sat | not computed | wire derives old_role from the prior frame → ROLE_HANDOFF baton |
| SUMMARY coverage_mean_last_orbit | replaced by the text "Run complete" | send it as a run_summary message |
| DEGRADE_START, ORACLE_SWAP, ORACLE_ALERT | the bare type string | plain sentences (round-2 Phase 3 text). ORACLE_* are removed in v2 (Track S) |
| STATE transitions | "State REPLANNING -> RECONFIGURING" (raw enums) | structured {from, to}; the UI owns the wording |
| metrics.replanning_latency_ms | always None (wire.py:34) | delete the field and its UI paths |
| One event per tick | simultaneous events arrive seconds apart | events: [] (L1) |

### 11.2 Backend + planner gaps the UI needs (add to the plan)
- Chief absolute state per frame: chief: {r_eci, lat, lon, alt} plus epoch_utc in hello. The globe can't show the true orbit without it (V1).
- Plan payload on ASSIGNMENT (v2): plan_samples, old_slots, new_slots, dv_planned per sat, level, rejected: [{level, why}], certificate {...}. This drives the decision card and the arcs.
- Mission KPIs in every sim_state: roles_held: {leader: id|null, downlink: id|null}; critical_vacancy_s (running); mission_state; t_since_failure; per-sat fuel_left_mps, fuel_budget_mps, soc, mode.
- Hello metadata: role specs, budgets, scenario description, engine.
- Counterfactual shadow (MUST, cheap with EngineV2): the session also steps a do_nothing twin from the same state and sends shadow: {critical_vacancy_s, coverage, roles_held}. The UI shows "Without recovery: leader vacant for 41:20". This is the single most persuasive element on stage.
- Incidents API: GET /incidents, GET /incidents/{id} (timeline + sources), and a paired replay stream of two logs on one clock.
- Live real-orbit API: GET /orbits/search?q= (CelesTrak cache, offline snapshot fallback), POST /simulation/start with {norad_id | elements}.
- Anomaly report: GET /session/report → JSON (and the UI renders a printable page): what failed, detection time, decision + rejected options, Δv, certificate, vacancy, outcome.
- Contract tests: a golden wire fixture per new message type; the frontend deserializer has a vitest test per type.

### 11.3 AI filler and stale copy found (remove or rewrite; each is a P1 for judges)
| Where | Text today | Problem → fix |
|---|---|---|
| live/*Field tooltips | "(cubesat/scenario.py Formation)", "(spec 7.5)", "(repo invariant 2)", "MASTER_PROMPT 3.4", "the validator allows 0 < dt <= 10" | Internal file paths and spec refs in user copy. Write what the setting does in one plain sentence; no file names |
| controls/FailureInjectionPanel | "Keeps sending heartbeats but cannot maneuver (reactive heartbeat detector does not replan)" | False (THRUSTER_OUT self-reports and replans). Use "Thrusters fail; the satellite reports it and the swarm replans" |
| FailureInjectionPanel / FailureRow | "DEAD (triggers autonomous replanning)", "THRUSTER_OUT …", "EPS_DEGRADE (gradual power death)" | Raw enums. Labels "Satellite dies", "Thrusters fail", "Battery fades". Enums only in the data |
| dashboard tooltip | "Measured P0 benchmark: +4.93 coverage pts … (mean −2.13 pts during transit)" | Stale numbers (current: 0.2698 all pairs). Numbers come only from PITCH_NUMBERS with a source link |
| pages/DocsPage | "recovery complete at t = 3114 s, worst separation 3095.1 m" | Premature RECOVERED (1,092 m off); one pair presented as general (worst in-flight is 1,852.5 m). Regenerate from artifacts |
| dashboard/MissionHealthScore + utils/health.ts | "Composite 0-100 score" = 0.5·coverage + 0.3·formation + 0.2·safety | Invented weights; a made-up number on screen. Delete; replace with mission state + critical-role vacancy |
| utils/suspect.ts + "Telemetry anomaly advisor" | Frontend heuristic: "centroid grew > K× calm jitter" | A detector invented in the UI with arbitrary thresholds. Delete; detection lives in the backend (P4) |
| live/RiskPanel, "AI early warning (display-only)", "AI-risk option not accepted…" | Predictor panel | Decision D2. Hide now, delete after P4 |
| controls policy labels | "Even redistribution — benchmark policy, adapted from the RL paper baseline" | Jargon/provenance. A single "Compare with: no recovery · wait for ground station" control instead of a policy picker |
| layout view toggle | "Formation Array · Local 2:1 Clohessy-Wiltshire relative grid", "Global Orbit · Constellation orbiting Earth in inclined LEO" | Template meta strings. "Earth view" / "Formation view" (and the global view is fake; V1) |
| recovery/AllocationFan | "Bezier allocation fan mapping surviving satellites to target slots" | Abstract diagram duplicating the scene. Delete; arcs are drawn in the 3D scene (V2) |
| narration | "Why these moves: the allocator minimizes total burn…" (text generated in the UI) | Explanation belongs to the backend's rejected/level/certificate data; the UI renders facts, not prose it invents |
| events | "State REPLANNING -> RECONFIGURING" | Plain wording: "Planning recovery", "Moving to new positions", "Recovered in 12:40" |

Copy rules for every string:
- Sentence case, plain verbs, written from the operator's view.
- No file paths, spec sections, "invariant", "engine", "allocator" or "Hungarian" in primary UI. Put those in an "Under the hood" drawer.
- No marketing words.
- Every number either comes from the live stream or carries a source link to its artifact.
- Errors say what happened and what to do.

Grep gate in CI: fail on `\.py|spec \d|MASTER_PROMPT|invariant|RL paper` inside frontend/src/components/**/*.tsx string literals.

### 11.4 Duplication and clutter to remove
- EventLog is mounted in three places (Left, Right, Bottom), RecoveryLog in two, NarrationStrip in two. Keep one of each.
- Six charts in tabs → three: separation vs the 2 km line, with dead-sat markers; fuel left per sat vs budget; critical-role vacancy + coverage on one time axis. FormationDeviationChart, InterSatDistanceChart and MissionHealthScore go.
- Docs, FAQ and Tutorial pages → one "How it works" page; its numbers are read from docs/PITCH_NUMBERS.md at build time.

### 11.5 What the console must show (judge test: understood in 10 s from 4 m, no narration)
```
┌───────────────────────────────────────────────────────────────┬──────────────────────┐
│ STATE BANNER: "Recovering · L2 local re-seat · 03:12 since failure" (gold when recovered) │
├───────────────────────────────────────────────┬───────────────────────────────────────┤
│                                               │ Mission-critical roles                │
│   3D: Earth view ⇄ Formation lens             │  Leader    SAT-3  held (stacked)      │
│   ghost old slots · planned arcs · batons     │  Downlink  SAT-5  held                │
│   dead-sat drift cone · 2 km keep-out rings   │  Vacancy   0:04   vs 41:20 without    │
│                                               │            recovery (shadow run)      │
│                                               ├───────────────────────────────────────┤
│                                               │ Decision                              │
│                                               │  L2 local re-seat (chosen)            │
│                                               │  L1 role swap: rejected — no imager    │
│                                               │  Certificate ✓ min sep 2.9 km         │
│                                               │   fuel margin 6.1 m/s · roles ok      │
│                                               ├───────────────────────────────────────┤
│                                               │ Fuel left per sat  ▮▮▮▮▯  (budget)    │
├───────────────────────────────────────────────┴───────────────────────────────────────┤
│ Timeline: ● failed 1200 s ─ ● detected 1204 s ─ ● plan 1206 s ─ ● recovered 1980 s  [inject] │
└──────────────────────────────────────────────────────────────────────────────────────┘
```
(The numbers in the wireframe are placeholders for layout only. Real values come from the stream.)

Ordered must-haves: 1. State banner. 2. Critical roles with VACANT state + vacancy timer + shadow comparison. 3. Decision card with ladder level, rejected options and certificate. 4. In-scene recovery visuals (V2). 5. Fuel bars. 6. Event timeline with click-to-seek. 7. Inject panel (plain labels, three modes + v2 modes). 8. Report export.

Presentation view: the same, with type sized for a projector (state banner ≥ 40 px, KPI numerals ≥ 32 px), director mode on.

### 11.6 Design direction (frontend-design skill applied)
Subject: a flight-ops console for a self-healing swarm. Audience: hackathon judges at projector distance first, engineers second. Job: make failure → decision → repair unmistakable.

One bold move: kintsugi gold means "repaired", nowhere else. Use --hero-gold: the formation links of a recovered formation render as gold seams; role batons travel in gold; the "Recovered" state banner turns gold. Today "recovered" uses --status-info blue. Change it, so the console and the landing tell one story.

Everything else stays quiet: graphite surfaces, red only for failed, amber only for degraded/in-transit, green only for healthy. Avoid making the console a near-black + one acid accent template: keep the existing token set and spend the boldness on gold only.

Type: keep IBM Plex Sans for UI text; restrict IBM Plex Mono to numerals and sat IDs (59 mono uses today; most are labels → Sans); no all-caps labels, no ·-joined meta strings (12 today), no "WORD — fragment" labels.

Motion: one orchestrated moment only — the recovery sequence (freeze → arcs draw → batons fly → seams turn gold). No idle animations on panels; honour reduced motion.

Quality floor: 1280×720 projector check, keyboard focus visible, colour never the only signal (icons + words for state), no hex outside tokens.css.

### 11.7 Order inside Track UI
1. Copy + duplication cleanup (11.3, 11.4), as part of Track S, with no backend change.
2. Wire pass-through fixes (11.1).
3. V1 Formation lens + true globe (needs chief state, 11.2-1).
4. State banner + critical-roles card + vacancy timer (needs 11.2-3; the shadow run 11.2-5 after L1).
5. Decision card + V2 in-scene visuals (needs the plan payload, 11.2-2, after 5c/5d).
6. Fuel bars (after 2.1).
7. Timeline click-to-seek.
8. Incidents UI.
9. Live real-orbit picker.
10. Report page.
11. L3 performance pass.
12. VISUAL-QA at 1920×1080 and 1280×720 after every step, with screenshots in the report.
