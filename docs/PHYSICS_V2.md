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

## Earth view data (2026-10-31; `cubesat/geo_v2.py`)
Fields (all v2-only, additive; the v1 wire and logs are unchanged):
- tick line / `sim_state`: `chief: {r_eci [x,y,z] m, lat_deg, lon_deg, alt_m}`, `station: {elevation_deg, visible}`.
- hello: `epoch_utc`, `inclination_deg`, `raan_deg`, `orbit_ring` (256 ECI points, m, 3 decimals), `ground_track` (257 [lat, lon], 4 decimals), `sun_vector_eci` (unit, 6 decimals), `ground_station {name, lat_deg, lon_deg, min_elevation_deg}`. No `time_warp` (no existing field to carry).

Models: GMST = IAU-1982 polynomial at the epoch (UT1 = UTC, < 0.9 s) + 7.2921159e-5 rad/s * t; geodetic on a spherical Earth of 6378.137 km; sun = Astronomical Almanac low-precision formula (~0.01 deg); ring and ground track are integrated with the engine's chief dynamics (gravity + J2, RK4 at `dt_s`; the negative half of the track uses negative steps); the station pass uses `cubesat/ground.py` constants and `elevation_deg`.

Measured (command: `uv run python -m cubesat.geo_v2`, scenario `two_failure.json` as v2):

| Quantity | Value |
|---|---|
| Chief period | 5676.978 s |
| Ring closure after one period (start to end distance) | 32458.3 m (J2 nodal-period phase drift, not an error) |
| Ring radius span | 0.106 % of the mean radius (J2) |
| Ground track max abs latitude | 82.590 deg (180 - 97.4 = 82.6) |
| Ring vs engine chief, samples on engine ticks, max abs diff | 0.0 m (bit identical; `tests/v2/test_geo_v2.py::test_ring_equals_engine_chief_at_matching_ticks`, tolerance 1e-6 m) |
| Sun declination 2000-06-21T01:48Z | 23.4389 deg (obliquity 23.4393) |
| Sun angle to +x at the 2000-03-20T07:35Z equinox | 0.0062 deg |
| hello Earth keys, compact JSON | 14798 bytes (limit tested < 60000) |
| `chief` + `station` per tick | 162 bytes |

Tests: GMST 2000-01-01T12:00Z = 280.46061837 deg and Meeus ex. 12.b; sun within 0.5 deg of +x at the 2000 equinox and declination 23.44 +- 0.1 deg at the June solstice (`uv run python -m pytest tests/v2/test_geo_v2.py`).

Honest limits: spherical Earth (latitude up to 0.2 deg off a real ellipsoid), UT1 = UTC, no precession/nutation/polar motion, constant rotation rate, sun fixed per run on the wire, the ring is one period of the J2-perturbed orbit and is open by 32 km, the ground track inherits the same J2 drift, one ground station, drag is not in the ring (the chief has none in the engine either).

## Cross-track phase psi (2026-10-31, Phase 5b; `cubesat/allocate_v2.py`, `cubesat/psi_table.py`)

**Definition.** Slots on the passive 2:1 relative orbit, `x = A cos(th)`, `y = -2A sin(th)`, `z = B cos(th + psi)`, `B = A`, `th = phase0 + 2 pi j/k`. `allocate_v2.candidate_slots(amp_m, phase0_rad, psi_deg, n_slots, n)` takes `(x, y, vx, vy)` from `hcw.slot_initial_state` at `th` and `(z, vz)` from the same function at `th + psi`, so `z = B cos(nt + th + psi)`, `vz = -B n sin(nt + th + psi)`: still passive (closes each period, zero fuel to hold). psi = 0 returns `hcw.slot_initial_state(A, A, th, n)` bit for bit, which is `sim.build_slots` (tested with `np.array_equal`). Scenario field `formation.cross_track_phase_deg`, default 0.0 (v1), finite, within +-360 deg, "v2 only; 0 reproduces v1 slots". The engine does not read it yet (not wired); the v2 packs are to set 30 (kit 2.2).

**Metric: worst separation under ANY along-track drift.** For slot pair (i, j): `min over t in [0, 2 orbits] and s in [-S, S] of |p_i(t) - (p_j(t) + s y_hat)|`, i.e. slot j (the dead one) is displaced by `s` along track. A y shift of the initial state shifts `y(t)` by exactly `s` at every `t` (CW y row has coefficient 1 on `y0` and nothing else depends on `y`), so the minimum over `s` is closed form, `s* = clip(dy, -S, S)`: no s grid and no s discretisation error; `S = 2 max|y|` sweeps the whole ring. Any drift `s(t)` can do no better than this min over (t, s), so it is a lower bound on the drift hazard. The result is the minimum over all pairs. Time grid: 2881 samples per orbit (about 2 s), halved to 1441 for the convergence delta (odd counts so no grid contains the symmetric minimiser time by luck).

**Coverage.** `allocate._coverage_estimate` unchanged (72 samples per orbit, union of footprints `r_f = h tan(fov_half)`, `coverage.target_grid`), 6 slots, 4 imagers, phase0 = 0. Seat layout is `allocate.seat_roles_for`'s (imagers on even seats: 0, 2, 4, 5) as the primary column; the column `coverage_scenario_order` uses the scenario role order (imagers on seats 0-3, `sim.py`'s initial formation).

