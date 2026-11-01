# KINTSUGI-6 — PHYSICS ENGINE v2: full implementation brief

(Verbatim brief from the user, 2026-10-31. This is the spec the plan implements.)

## 0. ROLE AND OPERATING MODE
You are the ORCHESTRATOR for upgrading the KINTSUGI-6 CubeSat swarm simulator's physics engine. Work on a new branch `physics-v2` from latest `master`. Never push, never merge to master; the user reviews each phase.

Use the superpowers workflow skills if available: brainstorming → writing-plans → subagent-driven-development / executing-plans → test-driven-development → verification-before-completion → requesting-code-review. Save the plan to docs/superpowers/plans/2026-10-31-physics-v2-plan.md.

Spawn these SUBAGENTS. Each gets ONLY the context it needs. Reviewers never see the implementer's reasoning, only the diff and this brief:
1. PLANNER: turns this brief into the step-by-step plan file (task list with files, tests, acceptance per task). Do not write code.
2. IMPLEMENTER (one per phase, sequential): tests first (watch them fail for the right reason), then the minimum code to pass.
3. PHYSICS-VALIDATOR (fresh context, independent): re-derives every formula in the phase from first principles and checks it numerically in a separate scratch script (NOT reusing the implementer's code). Reports pass/fail with numbers.
4. ADVERSARIAL-REVIEWER (fresh context): tries to break the phase with edge cases (simultaneous failures, all-but-one dead, zero fuel, packet loss 100%, extreme altitudes, cancel mid-run), checks determinism, checks every number claimed. Returns a defect list. Fixes nothing.
5. BENCHMARK-RUNNER (Phase 9 only): runs the pre-registered benchmark exactly as written and writes artifacts. Cannot change thresholds.

Phase loop: IMPLEMENTER → gates → PHYSICS-VALIDATOR + ADVERSARIAL-REVIEWER (in parallel) → IMPLEMENTER fixes → gates → commit `physics-v2: phase N — <summary>` → STOP and show the user: diff stat, test output tail, validator report, reviewer report, any number with its command.

## 1. NON-NEGOTIABLE RULES (from AGENTS.md; never break)
- NO NUMBER without a committed artifact AND the command that produced it. Unmeasured → "unmeasured". Never pre-state a result (e.g. "will eliminate ≥1.5 h downtime"); measure, then report.
- Determinism: same scenario + seed ⇒ identical log on the same machine. No wall clock in the sim. Randomness ONLY via one numpy Generator(PCG64(SeedSequence(scenario.seed))) owned by the sim, drawn in a fixed documented order (the seed is currently written to the log but never used).
- BACKWARD COMPATIBILITY: add a scenario field `engine: Literal["v1","v2"] = "v1"`. With "v1" every existing log, test and golden hash must stay identical. All new physics lives behind "v2".
- SI units internally; LVLH frame x radial, y along-track, z cross-track.
- Do NOT modify: files/** (sealed predictor), models/**, predictor/runtime.py, frontend landing files.
- No new dependencies. numpy + scipy only (scipy.optimize.linprog with method="highs" is allowed).
- Tests first for every change; `uv run ruff check .` and `uv run python -m pytest -q -m "not slow"` green at every phase end.

## 2. CONTEXT — VERIFIED FINDINGS (latest master eb6c9f1, independent runs)
Fix-or-replace targets (the v1 engine stays as-is for reproducibility; v2 fixes these):
F1. Do-no-harm guard regressed recovery: across all 15 two-failure pairs, hungarian is worse than do_nothing in 9/15; mean coverage 0.2594 vs do_nothing 0.2911 (−3.17 pts). Pairs (1,5),(2,5),(3,5),(4,5) end at 0.2327 (pre-guard 0.2698), (0,4) at 0.2625. Cause: allocate.replan scores the hold with survivor_roles but returns re-elected `seats`, and sim applies them. The claimed "100% non-negative, mean 30.84%" does not reproduce. data/eval/benchmark_results.json is stale (still pre-guard numbers).
F2. Critical roles: hungarian keeps leader AND downlink on healthy sats in 15/15 pairs; do_nothing in 6/15 (the 9 failures are exactly the pairs containing sat 0 or sat 5). This is the strongest true result. Preserve it.
F3. THRUSTER_OUT leaves duplicate roles: thruster_leader_6sat ends with sat 0 (THRUSTER_OUT) still labeled leader AND sat 2 leader.
F4. Fuel is unlimited in flight: per-sat Δv reaches 211.9 m/s against a 200 m/s budget (251 m/s pre-guard). A realistic 3U cold-gas budget is ~20 m/s (4 kg, 0.2 kg propellant, Isp 40 s: 40·9.80665·ln(4/3.8) = 20.1 m/s).
F5. "RECOVERED" is premature: two_failure declares RECOVERED at t=3114 s while one sat is 1,092 m off its seat and moving 7.75 m/s relative (tolerance = 5% of the largest transfer, position only).
F6. 4 of 6 dead → coverage 0.0: both survivors become leader + downlink, no imager left.
F7. 2 km separation is only checked on destination formations at replan; in flight the 15-pair worst survivor–dead clearance is 1,322.6 m.
F8. Formation is NOT passively safe: slots use z = A·cos(θ) (in phase with x). Under along-track drift of a dead sat, the minimum distance to its neighbour can fall to 5.9–11.8 m.
F9. Dead satellites never drift away in v1 (linear, unperturbed CW keeps them on a bounded ellipse forever). With drag at 500 km a tumbling dead 3U drifts ~3.1 km/day relative to an active one (28 km in 3 days, 152 km in 7 days) — it WILL cross every slot.
F10. The PD controller is the reason a_max = 0.1 m/s² (~0.8 N) is needed — not physics. A fuel-optimal LP planner (prototype on the CW STM) completes the 8 km two_failure leader transfer at a realistic a_max = 0.01 m/s² in one orbit for 16.4 m/s (2 km formation: ~4 m/s even at 0.002 m/s²). PD spent ~155 m/s on a comparable transfer.
F11. Heartbeat detection with K=3 has no glitch tolerance: with 5% packet loss it gives 0.34 false failure declarations per satellite per orbit (K=5: 0.0008).
F12. Golden hashes are machine-specific even with the sys.platform map (Linux run with pinned libs still mismatched). Floats differ at ~1e-11 m; events identical.
F13. Pitch-risk: "EPS = 44% of smallsat failures" is a misquote. Langer & Bouwmeester: EPS and COM TOGETHER ≈44% of losses at 30 days. Swartwout: ~40% university mission failure rate. Use those exact statements.

## 3. THE v2 CONCEPT (what makes it impressive and honest)
"Certified self-healing": every recovery decision is made with a fast planning model (CW or Schweighart–Sedwick J2) but flown in a realistic truth model (nonlinear gravity + J2 + drag), from per-satellite resources (fuel, power, thrust, payload, radio). Every plan ships with a physics CERTIFICATE — fuel-feasible, collision-safe over the horizon INCLUDING drifting dead satellites, role-capable — or it is not executed. Failures emerge from physics (battery aging, impacts, single-event resets, stuck thrusters) instead of only being scripted, and a model-based detector tells real failures from glitches. Never say "first/novel/state-of-the-art"; say "we couldn't find an open tool that does X".

## 4. PHASES, EXACT FORMULAS, FILES, TESTS

### PHASE 0 — Baseline + fix v1 bugs that affect the headline (small, do first)
- Reproduce F1–F3, F5 as failing tests.
- F1 fix: score the hold with the SAME role layout it will apply; the guard must guarantee hungarian(with guard) ≥ hungarian(without guard) per pair (state the guarantee in the test docstring). Re-run the 15-pair benchmark with its command of record; commit benchmark_results.json + manifest; GATES.md row with the numbers and command.
- F3 fix: when a sat leaves NOMINAL, clear its critical role label (roles[i] = "none" or keep original role in a separate field for display); assert exactly one leader and one downlink among NOMINAL sats after every ASSIGNMENT.
- F12: replace sys.platform hash maps with a canonical hash: json.dumps(line_with_every_float_rounded_to_9_significant_digits, sort_keys=True); keep a same-machine byte-identity test (run twice, compare bytes).
- Add benchmark metrics: critical_roles_held_end, critical_seat_frac (fraction of ticks after first failure with both critical roles on NOMINAL sats), imagers_end; summary pairs_critical_roles_held.
Acceptance: all green; benchmark artifact regenerated; hungarian critical roles 15/15, do_nothing 6/15 (verify, don't assume).

### PHASE 1 — Truth dynamics module (new file cubesat/truth.py; engine "v2" only)
State per body in ECI: r, v. Integrate with fixed-step RK4, dt = scenario.dt_s (2 s). Validated target: RK4 dt=2 s vs RK45 (rtol 1e-12) on two-body+J2, 3 orbits at 500 km: position error ≈ 1e-3 m.
Accelerations:
- Gravity: a = −μ r/|r|³, μ = 3.986004418e14.
- J2: a_J2 = −(3/2)·J2·μ·Re²/|r|⁵ · [x(1−5z²/|r|²), y(1−5z²/|r|²), z(3−5z²/|r|²)], J2 = 1.08262668e-3, Re = 6378.137e3. Test: equals the gradient of U_J2 = −(μ/|r|)·J2·(Re/|r|)²·(3sin²φ−1)/2 by central difference (rel err < 1e-5).
- Drag: a_D = −½·ρ(h)·B·|v_rel|·v_rel, v_rel = v − ω⊕×r, ω⊕ = 7.2921159e-5 rad/s ẑ, B = Cd·A/m. ρ(h) = ρ0·exp(−(h−h0)/H), Vallado exponential table rows: h0=450 km ρ0=1.585e-12 H=60.828 km; 500 km ρ0=6.967e-13 H=63.822 km; 600 km ρ0=1.454e-13 H=71.835 km (pick the row with h0 ≤ h). Defaults (illustrative, labelled in scenario): Cd 2.2; active sat A=0.010 m² (end-on), dead/tumbling A=0.035 m² (mean projected area of a 10×10×30 cm box = surface/4); m=4 kg. Test: decay per rev ≈ −2π·B·ρ·a² (King–Hele): active ≈ −1.14 m/rev, dead ≈ −3.99 m/rev at 500 km.
- Thrust: commanded a_LVLH rotated to ECI: a_I = Cᵀ·a_LVLH, C rows = [x̂; ŷ; ẑ] with x̂ = r_c/|r_c|, ẑ = h/|h| (h = r_c×v_c), ŷ = ẑ×x̂.
- Chief: a virtual reference propagated with gravity + J2 (no drag), circular initial state at the scenario altitude and new scenario field inclination_deg (default 97.4, SSO-like), raan_deg (default 0).
LVLH relative state for every sat: ρ = C·(r_d − r_c); ρ̇ = C·(v_d − v_c) − ω×ρ, ω = (0, 0, |h|/|r_c|²). Initial deputy states: map the v1 slot LVLH states back to ECI with the inverse transform. Test: round trip ECI→LVLH→ECI < 1e-6 m.
Log format: v2 still logs LVLH r, v (same schema) so wire/frontend work unchanged; add optional per-sat fields only.
Validation: with drag off and a 1 km formation, v2 truth vs v1 CW positions must agree to the measured CW-vs-Kepler level (3.1 m over 3 orbits at 1 km); report the J2-on difference as a new measured number.

### PHASE 2 — Spacecraft resource model (cubesat/spacecraft.py)
Per-sat state: mass m, propellant m_p, thrust health k∈[0,1], stuck_open flag + vector, battery energy E, state-of-health SoH∈[0,1], payload_ok, radio_ok, mode ∈ {NADIR, THRUST, SAFE, OFF}.
- Propulsion: |F| ≤ k·F_max; a_cmd saturated at k·F_max/m; ṁ = −|F|/(Isp·g0), g0 = 9.80665; remaining Δv = Isp·g0·ln(m/m_dry). When m_p ≤ 0 → status FUEL_DEPLETED (self-reported, behaves like THRUSTER_OUT). Defaults (illustrative): m0 4.0 kg, m_p 0.2 kg, Isp 40 s, F_max 0.04 N (→ 0.01 m/s²).
- Power: sun direction ŝ fixed in ECI for the run (scenario field sun_vector, default from a fixed date). Shadow (cylindrical): in eclipse iff r·ŝ < 0 and |r − (r·ŝ)ŝ| < Re. Check: β=0, 500 km → eclipse fraction asin(Re/r)/π = 0.378 (35.75 min/orbit). P_in = η·S·A_panel·max(0, n̂_panel·ŝ)·(1−eclipse), S = 1361 W/m², defaults η 0.28, A_panel 0.06 m² (body+wings, illustrative), panel normal = sun-tracking in NADIR mode simplified to cos factor 0.6 average (document the assumption). Loads: bus 1.5 W, imager 2.0 W (NADIR + imager role), radio 4.0 W (during downlink duty), thruster 1.0 W while firing. E_{k+1} = clamp(E_k + (P_in − P_load)·dt, 0, C_bat·SoH), C_bat = 20 Wh. SoC < 20% → SAFE (no imaging, no thrusting, still heartbeats); SoC < 5% → OFF (silent until SoC > 15%).
- Attitude (simplified): imaging only in NADIR; thrusting requires THRUST mode; slew time = angle/ω_max, ω_max = 3°/s; no imaging during thrust arcs and slews (coverage counts only NADIR imagers). Document this as a mode model, not attitude dynamics.
- Failure modes become resource damage: DEAD (all off), THRUSTER_OUT (k=0), EPS_DEGRADE (SoH ramps down → brown-out emerges naturally), new: PAYLOAD_FAIL (payload_ok=False), PARTIAL_THRUST (k=0.5), THRUSTER_STUCK_OPEN (constant thrust k_s·F_max along a fixed ECI vector until propellant empty), RADIO_FAIL (radio_ok=False; alive, flying, silent).
Tests per mode: semantics + determinism; v1 untouched.

### PHASE 3 — Physics-caused failures (hazard models, seeded, scenario block `hazards`, default off)
- SEU reset: Poisson rate λ_seu (per sat-day) → OFF for U[30,120] s then reboot (state preserved).
- Impact (micrometeoroid/debris): Poisson rate λ_imp = flux·A_exposed; the struck component is drawn with probability ∝ its area: panels → P_in × (1−f), f~U[0.2,0.6]; tank → leak ṁ_leak (propellant loss + small reaction thrust along a fixed body direction); camera → PAYLOAD_FAIL; radio → RADIO_FAIL; bus → DEAD.
- Battery aging: SoH(t) = 1 − (t−t0)/τ_age.
All rates are ILLUSTRATIVE scenario parameters; never present them as real statistics. Draw order fixed and documented; same seed ⇒ same events.

### PHASE 4 — Model-based failure detection (the physics is the detector)
Signals: heartbeat (received with probability 1−p_loss, seeded), self-telemetry (SoC, k, flags) when the radio works, and a MOTION RESIDUAL from tracking: r_k = ρ_meas(k) − [Φ(dt)·ρ_meas(k−1) + G(dt)·a_cmd(k−1)] using the planning model's STM/forcing (hcw.py). Optional measurement noise: σ_pos 1 m, σ_vel 0.01 m/s (seeded).
- χ² test: d_k = r_kᵀ Σ⁻¹ r_k > γ, γ = chi-square 6-dof quantile at P_fa = 1e-4 (≈ 27.86); Σ estimated from nominal-run residual statistics (commit the calibration run).
- Classification: silence + residual consistent with NO thrust (ballistic) for K ticks → DEAD; silence + residual consistent with commanded motion → SUSPECT (likely reboot/radio), wait T_grace before declaring; heartbeat OK + residual anomaly → THRUST_ANOMALY (stuck-open / partial); heartbeat OK + telemetry flag → self-reported mode.
- Choose K from the false-alarm law: expected false declarations per sat per orbit = N_ticks·(1−p)·p^K (N_ticks = 2838 at 500 km). Report a table for p ∈ {0.01, 0.05, 0.1}, K ∈ {3,5,7}.
Metrics: detection latency per mode, false declarations, missed detections.

### PHASE 5 — Recovery v2 (cubesat/allocate_v2.py + seam; v1 allocate stays)
1. Capability matrix cap[sat][role]: imager needs payload_ok ∧ power margin; downlink needs radio_ok ∧ power; leader is a SOFTWARE role, stackable on any sat with radio_ok (fixes F6: leader no longer consumes an imager).
2. Role priority (scenario field `role_priority`, default ["downlink","imager","leader"]); Hungarian on capability-aware costs (incapable = large constant, never inf in linprog/LSA).
3. Formation candidates: sweep amp × phase_offset × cross-track phase ψ, slots x = A·cos(θ), y = −2A·sin(θ), z = B·cos(θ+ψ) (new scenario field cross_track_phase_deg; v1 default 0). Measured trade at A=B=8 km, 6 slots, 4 imagers: ψ=0 coverage 0.371 / worst separation under any along-track drift 11.8 m; ψ=30° 0.364 / 2,929 m; ψ=45° 0.355 / 4,330 m; ψ=60° 0.345 / 5,657 m; ψ=90° 0.326 / 8,000 m. For ψ=90° the bound is d_min ≥ 2·sin(Δφ/2)·min(A,B). Recommend default ψ=30° in v2 scenarios; reproduce this table as a committed eval artifact.
4. Fuel-optimal transfers (LP, scipy linprog "highs"): decision variables Δv_k⁺, Δv_k⁻ ≥ 0 at N burn nodes t_k over transfer time T; minimise Σ_k Σ_axis (Δv⁺+Δv⁻); equality: Σ_k Φ_rv,vv(T − t_k)·(Δv_k⁺ − Δv_k⁻) = x_target(T) − Φ(T)·x0 (use the full 6×3 velocity columns of Φ); bounds per component ≤ k·a_max·(T/N)/√3; keep-out via linearised half-spaces n̂_jᵀ(ρ_i(t_j) − ρ_o(t_j)) ≥ d_safe at sample times t_j (sequential convexification, ≤3 iterations, n̂ from the previous iterate). Sweep T ∈ {0.5, 1, 2} orbits; choose the feasible T with least Δv. Execute as model-predictive control: re-solve every M ticks (e.g. 60) from the truth-measured state; PD only for terminal hold. Prototype reference: 8 km leader transfer, a_max 0.01, T = 1 orbit → 16.4 m/s.
5. CERTIFICATE (cubesat/certify.py): before executing, forward-propagate the full plan in the TRUTH model for horizon H = 2 orbits, including dead sats' drag drift; check min pairwise separation ≥ d_safe (2 km), each sat's planned Δv ≤ remaining Δv − reserve (20%), every critical role on a capable sat, coverage ≥ hold coverage. Emit CERTIFICATE event {passed, min_sep_m, worst_fuel_margin_mps, roles_ok, coverage}. If failed: try next candidate; if none: hold + flag. Never execute an uncertified plan in v2.
6. RECOVERED (v2): every NOMINAL sat ‖Δr‖ ≤ 50 m AND ‖Δv‖ ≤ 0.05 m/s relative to its seat for ≥ 30 consecutive ticks (60 s).
7. Continuous safety monitor: every tick, predicted closest approach over the next 10 min from the planning model; if < 1 km, trigger evasion (existing apply_accel) AND a replan.

### PHASE 6 — Mission value metrics
- coverage(t) (existing definition, NADIR imagers only in v2).
- coverage-hours H_cov = ∫ coverage dt (trapezoid over ticks).
- delivered coverage: imaged area counts only if a capable downlink sat exists AND a ground-station pass occurs within latency L (default 3 h). Ground station visibility: elevation el = asin( ((r_sat − r_gs)·û_gs) / |r_sat − r_gs| ) ≥ 10°, r_gs rotating with Earth at ω⊕; default stations: Bengaluru (13.03°N, 77.51°E) — scenario field, illustrative.
- critical-role uptime, Δv (total, per sat, remaining), min separation, certificate pass rate, false declarations, detection latency.

### PHASE 7 — Failure packs
data/scenarios/packs/<pack>/*.json, each pack a documented situation, engine "v2", ψ=30°, a_max 0.01, realistic fuel:
- two_dead (the 15 DEAD pairs, the problem statement), leader_battery_fade (EPS_DEGRADE + reassign_on_degrade), debris_strike (DEAD + neighbour PARTIAL_THRUST), stuck_thruster (THRUSTER_STUCK_OPEN), radiation_glitch_storm (SEU resets on 2 sats + p_loss 5% — correct behaviour is NOT to replan), aging_fleet (battery aging + PAYLOAD_FAIL), comms_blackout (RADIO_FAIL on downlink).
Benchmark mode `--mode packs` iterating files × policies (do_nothing, hungarian_v1, recovery_v2) × seeds (N=20) — writes logs with sha256, report JSON, manifest.

### PHASE 8 — Wire + frontend (minimal, no restyle)
New statuses mapped in wire.py (_STATUS_TO_WIRE) and frontend colours; new events formatted (CERTIFICATE, SUSPECT, THRUST_ANOMALY, FUEL_DEPLETED, SAFE_MODE); console shows: certificate badge (passed + min sep + fuel margin), per-sat fuel/battery bars, leader/downlink readout. Hex colours only in tokens.css.

### PHASE 9 — Pre-registered benchmark (BENCHMARK-RUNNER)
BEFORE running, commit to GATES.md the claims and thresholds, e.g.:
C1 recovery_v2 holds both critical roles in ≥ 95% of pack runs where at least 2 capable sats survive.
C2 recovery_v2 per-sat Δv ≤ fuel budget in 100% of runs (by construction; verified).
C3 0 certified plans violate 2 km in truth-model replay.
C4 radiation_glitch_storm: false replans ≤ 1 per 20 runs.
C5 two_dead: recovery_v2 coverage ≥ do_nothing in ≥ 13/15 pairs OR critical roles held 15/15 (report both).
Then run, and report pass/fail honestly whichever way it goes.

## 5. REMOVE / ADD / ADJUST SUMMARY
REMOVE (from claims and v2 defaults, keep code for v1 reproducibility): a_max 0.1 as default for v2; PD as the transfer controller in v2; heartbeat-only detection in v2; the misquoted "44%"; any claim based on the stale benchmark file.
ADD: engine flag; truth model (J2, drag); spacecraft resources; hazard models; model-based detector; capability-aware stacked roles; LP transfers + MPC; certificate; v2 recovered criterion; coverage-hours; delivered coverage; packs benchmark.
ADJUST: cross-track phase (ψ=30° default in v2); do-no-harm like-for-like; duplicate-role bug; canonical hashes; seed actually used.

## 6. FINAL DELIVERABLES
- Branch physics-v2 with one commit per phase; all tests green (v1 goldens unchanged).
- docs/PHYSICS_V2.md: every formula, every default with its source or "illustrative", every validation number with its command.
- data/eval/: CW-vs-truth report, ψ trade table, LP-vs-PD Δv table, false-alarm table, packs benchmark report + manifest.
- docs/PITCH_NUMBERS.md: only numbers that passed, each with command.
- A 10-line summary per phase in chat, plus the open-risk list.
