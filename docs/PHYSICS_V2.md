# PHYSICS_V2: truth-dynamics engine (Phase 1)

Scope of this file: what `engine: "v2"` implements today (Phase 1 only), every formula, every default with
its source or the word "illustrative", every validation number with the command that produced it, and the
draw-order table. Anything not listed here is not implemented. Numbers were measured on macOS arm64 on
2026-10-31 and are the printed values of the quoted commands; reproduce them, do not trust this page.
Plan: `docs/superpowers/plans/2026-10-31-physics-v2-plan.md`; formulas: `docs/superpowers/specs/2026-10-31-physics-v2-brief.md` section 4.

v1 (`engine: "v1"`, the default) is byte-identical: no existing test or golden pin was edited
(`git diff $(git merge-base backend HEAD)..HEAD -- tests/ ':!tests/v2' | grep -E 'sha|hash'` prints nothing).

## Frames, units
SI. ECI (inertial, z = Earth rotation axis). LVLH: x radial, y along-track, z cross-track; state `[x, y, z, vx, vy, vz]`.
`C` = ECI-to-LVLH DCM with rows `x_hat = r_c/|r_c|`, `z_hat = (r_c x v_c)/|r_c x v_c|`, `y_hat = z_hat x x_hat` (`truth.lvlh_dcm`).

## Formulas implemented (`cubesat/truth.py`)
| Item | Formula | Constants |
|---|---|---|
| Gravity | `a = -mu r / abs(r)^3` | mu = 3.986004418e14 m^3/s^2 |
| J2 | `a = -(3/2) J2 mu Re^2 / abs(r)^5 * [x(1-5z^2/r^2), y(1-5z^2/r^2), z(3-5z^2/r^2)]` | J2 = 1.08262668e-3, Re = 6378.137e3 m |
| Drag | `a = -1/2 rho(h) f B abs(v_rel) v_rel`, `v_rel = v - omega_E x r`, `h = abs(r) - Re` (spherical altitude), `B = Cd A / m`, `f` = `truth.density_factor` | omega_E = 7.2921159e-5 rad/s |
| Density | exponential, `rho = rho0 exp(-(h-h0)/H)` on the row with the largest `h0 <= h`; the 1000 km row above 1000 km; below 150 km the 150 km row value is used (constant: the exponential is never extrapolated downward) | table below |
| Thrust | commanded LVLH acceleration rotated to ECI, `a_I = C^T a_LVLH`, `C` from the chief at the start of the step, held over the step | |
| Integrator | classical RK4, fixed `dt = scenario.dt_s` (2 s) on `[r, v]`, batched over (chief + all sats) in one call | |
| Chief | virtual reference: circular orbit at ascending node, gravity + J2 only (no drag, no thrust) | |
| Chief initial | `r = a [cos O, sin O, 0]`, `v = vc [-sin O cos i, cos O cos i, sin i]`, `a = Re + altitude` | i, O from the scenario |
| ECI to LVLH | `rho = C (r_d - r_c)`, `rho_dot = C (v_d - v_c) - w x rho`, `w = (0, 0, abs(h)/abs(r_c)^2)` | |
| LVLH to ECI | exact inverse | |

Density table, as written in the master map section 10 Q7 (attributed there to Vallado, Fundamentals of Astrodynamics and Applications, Table 8-4). Book check pending: only the 450, 500, 600 and 700 km rows were compared with the printed values; the other rows (the 400 km row 3.725e-12 / 58.515 in particular) match the master map but are NOT verified against the book. All 14 rows are asserted equal to this table by `tests/v2/test_truth_accel.py::test_density_table_matches_vallado_rows`, and the row-selection rule by `::test_density_uses_largest_h0_not_nearest_row`:

| h0 km | rho0 kg/m^3 | H km |
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

The table is a static exponential atmosphere: no solar-activity, diurnal or latitude variation.