**Measured (A = B = 8 km, h = 500 km, fov_half 1.5 deg, r_f = 13093 m, grid 30 km / 2 km).** Command: `uv run python -m cubesat.psi_table --report data/eval/psi_trade_table.json` (about 18 s), artifact `data/eval/psi_trade_table.json`.

| psi | coverage (even seats) | coverage (scenario order) | worst sep (m) | halved-grid delta (m) | brief coverage / sep |
|---|---|---|---|---|---|
| 0 | 0.4003 | 0.3710 | 0.0 | 0.0 | 0.371 / 11.8 |
| 15 | 0.3981 | 0.3697 | 1476.74 | 0.002 | - |
| 30 | 0.3890 | 0.3637 | 2928.20 | 0.000 | 0.364 / 2929 |
| 45 | 0.3772 | 0.3554 | 4329.57 | 0.000 | 0.355 / 4330 |
| 60 | 0.3625 | 0.3446 | 5656.85 | 0.000 | 0.345 / 5657 |
| 75 | 0.3482 | 0.3334 | 6887.35 | 0.000 | - |
| 90 | 0.3390 | 0.3259 | 8000.00 | 0.000 | 0.326 / 8000 |

**Disagreements with the brief (not tuned away).** (1) Separation reproduces within 0.03 percent for psi >= 30 (2928.2 vs 2929, 4329.6 vs 4330, 5656.9 vs 5657, 8000.0 vs 8000). (2) psi = 0: this metric gives 0.0 m, not 11.8 m. Slots j and k-j have equal `x` and `z` at t = 0 and differ only along track, so a dead satellite displaced by `dy` sits on top of its mirror neighbour; the unrestricted minimum is exactly 0, and the brief's 11.8 m is consistent with a discrete along-track offset grid (an s grid of step 24 m leaves up to 12 m; `s_step` in `pair_min_distance` reproduces this effect, tested). With `s = 0` only (no drift) the same formation is 11313.7 m apart at psi = 0, which is why the drift sweep matters. (3) Coverage: the brief's column is reproduced (max difference 0.0004, every row inside 0.003) only with imagers on seats 0-3; with `seat_roles_for`'s even layout coverage is 0.013 to 0.029 higher and all five rows are flagged (more than 0.003). Coverage is monotone non-increasing in psi in both layouts. The 2 km / fov_half 0.375 deg kit formation (illustrative, grid scaled by 1/4 so r_f/A is unchanged, r_f = 3272.5 m) gives the same coverage to the grid's resolution (psi = 30: 0.3890 / 0.3637) and the separation scales with A (psi = 30: 732.05 m, psi = 90: 2000.0 m).

**Bound.** psi = 90: neighbours at `dphi = 60 deg` stay `2 sin(dphi/2) min(A, B)` apart in the (x, z) plane at all times (a rotating circle); measured 8000.0 m = bound at A = 8 km, 2000.0 m at 2 km (`tests/v2/test_psi_table.py::test_psi90_matches_analytic_bound`). Mutation check on a copy (`/tmp/mut`): sign of psi, psi on x instead of z, wrong z amplitude, separation restricted to s = 0, coverage with all seats imaging, separation taken at t = 0 only: 6 of 6 killed.

## Phase 2 (fuel-first): spacecraft resources (`cubesat/spacecraft.py`, 2026-10-31)
Scope: propulsion, mass and failure modes as resource damage. Power, eclipse and safe/off modes (plan Task 2.2) are NOT built: `SatState` has no battery fields. Everything is engine `"v2"` only; v1 logs, canonical pins and v1 wire fixtures are untouched.

**Formulas** (g0 = 9.80665 m/s^2):
- thrust cap `|F| <= k F_max`, acceleration `a = F / m` with m the mass at the start of the step; a command under the cap passes through bit-unchanged, above it the vector is scaled (direction kept);
- mass flow `mdot = |F| / (Isp g0)`, propellant used per step `dm = |a| m dt / (Isp g0)`;
- tank delta-v `Isp g0 ln(m / (m - m_prop))` (log key `fuel_mps_left`);
- empty tank: zero thrust. A burn that would overdraw the tank is truncated on that step: the acceleration is scaled by `m_prop / dm`, so the step delivers exactly the impulse the remaining propellant buys, and `m_prop` is set to exactly 0 (never negative).

**Defaults (all ILLUSTRATIVE, not measured hardware):** a 3U cold-gas CubeSat; `truth.mass_kg` 4.0 kg is the WET mass (propellant included, dry = wet - m_prop), `spacecraft.m_prop_kg` 0.2, `isp_s` 40, `f_max_n` 0.04 (so 0.04 N / 4 kg = 0.01 m/s^2, the default `a_max`). Tank delta-v 20.12 m/s. Validation (engine v2 only; a v1 scenario ignores the block): `spacecraft.m_prop_kg <= 0.5 truth.mass_kg`, i.e. the dry mass is at least half the wet mass (plain error otherwise), because the drag model keeps the wet mass.

