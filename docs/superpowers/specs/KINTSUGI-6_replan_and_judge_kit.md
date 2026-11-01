# KINTSUGI-6 — Replan + Judge Explanation Kit (31 Oct, evening)

(Verbatim from the user, 2026-10-31. It updates the ORDER of docs/superpowers/specs/KINTSUGI-6_v2_master_map.md; the map's specs still apply.)

## 1. Where we are (verified on origin/backend @ 3c20b03)

Done:
- Phase 0 (critical-role metrics, canonical hashes, CI on Ubuntu + Windows + frontend build).
- Simplify.
- Evidence re-measure: 150 claims checked. 76 reproduce, 63 updated, 3 now "unmeasured", 8 handed to the frontend owner.
- CI green.

Branch ownership: the frontend lives on the other session's frontend branch. Master is untouched.

Measured numbers that matter (data/eval/benchmark_results.json on backend, 15 two-failure pairs):

| Policy | Critical roles held | Mean leader/downlink vacancy | Worst vacancy | Mean coverage | Swarm Δv (mean) | Worst per-sat Δv | Worst min sep |
|---|---|---|---|---|---|---|---|
| hungarian | 15/15 | 5.9 s | 16 s | 0.2698 | 444 m/s | 251 m/s | 1,852 m |
| greedy | 15/15 | 5.9 s | 16 s | 0.2698 | 490 m/s | 284 m/s | 1,852 m |
| even_split | 15/15 | 5.9 s | 16 s | 0.2698 | 1,440 m/s | 1,308 m/s | 723 m |
| do_nothing | 6/15 | 9,418 s (2.6 h) | 15,830 s (4.4 h) | 0.2911 | 0 | 0 | 11,314 m |

Other measured facts:
- A zero-fuel role swap beats hungarian's coverage on 6 of 15 pairs (backend audit C).
- The linear CW model's error vs a full Kepler orbit is 1,578.5 m at the current 8 km formation and 3.1 m at 1 km, over 3 orbits (data/eval/cw_error_report.json).
- New, computed today: a 500 km sun-synchronous satellite seen from a single Bengaluru station (elevation ≥ 10°): 2.5 passes/day; the mean wait from a random failure to the next pass is 5.7 h (median 5.6 h, 90th percentile 10.4 h); the longest gap is 13.2 h. This is illustrative and depends on the station network. Commit it as an artifact before quoting it (script in §6).

## 2. What the data is telling us (brainstorm → five decisions)
1. **The value is in roles, not motion.** Re-electing the leader and downlink costs zero fuel and gives 5.9 s of vacancy. Moving costs about 444 m/s across the swarm and loses coverage on average. Hungarian and greedy are identical on the mission metric. → Stop selling "Hungarian assignment". Sell: detect in seconds → hand over the critical roles instantly → move only when moving helps and is certified safe. That is the recovery ladder with L1 (role swap) first.
2. **The 8 km formation is the root of three criticisms at once:** the CW model error (1.6 km) is about the size of the 2 km safety margin; the Δv is far beyond any CubeSat tank; PD needs 10× realistic thrust. → v2 default formation: 2 km amplitude, ψ = 30°, a_max 0.01 m/s², 20 m/s cold-gas budget. The LP prototype needs about 4 m/s for a 2 km re-formation. This one change answers the thrust, Δv and model-accuracy questions together. Side effect: the 13 km footprint would cover the whole 2 km formation, so the coverage metric would go flat. Scale the imager instead: a narrower field of view keeps the footprint-to-spacing ratio of v1 (13.1/8 ≈ 1.6), i.e. fov_half ≈ 0.375° → r_f ≈ 3.3 km. That is realistic for a higher-resolution CubeSat imager. Label it in the scenario.
3. **"Wait for ground" is hours, not 90 minutes.** Model the delay from ground passes (5.7 h mean from one Indian station), not a constant. Report critical-role vacancy for wait_for_ground next to autonomous and do_nothing.
4. **Coverage-hours does not rescue the −2.13 pts.** The team list's #2 claim is wrong: wait-for-ground had more imaging coverage-hours in 10 of 15 pairs. Keep coverage honest and secondary. The headline metric is vacancy.
5. **Beat the strongest baseline, not the weakest.** Add role_swap_only (0 Δv) as a policy. The ladder picks L1 or a move, whichever the certificate shows is better, so v2 should be ≥ both on every pair. Pre-register that claim.

## 3. Reconciling the team lists (Chinmay's impact table, the ranked list, the detailed change plan)

| Their item | Verdict | Where it goes |
|---|---|---|
| Two-impulse planner + Δv vs budget | Yes. LP transfers (they generalize two-impulse and avoid its singular transfer times) + budget % and pass/fail in UI and benchmark | Budget reporting today; LP in v2 5c |
| Coverage-hours + wait_for_ground "turns −2.13 into a win" | Metric yes, framing no (measured false). Use vacancy; delay from the pass model | Today |
| README rewrite, 30-s demo first, fresh-clone build (frontend/dist gitignored) | Yes | Today |
| Clamp ScenarioBuilder to 32 sats | Yes (frontend owner) | Today |
| Browser pass, 422 fails loudly | Yes | Today |
| Docker / G6 verify (CMD + healthcheck are broken per the audit) | Yes | Today |
| API hardening | Yes, the subset that matters for a hosted demo: host allowlist, streaming body limit, atomic upload, serialize start/inject/reset, cancel abandoned runs | Today/tomorrow |
| Coverage-aware replan | Yes = recovery ladder (L1 vs L2/L3, like-for-like) | v2 R1 |
| Monte Carlo 3+ failures, random times, baselines | Yes, plus a role_swap_only baseline | Packs + pre-registered benchmark |
| Replan latency on the landing page | No. Machine-dependent; the landing page is frozen. Out-of-band doc only | — |
| Two-tier safety (2 km vs 1 km) | Interim: one sentence in docs. v2 replaces it with the certificate | Today (doc) / v2 |
| HCW error %, nonlinear safety check | Yes = truth model + certificate. "J2/drag breaks golden hashes" is no longer true: the engine flag keeps v1 byte-identical | v2 P1 |
| Narration per state beat | Yes, rendered from backend facts, not prose the UI invents | Track UI |
| Speed up run_scenario | Yes, plus a stepping engine (no full recompute on inject) | v2 L1 |
| sat_id + narrative in wire events | Yes | §11.1 of the map |
| Frontend cleanup, shared types, contract tests | Yes (frontend owner) | Track UI |
| Dead-sat drift study | Covered by the truth model | v2 P1 |
| Partial thrust, comms blackout | Yes as v2 failure modes | v2 P2 |
| Transit-path avoidance | Yes: LP keep-out + certificate | v2 5c/5d |
| Repo hygiene (LICENSE, description, .aistudio blobs) | Yes, 30 min | Today |
| Interactive what-if / health dashboard / timeline / reports | What-if = live inject + shadow no-recovery twin. Health = per-sat fuel & battery bars (never a composite score). Timeline exists. Report = anomaly report export | Track UI |
| Communication-aware recovery, CBBA | Roadmap (needs a comms model; cite NASA Starling's distributed autonomy) | Slide |
| AI failure prediction in the loop | No. Failed its pre-registered bar | — |
| Raft/Paxos | No. Wrong tool | — |

## 4. New order with cut lines

When is the final? Pick the matching cut line.

**Today (hours), "the demo can't embarrass us":**
- README: 30-second run first, honest claims, a fresh-clone build step.
- Docker CMD/healthcheck fixed and verified; one-command run.
- Serialize session start/inject/reset; cancel abandoned runs; 422 fails loudly.
- Clamp the builder to 32 sats (frontend).
- Δv as % of budget, with pass/fail, in the benchmark and on the per-sat UI rows.
- Commit the ground-pass artifact; wait_for_ground delay from the pass model; vacancy table for all four policies (+ role_swap_only).
- Repo hygiene.

**Next 1–2 days, "the story is visible":**
- EngineV2 (truth model + stepper).
- 2 km ψ = 30° formation with a realistic budget.
- Fuel model.
- Ladder with L1 first + certificate (separation over 2 orbits including drift, fuel margin, roles).
- LP transfers.
- Streaming live + shadow twin.
- Frontend: state banner; critical-roles card with vacancy timer, shown against the twin; decision card; formation lens; gold seams.

**Days 3–5, "the wow":**
- Incidents (Starling-2023, Proba-3-2026).
- Real-orbit live (sgp4).
- Packs + Monte Carlo + pre-registered benchmark (C1–C7).
- Physics detector.
- Deploy + rehearsal.

**If the final is ≤ 2 days away:**
- Do Today in full.
- From Next: only the L1-first ladder in v1 (zero-fuel role swap, then move only if certified by the existing separation/fuel checks), Δv budget, shadow twin, vacancy UI and formation lens.
- Present v2 physics as "in progress", with the measured prototype numbers only.

## 5. Explaining it to jaded judges

Judges look jaded because they've seen twenty dashboards of coloured dots and big claims. Five fixes:

**a. Open with one outcome, in plain words.**
"When two satellites in our swarm die, the swarm has a new leader in about 6 seconds. Without it, the swarm stays leaderless for 2.6 hours on average, up to 4.4. And waiting for a ground station from India means about 5.7 hours."
(The last sentence only once the pass artifact is committed.)

**b. Let them break it.** Hand the judge the mouse: "Pick any two satellites to kill." 15/15 means any choice works. A judge who chose the failure believes the result.

**c. Say the trade-off before they find it.**
"Recovery costs some imaging coverage. We choose that on purpose: without a leader and a downlink, no image ever reaches Earth."
Naming your weakness first makes everything else credible.

**d. Show, don't tell: the twin.** On screen, the swarm next to its no-recovery twin: "Leader: held · Without recovery: vacant 41:12" (live value). One glance, no explanation needed.

**e. Three depths, used in order. Stop as soon as they nod.**
1. One sentence: "A satellite swarm that notices when members die, hands their jobs to survivors in seconds, and only moves when a safety check says the move is worth it."
2. 30-second analogy: "Think of a football team that loses two players and can't call the coach, because the ground station is hours away. The captain's armband passes instantly: that's the role swap, no running needed. Players only reposition if it helps, and a referee checks no one will collide before anyone moves. That referee is our safety certificate."
3. 2-minute depth (only if asked): the orbit equations, the matching algorithm, fuel-optimal transfers, the certificate.

Kill the jargon on stage. Say "matching" (not Hungarian), "orbit equations" (not Clohessy–Wiltshire), "relative to the formation" (not LVLH), "fuel" (not Δv) unless they ask.

**Pitch spine (4 beats, about 5 min):**
1. Problem. Real incidents (Proba-3, launched on PSLV; NASA Starling), then the problem statement.
2. Live. The judge kills two satellites; watch: failure → new leader in seconds → decision card → safe repair, gold seams.
3. Proof. 15/15 critical roles vs 6/15; about 6 s vs 2.6 h vacancy; the honest coverage trade-off; the realistic-fuel numbers, only when v2 has measured them.
4. Next. Real-orbit live, incident replays, decentralised coordination.

**Hostile questions, with honest answers:**
- "Your thrust is 10× a real CubeSat." "That was our first version. The new one uses a 2 km formation and fuel-optimal transfers at realistic thrust." Quote the measured Δv once v2 has it; until then: "being measured; our prototype says about 4 m/s against a 20 m/s tank."
- "Coverage goes down after recovery?" Answer (c).
- "Is the linear model accurate?" "At 8 km its error was 1.6 km, which is why v2 plans with it but checks every plan in a full-gravity, drag model. At 2 km the error drops to metres."
- "Why not machine learning?" "We tried. Our learned predictor matched a simple moving average and leaked the answer. Physics needs no failure data and can prove a plan safe."
- "Is this real data?" "Real orbits, a hypothetical swarm, labelled as such."

## 6. Prompts

**To Claude (backend session):**
Read KINTSUGI-6_replan_and_judge_kit.md (save to docs/superpowers/specs/). It updates the order of the master map; the map's specs still apply. Key changes:
1. Add policy role_swap_only (0 Δv) and a wait_for_ground policy whose delay comes from a ground-pass model (station Bengaluru 13.03N 77.51E, el>=10°, chief from scenario elements). Commit the pass-statistics artifact (passes/day, mean/median/p90 wait, max gap) with its command. Report critical_vacancy_s for all 5 policies.
2. v2 scenario defaults: radial_amp 2 km, psi 30°, a_max 0.01, propellant budget 20 m/s (Isp 40 s, 0.2 kg on 4 kg), fov_half_angle chosen so r_f/spacing matches v1 (~0.375° → r_f ≈ 3.3 km); document each as illustrative.
3. Recovery ladder L1 (role swap, 0 Δv) evaluated first; a move (L2/L3) only if certified AND better than L1 like-for-like. Pre-register in GATES.md: v2 coverage ≥ max(role_swap_only, hungarian) − 1e-4 on every pair, and critical roles 15/15.
4. Do the "Today" list in §4 first (README, Docker CMD/health, session serialization + cancel, loud 422, Δv-as-%-of-budget, repo hygiene). STOP and report, then continue with "Next".
Do not touch frontend/ (other session); write any UI requirements to docs/frontend-requests.md.

**To the frontend session:**
Read docs/superpowers/specs/KINTSUGI-6_v2_master_map.md §11 and KINTSUGI-6_replan_and_judge_kit.md §5. Today: clamp the builder to 32 sats; remove the Mission Health score and the frontend "anomaly advisor"; strip file paths/spec refs/enum labels from copy; per-sat Δv shown as % of budget. Then build: state banner, critical-roles card with a live vacancy timer (+ "without recovery" twin value when the backend sends `shadow`), decision card, formation lens, gold-means-repaired seams. Load the frontend-design skill. Visual QA at 1920×1080 and 1280×720.

**Ground-pass script (it produced the numbers in §1; Claude should turn it into cubesat/ground.py + a benchmark mode and commit the artifact):**
- Circular 500 km, i = 97.4°, J2 RAAN drift.
- Station 13.03°N 77.51°E, elevation ≥ 10°, 7 days, dt 10 s.
- 12 RAAN × 4 phase starts.
- Waits measured from failure times every 600 s.