## EngineV2 (`cubesat/sim_v2.py`, `cubesat/faults_v2.py`, `cubesat/rng_v2.py`), Phase 1 behaviour
- Init: sat i starts on v1 slot i (`sim.build_slots`) mapped to ECI with `lvlh_to_eci`. `initial_lvlh` (N, 6) overrides the start states (validation hook).
- Tick `k` (`step()`): re-entry check, failures due at `t = k dt`, heartbeat/detection, draw rows 1-7 for every sat, log the LVLH state, then advance one RK4 step. Log schema = v1 tick schema plus optional `events` (ALL events of the tick; `event` = the first). Consumers that read only `frame["event"]` (`wire.py`, `dv_bound.py`) see just the first of several simultaneous events; `events` carries all. INIT also carries `engine: "v2"`.
- Seat holding: v1 `PDController.command` on the LVLH state against the slot reference, applied as a zero-order-hold acceleration. The reference is advanced with a cached `stm(dt)` (`hcw.stm`); the cached-Phi iteration differs from a direct `stm(t)` by 2.506e-08 m after one orbit (`uv run python -m pytest tests/v2/test_sim_v2_truth.py -k cached_phi -s`). `forcing_matrix(dt)` is not cached yet: nothing uses it before the Phase 5 planner.
- Failures (Phase 1 minimum): DEAD and EPS_DEGRADE (after its fade) coast in the truth model with the dead area; THRUSTER_OUT coasts with the active area and self-reports on the firing tick; EPS_DEGRADE with `degrade_s > 0` is DEGRADED (still holding) from `t - degrade_s`. Detection is the v1 heartbeat rule (`detection.missed_ticks_k`, a DEAD sat at t is declared at t + (K-1) dt). A repeated failure that leaves a sat in the status it already has emits nothing. No replanning, no recovery, no resources: mission state stays `FAILURE_DETECTED`.
- Re-entry guard: a sat whose altitude `|r| - Re` falls below 100 km (`sim_v2.REENTRY_ALTITUDE_M`, a guard value, not a decay model) is flagged `REENTERED`: one `REENTRY` event `{sat_id, t, altitude_m}`, the state is frozen (ECI and the logged LVLH state at the moment of re-entry), no further integration, it counts as silent for the heartbeat, and it is excluded from coverage and from `min_sep` (all sats are used when fewer than two remain). Without it a 161 km dead sat left Earth at 1.7e12 km and `density_factor = 2000` gave |r| ~ 4e105.
- `inject(failure)`: the failure time is clamped to the current tick and an EPS_DEGRADE fade onset (`t - degrade_s`) is clamped to now by shortening `degrade_s`; the RESOLVED failure is recorded in `engine.injections`. The contract is `EngineV2(s, engine.injections)` replayed from t=0 == the live log (tested for a past onset, a future failure with a past onset, a future onset, and DEAD). `inject` after the run finished raises `RuntimeError`.
- `snapshot()/restore()`: JSON bytes (floats round-trip exactly), no pickle, so a blob is data. A fingerprint (sha256 of the scenario JSON, `n_sats`, log schema version) is checked on restore; a mismatch or a non-snapshot raises `ValueError`. `run(cancel_event)` raises `RunCancelled` between ticks.
- The chief has no drag, so dragged deputies drift relative to it (see Known limits).

## Scenario fields added (all defaulted; every `data/scenarios/*.json` validates unchanged, `tests/v2/test_schema_v2.py`)
| Field | Default | Source |
|---|---|---|
| `engine` | `"v1"` | `Literal["v1","v2"]` |
| `chief.inclination_deg` | 97.4 | illustrative (SSO-like) |
| `chief.raan_deg` | 0.0 | illustrative |
| `chief.epoch_utc` | `2026-03-20T12:00:00Z` | illustrative fixed date; stored, not used by Phase 1 (reserved for the Phase 2 sun vector) |
| `truth.cd` | 2.2 | illustrative |
| `truth.area_active_m2` | 0.010 | illustrative: 10 x 10 cm end-on face of a 10 x 10 x 30 cm box |
| `truth.area_dead_m2` | 0.035 | illustrative: tumbling mean projected area = surface/4 = 1400 cm^2 / 4 |
| `truth.mass_kg` | 4.0 | illustrative |
| `truth.density_factor` | 1.0 | multiplier on rho; 0 = drag off; not time-scheduled yet |
| `truth.j2_enabled` | true | validation switch |