**Failure modes as resource damage** (`apply_failure(sat, mode, stuck_vec)`; the four new modes are rejected for engine `"v1"` scenarios with `failure mode X (sat N) requires engine "v2"`, so v1 JSON stays valid and unchanged):

| Mode | Resource damage | Status | Event |
|---|---|---|---|
| DEAD, EPS_DEGRADE (fade ends in death, as Phase 1) | k=0, payload and radio off | DEAD | heartbeat rule after K misses |
| THRUSTER_OUT | k=0 | THRUSTER_OUT | FAILURE_DETECTED self_report |
| PARTIAL_THRUST | k=0.5 | DEGRADED | none (silent) |
| THRUSTER_STUCK_OPEN | constant `STUCK_K F_max` (module constant `STUCK_K` = 1.0, valve fully open, illustrative) along a unit ECI vector fixed at failure time (the sat's ECI velocity direction then; no random draw), PD ignored, until the propellant is empty | DEGRADED | none (silent) |
| PAYLOAD_FAIL | payload_ok = False: flies and seat-holds, excluded from coverage | PAYLOAD_FAILED | FAILURE_DETECTED self_report |
| RADIO_FAIL | radio_ok = False: flies and seat-holds, silent heartbeat | RADIO_SILENT | FAILURE_DETECTED after K misses (heartbeat rule) |
| (any sat, tank empty) | m_prop = 0 and k = 0 (at the moment the tank empties; a sat that starts empty is announced at t=0) | FUEL_DEPLETED | self-report, once, like THRUSTER_OUT: `FAILURE_DETECTED` {mode FUEL_DEPLETED, self_report} then `FUEL_DEPLETED` {sat_id, t}; mission state FAILURE_DETECTED |

Status precedence: a new failure only raises the label (NOMINAL < DEGRADED < PAYLOAD_FAILED < THRUSTER_OUT < FUEL_DEPLETED < RADIO_SILENT < DEAD < REENTERED); `fail_mode` and `t_fail` follow the label when it is raised. The flags (k, payload_ok, radio_ok, stuck) carry the full truth, so a PARTIAL_THRUST after THRUSTER_OUT keeps k = 0 (`min(k, 0.5)`) and nothing acts on a DEAD sat. A silent sat (radio failed) cannot self-report: a later THRUSTER_OUT or an empty tank on it announces nothing and keeps the RADIO_SILENT label. FUEL_DEPLETED behaves like THRUSTER_OUT (brief section 4 Phase 2): self-reported, k = 0, mission state FAILURE_DETECTED; it still flies and its camera counts for coverage.

**Detection latch.** `declared[i]` latches only the heartbeat (silence) declaration. A self-report (THRUSTER_OUT, PAYLOAD_FAIL, FUEL_DEPLETED) never sets it, so a benign self-reported fault cannot hide a later death or radio loss: PAYLOAD_FAIL then EPS_DEGRADE death emits FAILURE_DETECTED twice (self-report, then the heartbeat declaration of the death). A silence caused by re-entry announces mode `REENTRY` with `t_fail` = the re-entry time. DEGRADE_START is announced once per sat at the fade onset unless the sat's label is already worse than DEGRADED.

**Engine wiring and log keys** (additive, v2 only; v1 sat rows keep exactly `id, role, status, r, v, dv_used`): per sat `fuel_kg`, `fuel_mps_left`, `k`, `stuck` (a stuck-open valve is burning or dry; visible even when the label is THRUSTER_OUT), `payload_ok`, `radio_ok`; `dv_used` keeps its meaning (sum of the applied |a| dt). Coverage counts only imagers whose payload works and that are not DEAD/REENTERED.

**Simplifications (stated, not hidden):**
- Drag ballistic coefficient B stays `truth.mass_kg` (the wet mass) for the whole run: the propellant fraction is 5% by default, so B is up to 5% low as the tank empties. Not modelled.
- Acceleration uses the mass at the START of each step, so the sum of `a dt` undershoots the rocket-equation tank delta-v: 20.1201 vs 20.1206 m/s (5.3e-4 m/s, 2.6e-5 relative) at dt = 2 s over a full tank.
- The stuck direction is a fixed ECI vector (the sat's velocity direction at failure), not a body-fixed vector that rotates with attitude; stuck_k = 1 and the PD cannot counter the stuck thruster.
- Zero-order hold: thrust is constant over a step, so a truncated burn is a scaled constant acceleration over the whole step, not a shorter burn at full thrust (same impulse).

**Validation numbers (each: value, then the command):**

| Quantity | Measured | Threshold | Command |
|---|---|---|---|
| Acceleration cap, k=1 / k=0.5 | 0.01 / 0.005 m/s^2 (rel 1e-12) | 0.04/4, 0.02/4 | `uv run python -m pytest tests/v2/test_spacecraft.py::test_accel_saturates_at_k_fmax_over_m` |
| Mass flow at full thrust | 1.0197e-4 kg/s = 0.04/(40 g0) | rel 1e-12 | `uv run python -m pytest tests/v2/test_spacecraft.py::test_mass_flow_isp` |
| Tank delta-v, 4.0 -> 3.8 kg | 20.1206 m/s | 20.12 +- 0.05 | `uv run python -m pytest tests/v2/test_spacecraft.py::test_delta_v_budget_20p1 -s` |
| Full-tank burn at 2 s steps: time to empty, sum a dt | 1962 s, 20.1201 m/s | rocket eq within 2e-3 | `uv run python -m pytest tests/v2/test_spacecraft.py::test_propellant_never_negative_over_a_long_saturated_burn` |
| Truncated step (1e-4 kg left) | dv step = 0.01 x 0.4903 x 2 s, matches Isp g0 ln(4/3.9999) to 1e-4 | exact, m_prop == 0.0 | `uv run python -m pytest tests/v2/test_spacecraft.py::test_burn_truncated_on_the_step_that_exhausts_the_tank tests/v2/test_sim_v2_resources.py::test_propellant_exactly_exhausted_mid_burn_truncates_that_step` |
| Stuck-open whole tank (0.002 kg) | 0.1962 m/s, stops with the tank | rocket eq 1e-3 | `uv run python -m pytest tests/v2/test_failure_modes_v2.py::test_stuck_open_burns_constant_thrust_ignores_the_pd_and_stops_when_the_tank_empties` |
| Radio-failed sat vs no-failure run | trajectory bit-identical, declared at t=104 | exact | `uv run python -m pytest tests/v2/test_failure_modes_v2.py::test_radio_failed_sat_keeps_flying_and_is_declared_by_the_heartbeat_rule` |
| two_failure as v2, fuel use (PD seat-holder, no recovery) | table below | measurement | `uv run python -m pytest tests/v2/test_fuel_demo_two_failure.py -s` |

**Measured fuel demonstration** (`data/scenarios/two_failure.json` with `engine "v2"`, `a_max_mps2` 0.01, spacecraft 0.2 kg / Isp 40 s / F_max 0.04 N, duration 17028 s = 3 orbits; sats 1 and 2 die at 1200 and 1500 s; the controller is the v1 PD seat-holder with no recovery, so this measures what the PD seat-holder spends to keep its slots, not a planner; the attribution below says where that goes):

| sat | role | final status | dv_used m/s | propellant used kg | tank left m/s | ran dry |
|---|---|---|---|---|---|---|
| 0 | leader | NOMINAL | 1.6608 | 0.016900 | 18.4598 | no |
| 1 | imager | DEAD (t=1200) | 0.0653 | 0.000665 | 20.0554 | no |
| 2 | imager | DEAD (t=1500) | 0.1192 | 0.001215 | 20.0014 | no |
| 3 | imager | NOMINAL | 1.6733 | 0.017026 | 18.4473 | no |
| 4 | imager | NOMINAL | 1.6730 | 0.017023 | 18.4476 | no |
| 5 | downlink | NOMINAL | 1.6765 | 0.017059 | 18.4441 | no |

No sat runs dry in 3 orbits: the survivors use about 8.5% of the 0.2 kg tank (1.66-1.68 of 20.12 m/s).

**Where the survivor fuel goes** (same scenario and spacecraft block, three truth configurations; command `uv run python -m pytest tests/v2/test_fuel_attribution.py -s`, survivor dv_used in m/s for sats 0, 3, 4, 5):

| truth | sat 0 | sat 3 | sat 4 | sat 5 |
|---|---|---|---|---|
| full (J2 and drag) | 1.6608 | 1.6733 | 1.6730 | 1.6765 |
| two-body only (J2 off, density_factor 0) | 0.9049 | 0.9049 | 0.9042 | 0.9043 |
| drag only (J2 off) | 0.9049 | 0.9049 | 0.9042 | 0.9044 |

Drag is not what the survivors pay for: drag-only differs from two-body-only by at most 1.12e-5 m/s. About 0.90 m/s is spent with gravity only, i.e. the cost of the PD controller tracking a linear (HCW) slot reference against the nonlinear two-body truth at the 8 km formation amplitude (a model mismatch, not a perturbation); J2 adds a further 0.76-0.77 m/s (full minus two-body, smallest gap 0.7559). The test asserts drag-only within 1e-2 m/s of two-body-only and full above two-body-only. This is why the 2 km formation (the mismatch shrinks with the amplitude squared) is the planned v2 default; the 2 km number itself is UNMEASURED until a run exists. Not claimed: any lifetime extrapolation, any recovery cost (a re-formation transfer is Phase 5).

**Honest limits (Phase 2 fuel-first):** no power or eclipse model; no SEU, impact or aging; no propellant leak; the heartbeat rule is still the only detector, so PARTIAL_THRUST and THRUSTER_STUCK_OPEN are never declared (Phase 4); the recovery planner does not read `fuel_mps_left` yet (Phase 5); `wire.py` (inject message model `Literal`) still lists only the three v1 modes and `_STATUS_TO_WIRE` does not map the new statuses (a status string passes through unmapped); `wire.py`, `session.py` and `api.py` are outside this change.

**Mutation check (Phase 2, after the review fixes).** Method as above on a scratch copy (`/tmp/kmut`, script kept out of the repo): one string replacement at a time, run the five Phase 2 test files (`tests/v2/test_spacecraft.py`, `test_failure_modes_v2.py`, `test_sim_v2_resources.py`, `test_p2_review_fixes.py`, `test_p2_mutant_pins.py`) with `-x`, first failing test recorded. 28 mutants run, 27 killed; the survivor is an equivalent mutant.

| Mutant | First failing test |
|---|---|
| thrust cap comparison flipped | `test_spacecraft.py::test_accel_saturates_at_k_fmax_over_m` |
| mass flow dropped | `test_spacecraft.py::test_command_below_cap_passes_through_unchanged` |
| negative propellant allowed | `test_spacecraft.py::test_propellant_never_negative_over_a_long_saturated_burn` |
| k ignored in the cap | `test_spacecraft.py::test_accel_saturates_at_k_fmax_over_m` |
| coverage ignores payload_ok | `test_failure_modes_v2.py::test_payload_failed_sat_excluded_from_coverage_but_still_seat_holds` |
| radio failure not silent | `test_failure_modes_v2.py::test_radio_failed_sat_keeps_flying_and_is_declared_by_the_heartbeat_rule` |
| stuck vector recomputed each step (M07) | `test_p2_mutant_pins.py::test_stuck_open_thrust_is_a_frozen_eci_vector_along_the_failure_velocity` |
| stuck thrust applied as LVLH (M08) | same |
| PAYLOAD_FAILED / THRUSTER_OUT ranks swapped (M13a) | `test_p2_mutant_pins.py::test_failure_matrix_status_rank_k_fail_mode_and_t_fail[fails4-want4]` |
| RADIO_SILENT ranked below FUEL_DEPLETED (M13b) | `test_sim_v2_resources.py::test_radio_silent_sat_that_runs_dry_stays_silent_and_announces_nothing` |
| DEGRADED ranked above PAYLOAD_FAILED (M13c) | `test_p2_mutant_pins.py::test_failure_matrix_status_rank_k_fail_mode_and_t_fail[fails2-want2]` |
| FUEL_DEPLETED ranked above RADIO_SILENT (M13d) | `test_sim_v2_resources.py::test_radio_silent_sat_that_runs_dry_stays_silent_and_announces_nothing` |
| FUEL_DEPLETED event emitted for a silent sat (M20) | same |
| depletion lowers a higher label (M24) | same |
| PARTIAL_THRUST after THRUSTER_OUT restores k (M25) | `test_p2_mutant_pins.py::test_failure_matrix_status_rank_k_fail_mode_and_t_fail[fails1-want1]` |
| fail_mode / t_fail not updated when the label is raised (M26) | `test_failure_modes_v2.py::test_self_report_then_eps_fade_death_is_still_declared` |
| self-report latches `declared` again (A1) | same |
| depletion does not zero k in Faults (A2) | `test_sim_v2_resources.py::test_zero_fuel_start_is_announced_at_t0_with_k_zero` |
| no FAILURE_DETECTED at depletion (A2) | `test_sim_v2_resources.py::test_fuel_never_negative_and_depleted_status_and_event_once` |
| DEGRADE_START only from NOMINAL (B3) | `test_p2_review_fixes.py::test_degrade_start_not_lost_after_partial_thrust` |
| `stuck` log key always False (B4) | `test_p2_review_fixes.py::test_stuck_flag_logged_while_label_is_thruster_out_and_fuel_falls[order0]` |
| dry-mass floor off (B5) | `test_p2_review_fixes.py::test_dry_mass_must_be_at_least_half_the_wet_mass_for_v2_only` |
| restore mutates the engine before `faults.load` (B6) | `test_p2_review_fixes.py::test_restore_of_a_partial_snapshot_raises_valueerror_and_changes_nothing[drop0]` |
| re-entry silence keeps the failure label (B7) | `test_p2_review_fixes.py::test_reentry_silence_announces_reentry_not_the_failure_label` |
| stuck-open treated as nominal | `test_failure_modes_v2.py::test_mode_THRUSTER_STUCK_OPEN_semantics` |
| v2-only mode validator off | `test_failure_modes_v2.py::test_v1_scenarios_with_v2_modes_are_rejected_with_a_plain_message[PAYLOAD_FAIL]` |
| survivor (equivalent): `Faults.load` catches `(TypeError, ValueError)` only | none: `EngineV2.restore` also catches KeyError and re-raises ValueError, so the observable behaviour is identical |

## Phase 5a: capability roles (2026-10-31; `cubesat/roles_v2.py`, `sim_v2.py`, `scenario.role_priority`)

Engine v2 only; v1 keeps its labels and logs byte for byte. **Power is NOT modelled** (no battery, Task 2.2 unbuilt): the "power" need of the master-map role table is treated as always satisfied. Roles are a pure function of the live statuses (plus the incumbents); this phase moves no one: motion is unchanged, nothing is replanned, so the numbers below measure the assignment rule, not a recovery planner.

**`capability(status, payload_ok, radio_ok, role) -> bool`.** `ROLE_SPECS` (critical, stackable, needs): leader (True, True, radio), downlink (True, False, radio), imager (False, False, payload), relay (False, True, radio), spare (False, True, none). Reporting statuses = NOMINAL, DEGRADED, FUEL_DEPLETED, THRUSTER_OUT, PAYLOAD_FAILED (no role here needs thrust, so a dry or thruster-dead sat still images and talks). imager: `payload_ok` and a reporting sat (a dead payload takes no images; an image that cannot be reported is not coverage). downlink / leader / relay: `radio_ok` and a reporting sat. RADIO_SILENT flies but nothing it does reaches ground: it holds only `spare`. DEAD and REENTERED hold nothing whatever their (stale) flags say. Unknown role: ValueError.

**`assign_roles(sats, priority=("downlink","imager","leader")) -> list[list[str]]`.** Each sat dict: `status`, `payload_ok`, `radio_ok`, `roles` (the incumbents). Roles are filled in priority order; per role `linear_sum_assignment` on rows = sats, columns = seats (1 for a critical role, max(1, capable incumbents) otherwise, so a lost imager is not replaced). Cost: incapable `1e6` (finite, never inf), incumbent 0, otherwise 1 + 2 per non-stackable role the sat already holds or critical role it holds now (a role stacks onto a busy sat only when no free capable sat exists; leader on an imager when two sats survive; downlink avoids the leader's sat), plus the `1e-9` row-major index epsilon (ties go to the lowest id). A seat that lands on an incapable sat stays VACANT (`vacant_roles`). A capable sat with nothing holds `["spare"]`; an incapable or dead one `[]`. Deterministic, no RNG, input not mutated.

**Engine log (v2 only).** Per sat: `roles` (list, priority order), `role` (primary = `roles[0]`, `"none"` when empty; a stacked leader on an imager therefore shows `imager`), `original_role` (the scenario label). Coverage counts sats whose `roles` contain `imager`: a PAYLOAD_FAILED or RADIO_SILENT imager is excluded (RADIO_SILENT is new: Phase 2 still counted it), and with no failure the numbers equal the Phase-2 rule (`test_coverage_reproduces_the_phase2_rule`). Event `ROLE_HANDOFF {role, from_sat, to_sat, reason}` is emitted, appended to the tick's `events`, ONLY when leader or downlink changes holder (`to_sat` null = vacant, `from_sat` null = was vacant; `reason` = the old holder's status, `VACANT` if none). Incumbent role state is in the engine snapshot (`state.roles`); a snapshot without it is refused (ValueError, engine untouched). `Scenario.role_priority` (default `["downlink","imager","leader"]`, unique known names, engine v2 only).

**Measured (command: `uv run python -m pytest tests/v2/test_roles_demo.py -s -m slow`, two_failure.json as engine v2, a_max 0.01, default 0.2 kg spacecraft block, sat i DEAD at 1200 s and sat j at 1500 s, last tick t = 17028 s; 2 min 48 s):**

| pair (i,j) | leader | downlink | imagers | coverage at last tick |
|---|---|---|---|---|
| (0,1) | 2 | 5 | 3 | 0.3319 |
| (0,2) | 1 | 5 | 3 | 0.3528 |
| (0,3) | 1 | 5 | 3 | 0.3392 |
| (0,4) | 1 | 5 | 3 | 0.2893 |
| (0,5) | 1 | 2 | 4 | 0.3840 |
| (1,2) | 0 | 5 | 2 | 0.2373 |
| (1,3) | 0 | 5 | 2 | 0.2851 |
| (1,4) | 0 | 5 | 2 | 0.2373 |
| (1,5) | 0 | 2 | 3 | 0.3319 |
| (2,3) | 0 | 5 | 2 | 0.2851 |
| (2,4) | 0 | 5 | 2 | 0.2581 |
| (2,5) | 0 | 1 | 3 | 0.3528 |
| (3,4) | 0 | 5 | 2 | 0.1967 |
| (3,5) | 0 | 1 | 3 | 0.3392 |
| (4,5) | 0 | 1 | 3 | 0.2893 |

Leader and downlink each held by exactly one capable sat in **15/15** pairs (expected: it is a pure assignment, so this is a consistency check, not a recovery result). 4 of 6 dead (all 15 subsets, failures at 1200/1300/1400/1500 s): leader + downlink + at least one imager held in **15/15**; 5 of 6 dead (6 subsets): **6/6** (the survivor holds all three). v1 benchmark numbers are not comparable (different engine, a_max 0.1, recovery on). Not claimed: delivered coverage (needs a downlink path, Phase 6); that a role hand-off is free (it is a label change, no handover time); any power constraint.

**Mutation check (copy of the tree under /tmp, tests/v2/test_roles_{capability,assign,engine}.py, first failing test shown):**

| Mutant | Killed by |
|---|---|
| drop the capability gate | `test_four_of_six_dead_keeps_imager` |
| incapable cost 0.5 instead of 1e6 | `test_four_of_six_dead_keeps_imager` |
| ignore incumbents | `test_v1_roles_map_onto_same_initial_holders` |
| reverse the priority order | `test_four_dead_with_the_critical_holders_among_the_dead` |
| a RADIO_SILENT sat may hold the leader | `test_radio_silent_holds_nothing_that_needs_radio` |
| two downlink seats | `test_v1_roles_map_onto_same_initial_holders` |
| ROLE_HANDOFF for non-critical roles | `test_no_handoff_without_a_critical_change` (this test was first too weak: it did not move the first imager; strengthened) |
| roles not restored from the snapshot | `test_snapshot_carries_role_state` |
| dead sat keeps its role label | `test_four_of_six_dead_keeps_imager` |
| critical-role pile-up allowed | `test_a_lost_critical_role_avoids_the_sat_that_already_holds_the_other_one` (found by the demo: pair (0,5) first stacked downlink + leader + imager on sat 1; fixed with a red test) |
| stacking penalty removed | `test_four_dead_with_the_critical_holders_among_the_dead` |

## Phase 5a fix round (2026-10-31, after the adversarial review; supersedes the 5a section above where they differ)

Roles still move nobody: v2 motion (r, v, dv_used) is unchanged (sha256 prefixes of four scenarios below). All numbers below are printed by the quoted commands.

**What changed, and why.**
- **Roles follow what the swarm believes (`roles_v2.believe`).** A silent failure (DEAD, dead radio, REENTERED) keeps the sat's roles until the heartbeat rule declares it; a self-reported failure (PAYLOAD_FAIL, FUEL_DEPLETED, THRUSTER_OUT, from a sat whose radio works) is believed at once. So `ROLE_HANDOFF` is emitted in the SAME tick as the `FAILURE_DETECTED` of the dead holder: DEAD at t = 100 s: both at t = 104 s ((K - 1) dt, K = 3, dt = 2 s); RADIO_FAIL at 200 s: both at 204 s. A radio-silent sat cannot announce a payload failure: its true state is believed only once declared. Coverage stays physical (a dead payload takes no images at the failure tick even while its role is kept). Believed state is in the engine snapshot (`state.believed`).
- **`role` is a display label in a fixed order** (leader, downlink, imager, then spare; `none` when empty); `roles` is the truth. A stacked leader shows `leader`. `benchmark.metrics_from_log` and the wire read `roles` when the log has it and fall back to `role` (v1). Measured (`uv run python -m pytest tests/v2/test_roles_demo.py -s -m slow -k vacancy`): v2 nominal, leader dead at t = 100: critical roles held at the end True, `critical_vacancy_s` **4.0** (= detection latency: ticks 100 and 102 have a dead, undeclared holder), imagers_end 4; downlink dead: True / 4.0 / 4; both dead: True / 4.0 / 3.
- **Imager seats = min(original imager count, imager-eligible survivors).** Eligible = capable (payload ok, flying, reporting) and not holding the downlink, which does not image; when nobody else is capable the downlink holder images (a lone survivor keeps every role). Incumbent imagers keep their seats; a leader-only or spare sat with a working payload is re-roled to imager up to the original count (a label change, zero fuel; no motion). `imager_seats` is an argument of `assign_roles` (the engine passes the scenario's imager count).
- **`role_priority` must be a permutation of downlink, imager, leader** (plain error otherwise); `relay` is deleted; `spare` is only an output label. The engine fills only roles the scenario labels: a scenario with no downlink (live_2sat) has it vacant from the start, and no `ROLE_HANDOFF` is emitted at t = 0 (live_2sat, live_8sat, live_12sat tested). A second sat labelled `downlink` (live_8sat, live_12sat) keeps `original_role: "downlink"`, is not assigned the role (the lowest id holds it) and shows `["spare"]`.
- **Order dependence of the guards (documented, pinned).** The "no leader + downlink on one sat" guard is greedy in priority order. Sats [NOMINAL leader, NOMINAL empty, DEAD downlink]: with (imager, leader, downlink) and (leader, imager, downlink) the downlink lands on the leader's sat (both pile up) while the other sat images; with the default (downlink, imager, leader) and the other three orders it does not. The reviewer's original repro (priority (leader, downlink, imager)) no longer piles up since the guard also counts the critical roles a sat already holds. All six orders on two and three capable survivors are pinned in `tests/v2/test_roles_assign.py` (`PIN_A`, `PIN_C`), and a test sweeps every 2-capable-of-3 incumbent layout under the default order for no pile-up. Not claimed: any guarantee under a non-default priority.
- **Plumbing.** `handoff_events(old, new, statuses, priority)` and `primary_role` live in `roles_v2.py` (pure, unit-tested); `sim_v2.py` is 297 lines. `cubesat/scenario.py` no longer imports `roles_v2` (it hard-codes `ROLE_PRIORITY`, pinned equal to `roles_v2.DEFAULT_PRIORITY`): `import cubesat.scenario` takes 102-131 ms here and does not import `scipy.optimize` (test `test_importing_scenario_does_not_import_scipy_optimize`). The exactly-one-leader/downlink invariant is checked by tests only (`tests/v2/test_roles_engine.py::test_one_leader_and_one_downlink_whenever_a_capable_sat_exists`): an engine-side check costs a pass over every tick and the assignment already guarantees it.

**Re-measured (command: `uv run python -m pytest tests/v2/test_roles_demo.py -s -m slow`, two_failure.json as engine v2, a_max 0.01, sat i DEAD at 1200 s and sat j at 1500 s, last tick t = 17028 s). Coverage is a pure function of the surviving positions and roles (nobody moves, nothing is replanned): it is NOT a recovery result and NOT the pre-registered PR-1 comparison.**

| pair | leader | downlink | imagers before / after | coverage before | coverage after |
|---|---|---|---|---|---|
| (0,1) | 2 | 5 | 3 / 3 | 0.3319 | 0.3319 |
| (0,2) | 1 | 5 | 3 / 3 | 0.3528 | 0.3528 |
| (0,3) | 1 | 5 | 3 / 3 | 0.3392 | 0.3392 |
| (0,4) | 1 | 5 | 3 / 3 | 0.2893 | 0.2893 |
| (0,5) | 1 | 2 | 4 / 3 | 0.3840 | 0.3528 |
| (1,2) | 0 | 5 | 2 / 3 | 0.2373 | 0.3278 |
| (1,3) | 0 | 5 | 2 / 3 | 0.2851 | 0.3736 |
| (1,4) | 0 | 5 | 2 / 3 | 0.2373 | 0.3278 |
| (1,5) | 0 | 2 | 3 / 3 | 0.3319 | 0.3278 |
| (2,3) | 0 | 5 | 2 / 3 | 0.2851 | 0.3528 |
| (2,4) | 0 | 5 | 2 / 3 | 0.2581 | 0.3278 |
| (2,5) | 0 | 1 | 3 / 3 | 0.3528 | 0.3278 |
| (3,4) | 0 | 5 | 2 / 3 | 0.1967 | 0.2893 |
| (3,5) | 0 | 1 | 3 / 3 | 0.3392 | 0.3736 |
| (4,5) | 0 | 1 | 3 / 3 | 0.2893 | 0.3278 |

Leader and downlink each held by one capable sat in **15/15** pairs (a consistency check of a pure assignment). Mean last-tick coverage over the 15 pairs **0.3348** after vs **0.3007** before (the reviewer's all-alive-sats-image variant reads 0.3940: here the downlink holder does not image, so the number is lower, and it can be lower than before for a pair that loses an imager to the downlink, e.g. (0,5)). 4 of 6 dead (15 subsets, failures at 1200/1300/1400/1500 s, last tick t = 2000 s): leader + downlink + imager held **15/15**, imagers min 1 mean 1.00, coverage min 0.1374 mean 0.1395; 5 of 6 dead (6 subsets): **6/6**, imagers 1, coverage min 0.1374 mean 0.1398 (the lone survivor holds all three roles).

**Mutation check (a COPY of the tree under /tmp/rolesmut_*, the 5 roles test files, first failing test shown; 20 mutants, 19 killed, 1 equivalent):**

| Mutant | Killed by |
|---|---|
| M1 drop the capability gate | `test_four_of_six_dead_keeps_imager` |
| M2 incapable cost 0.5 | `test_four_of_six_dead_keeps_imager` |
| M3 ignore incumbents | `test_v1_roles_map_onto_same_initial_holders` |
| M4 reverse priority | `test_four_of_six_dead_keeps_imager` |
| M5 silent sat holds leader | `test_radio_silent_holds_nothing_that_needs_radio_but_is_still_a_spare` |
| M6 two downlink seats | `test_v1_roles_map_onto_same_initial_holders` |
| M7 handoff for non-critical roles | `test_no_handoff_without_a_critical_change` |
| M8 roles not restored from the snapshot | `test_snapshot_carries_role_state` |
| M9 dead sat keeps its label | `test_four_of_six_dead_keeps_imager` |
| M21 drop `r not in held[i]` (pile-up guard) | `test_two_capable_survivors_pinned_for_every_priority_order[perm3]` |
| M23 coverage counts only `roles[0] == "imager"` | `test_a_lone_survivor_images_and_counts_toward_coverage_with_every_role_stacked` |
| M25 restore skips the roles-length check | `test_restore_refuses_a_state_list_of_the_wrong_length[roles]` |
| M40 handoff reason `DEAD` instead of `VACANT` | `test_handoff_events_vacant_both_ways` |
| M41 roles follow truth, not belief | `test_handoff_when_the_leader_dies_and_not_for_imager_changes` |
| M42 downlink holder may image | `test_four_of_six_dead_keeps_imager` |
| M43 stacking penalty removed | `test_four_dead_with_the_critical_holders_among_the_dead` |
| M44 display role = `roles[0]` | `test_dead_sat_shows_no_role_but_keeps_original_role` |
| M45 wire ignores `roles` | `test_track_roles_sees_a_stacked_downlink_gained_by_the_leader_sat` |
| M46 benchmark ignores `roles` | `test_stacked_leader_on_an_imager_counts_as_both` |
| M47 seats not capped by `min(want, eligible)` | SURVIVED: equivalent (ineligible rows cost 1e6 and are dropped, so the cap changes nothing); the `min` stays as documentation of the rule |

**Honest limits.** M40's `VACANT` reason cannot occur in the engine (a role is only ever vacated by a death, never refilled from vacancy, and roles the scenario does not label are not assigned); it is tested on `handoff_events` directly. The believed-state rule models the heartbeat declaration only, not a detector (Phase 4).