Bounds (all new floats reject NaN/inf; they only keep every log finite and are not claims about hardware): inclination 0..180 deg, raan -360..360 deg, `cd` in (0, 10], areas in (0, 100] m^2, mass 1e-3..1e4 kg, `density_factor` 0..1e4; `epoch_utc` must parse with `datetime.fromisoformat`. Rejected inputs are pinned by `tests/v2/test_p1_fixes.py::test_schema_rejects_non_finite_or_absurd_values`.

## Validation numbers (each: value, then the command)
| Check | Measured | Threshold | Command |
|---|---|---|---|
| J2 vs central-difference gradient of U_J2, relative error | 2.680e-11 | < 1e-5 | `uv run python -m pytest tests/v2/test_truth_accel.py::test_j2_matches_potential_gradient -s` |
| King-Hele decay per rev at 500 km, active (A = 0.010 m^2) | -1.1415 m | -1.14 m, 5% | `uv run python -m pytest tests/v2/test_truth_accel.py::test_drag_decay_per_rev_king_hele -s` |
| King-Hele decay per rev at 500 km, dead (A = 0.035 m^2) | -3.9952 m | -3.99 m, 5% | same |
| RK4 numeric decay per rev, active / dead (polar orbit, energy-based a) | -1.1401 m / -3.9903 m | 5% | `uv run python -m pytest tests/v2/test_truth_integrate.py::test_drag_decay_numeric_per_rev -s` |
| LVLH round trip, worst absolute error | 4.502e-10 m | < 1e-6 m | `uv run python -m pytest tests/v2/test_truth_integrate.py::test_lvlh_roundtrip_under_1e6_m -s` |
| RK4 (dt = 2 s) vs scipy RK45 (rtol 1e-12), two-body + J2, 3 orbits, 500 km, position | 6.278e-04 m | < 1e-2 m | `uv run python -m pytest tests/v2/test_truth_integrate.py::test_rk4_dt2_vs_rk45_two_body_j2_3orbits_500km -s` |
| same, against a scipy DOP853 reference (rtol 1e-13, atol 1e-10) | 7.737e-05 m (the RK45 and DOP853 references differ from each other by 5.458e-04 m, so the 6.278e-04 m figure is dominated by the RK45 reference error, not by RK4) | < 1e-2 m | same command (it prints all three numbers) |
| RK4 numeric decay per rev at the scenario inclination 97.4 deg, active / dead; ratio to the polar value | -1.1595 m / -4.0582 m; 1.0170 | 5% of -1.14 / -3.99; ratio in 1.010..1.030 | `uv run python -m pytest tests/v2/test_truth_integrate.py::test_drag_decay_numeric_per_rev_at_scenario_inclination -s` |
| Engine decay per rev (J2 off), chief / dead / THRUSTER_OUT / active | -1.51e-07 / -4.0595 / -1.1598 / -1.1598 m (dead/active 3.5, THRUSTER_OUT/active 1.0) | chief < 0.01 m; dead/active in 3.3..3.7 | `uv run python -m pytest tests/v2/test_engine_behaviour.py::test_decay_dead_vs_active_vs_thruster_out_and_chief_has_no_drag -s` |
| Chief RAAN drift over 6 orbits vs `-1.5 n J2 (Re/a)^2 cos i` | 6.807e-03 rad vs 6.780e-03 rad | within 5% | `uv run python -m pytest tests/v2/test_engine_behaviour.py::test_chief_nodal_precession_matches_j2_secular_rate -s` |
| G1 state (1 km radial, 500 m cross-track), J2 off, drag off, v2 vs CW, 3 orbits | 3.1026 m | 3.101 m + 10% = 3.411 m | `uv run python -m pytest tests/v2/test_sim_v2_truth.py -m slow -s -k "3p1_m and not 1orbit"` (slow-marked, 5 s) |
| same, 1 orbit | 1.0680 m | 3.411 m | `uv run python -m pytest tests/v2/test_sim_v2_truth.py -s -k 3p1_m_1orbit` |
| same state, J2 on, 1 orbit (new measured number) | 44.8058 m | finite | `uv run python -m pytest tests/v2/test_sim_v2_truth.py -s -k j2_on` |
| 6 ring slots at 1 km (planar: z amplitude = x), J2/drag off, 1 orbit: engine vs independent two-body RK45 (`cubesat/cw_curve.py`) | 6.208 m vs 6.208 m | within 2% | `uv run python -m pytest tests/v2/test_sim_v2_truth.py -s -k independent_kepler` |

The 3.101 m figure is specific to the G1 evidence state; the ring slots are a different state (z amplitude 1 km) and the same independent reference gives 18.5 m for them over 3 orbits.

## CW-vs-truth report (`data/eval/cw_vs_truth_report.json`)
Command: `uv run python -m cubesat.cw_truth --report data/eval/cw_vs_truth_report.json` (about 42 s). Passive formation (a_max 1e-12 m/s^2), 6 ring slots, 3 orbits, 500 km, i = 97.4 deg; metric: max over sats and ticks of |r_v2 - r_CW| in LVLH.

| Radial amplitude | J2 | drag | max position difference |
|---|---|---|---|
| 1 km | off | off | 18.5432 m |
| 1 km | off | on | 49.3207 m |
| 1 km | on | off | 131.3361 m |
| 1 km | on | on | 184.5916 m |
| 8 km | off | off | 1189.1305 m |
| 8 km | off | on | 1144.6752 m |
| 8 km | on | off | 1993.2687 m |
| 8 km | on | on | 1944.8957 m |

The same file holds `g1_state`: v2 vs CW 3.1026 m, CW vs two-body RK45 (`cw_curve`) 3.1009 m.

How to read the drag-on rows: the virtual chief is not dragged, so with drag on every deputy sinks relative to it. After 3 orbits the drag shifts every deputy along-track by 49.1 to 49.3 m at 1 km and 48.4 to 50.5 m at 8 km (`uv run python -m pytest tests/v2/test_sim_v2_truth.py -m slow -s -k shifts`), independent of amplitude. At 1 km this adds to a small CW error (49.3207 m vs 18.5432 m); at 8 km the shift has the opposite sign to the negative along-track CW error, which is why the 8 km drag-on figure (1144.6752 m) is below drag-off (1189.1305 m). The metric is therefore the formation drifting ahead of an undragged reference, not differential drag between sats.

## Randomness: one Generator, one draw-order table
`sim_v2.make_rng(scenario)` = `numpy.random.Generator(PCG64(SeedSequence(scenario.seed)))`, created once at tick 0, owned by the engine, saved in `snapshot()`. v1 never touches it. Per tick, sats in ascending id; each sat draws ALL seven rows in table order, whether or not its event fires (the conditional rows are drawn and used only on a hit), so a hit never shifts any later draw. This amends the first Phase 1 version, where rows 4, 6, 7 were hit-only and a hit moved every later heartbeat/noise draw. New rows are appended, never inserted. Phase 1 draws all rows and ignores them (`sim_v2.draw_tick`). The names are asserted by `tests/v2/test_draw_order.py::test_doc_table_matches`, the call sequence by `tests/v2/test_p1_fixes.py::test_all_seven_rows_drawn_per_sat_per_tick` and `::test_tick1_heartbeat_independent_of_a_hit_at_tick0`.

| # | Draw | Call | Phase | Drawn |
|---|---|---|---|---|
| 1 | `heartbeat_loss` | `rng.random()` | 4 | every sat, every tick |
| 2 | `measurement_noise` | `rng.standard_normal(6)` | 4 | every sat, every tick |
| 3 | `seu` | `rng.random()` | 3 | every sat, every tick |
| 4 | `seu_duration` | `rng.uniform(30, 120)` | 3 | every sat, every tick (used on an SEU hit) |
| 5 | `impact` | `rng.random()` | 3 | every sat, every tick |
| 6 | `impact_component` | `rng.random()` | 3 | every sat, every tick (used on an impact hit) |
| 7 | `impact_fraction` | `rng.uniform(0.2, 0.6)` | 3 | every sat, every tick (used on an impact hit) |

## Determinism
Same scenario + seed gives identical bytes on one machine: `uv run python -m pytest tests/v2/test_sim_v2_truth.py -k byte_identical` and, from the CLI, two `uv run python -m cubesat.run --scenario <two_failure.json with "engine": "v2", "duration_s": 1800> --seed 42 --out a.jsonl|b.jsonl` runs compared with `cmp` (identical at the gate).

## Known limits (Phase 1)
- Logged LVLH velocity uses `omega = (0, 0, |h|/r^2)` as in the brief. With J2 on the chief frame is not exactly that rotation, so the logged `v` differs from the finite difference of the logged `r`: at 8 km over one orbit max |v - d(rho)/dt| = 6.359e-03 m/s with J2 on and 1.453e-05 m/s with J2 off (`uv run python -m pytest tests/v2/test_sim_v2_truth.py -k velocity_vs -s`).
- The drag-on CW-vs-truth rows measure the formation sinking relative to an undragged virtual chief (see the report section), not differential drag.
- The RK4-vs-RK45 6.278e-04 m figure is mostly RK45 reference error; against DOP853 (rtol 1e-13) the RK4 dt = 2 s error is 7.737e-05 m (validation table).
- The King-Hele decay tests at 500 km use a polar orbit (the co-rotating atmosphere then does not change |v_rel| along-track); at the scenario's 97.4 deg the numeric decay is 1.7% larger (-1.1595 m active, -4.0582 m dead), still inside the 5% tolerance and pinned by a ratio test.
- Density: the Vallado rows other than 450/500/600/700 km are not verified against the printed book (book check pending); static exponential atmosphere, no solar-activity, diurnal or latitude variation; below 150 km the 150 km value is held constant, and the 100 km re-entry threshold is a guard, not a decay model.
- Thrust is held fixed in ECI over each 2 s step (the LVLH frame turns 2.2e-3 rad per step) rather than rotating with it: about 1e-4 m/s per saturated step (`tests/v2/test_engine_behaviour.py::test_pd_thrust_direction_and_dv_used_after_one_step`).
- `frame["event"]` consumers see only the first of several simultaneous events; read `events`.
- Spherical-altitude density; no attitude, SRP, third body or tides; constant drag area per status; PD seat holding with the v1 controller (v1 gains and the v1 a_max demand); no resources, hazards, detector, recovery or certificate (later phases).

## Mutation check (Phase 1 review fixes)
Method: copy the worktree to a scratch directory (never the original), apply one mutation at a time with a string replacement, run `pytest tests/v2 -m "not slow" -x`, record the first failing test; the unmodified copy passes. All 17 mutants were killed:

| Mutant | First failing test |
|---|---|
| M2b density row = nearest instead of largest `h0 <= h` | `test_truth_accel.py::test_density_uses_largest_h0_not_nearest_row` |
| M3 dead area switch removed | `test_engine_behaviour.py::test_decay_dead_vs_active_vs_thruster_out_and_chief_has_no_drag` |
| M6 chief gets drag | same |
| M26 THRUSTER_OUT uses the dead area | same |
| M7 `fired` not restored | `test_engine_behaviour.py::test_restore_recovers_every_state_field_and_reaches_summary` |
| M8 `cov` not restored | same |
| M9 DCM transpose in the thrust rotation | `test_engine_behaviour.py::test_pd_thrust_direction_and_dv_used_after_one_step` |
| M14 thrust sign | same |
| M12 `dv_used` without `dt` | same |
| M10 no RNG draw per tick | `test_engine_behaviour.py::test_engine_consumes_one_draw_tick_per_step` |
| M11 detection one tick late | `test_engine_behaviour.py::test_dead_sat_declared_after_k_missed_heartbeats` |
| M16 no Earth rotation in drag | `test_truth_accel.py::test_drag_includes_earth_rotation_on_an_equatorial_orbit` |
| M18 DEGRADE_START late | `test_engine_behaviour.py::test_eps_fade_starts_at_onset_and_sat_keeps_holding_its_seat` |
| M28 DEGRADED sat not seat-held | same |
| M19 dead imagers counted in coverage | `test_engine_behaviour.py::test_dead_imager_is_excluded_from_coverage` |
| M20 chief without J2 | `test_engine_behaviour.py::test_chief_nodal_precession_matches_j2_secular_rate` |
| M27 THRUSTER_OUT sat still thrusts | `test_engine_behaviour.py::test_thruster_out_sat_does_not_thrust` |
