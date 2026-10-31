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

## Phase 2 (fuel-first): spacecraft resources (`cubesat/spacecraft.py`, 2026-10-31)
Scope: propulsion, mass and failure modes as resource damage. Power, eclipse and safe/off modes (plan Task 2.2) are NOT built: `SatState` has no battery fields. Everything is engine `"v2"` only; v1 logs, canonical pins and v1 wire fixtures are untouched.

**Formulas** (g0 = 9.80665 m/s^2):
- thrust cap `|F| <= k F_max`, acceleration `a = F / m` with m the mass at the start of the step; a command under the cap passes through bit-unchanged, above it the vector is scaled (direction kept);
- mass flow `mdot = |F| / (Isp g0)`, propellant used per step `dm = |a| m dt / (Isp g0)`;
- tank delta-v `Isp g0 ln(m / (m - m_prop))` (log key `fuel_mps_left`);
- empty tank: zero thrust. A burn that would overdraw the tank is truncated on that step: the acceleration is scaled by `m_prop / dm`, so the step delivers exactly the impulse the remaining propellant buys, and `m_prop` is set to exactly 0 (never negative).

**Defaults (all ILLUSTRATIVE, not measured hardware):** a 3U cold-gas CubeSat; `truth.mass_kg` 4.0 kg is the WET mass (propellant included, dry = wet - m_prop), `spacecraft.m_prop_kg` 0.2, `isp_s` 40, `f_max_n` 0.04 (so 0.04 N / 4 kg = 0.01 m/s^2, the default `a_max`). Tank delta-v 20.12 m/s. Validation: `spacecraft.m_prop_kg < truth.mass_kg` for engine v2 scenarios.

**Failure modes as resource damage** (`apply_failure(sat, mode, stuck_vec)`; the four new modes are rejected for engine `"v1"` scenarios with `failure mode X (sat N) requires engine "v2"`, so v1 JSON stays valid and unchanged):

| Mode | Resource damage | Status | Event |
|---|---|---|---|
| DEAD, EPS_DEGRADE (fade ends in death, as Phase 1) | k=0, payload and radio off | DEAD | heartbeat rule after K misses |
| THRUSTER_OUT | k=0 | THRUSTER_OUT | FAILURE_DETECTED self_report |
| PARTIAL_THRUST | k=0.5 | DEGRADED | none (silent) |
| THRUSTER_STUCK_OPEN | constant `stuck_k F_max` (stuck_k = 1.0, valve fully open, illustrative) along a unit ECI vector fixed at failure time (the sat's ECI velocity direction then; no random draw), PD ignored, until the propellant is empty | DEGRADED | none (silent) |
| PAYLOAD_FAIL | payload_ok = False: flies and seat-holds, excluded from coverage | PAYLOAD_FAILED | FAILURE_DETECTED self_report |
| RADIO_FAIL | radio_ok = False: flies and seat-holds, silent heartbeat | RADIO_SILENT | FAILURE_DETECTED after K misses (heartbeat rule) |
| (any sat, tank empty) | m_prop = 0 | FUEL_DEPLETED | `FUEL_DEPLETED` {sat_id, t}, once |

Status precedence: a new failure only raises the label (NOMINAL < DEGRADED < PAYLOAD_FAILED < THRUSTER_OUT < FUEL_DEPLETED < RADIO_SILENT < DEAD < REENTERED). A silent sat (radio failed) cannot self-report, so a later THRUSTER_OUT or empty tank on it is only visible through the flags. FUEL_DEPLETED is self-reported and plain: it does not move the mission state to FAILURE_DETECTED (a depleted sat still flies and images; a recovery policy decides in a later phase). A FUEL_DEPLETED sat coasts: no PD command, `dv_used` frozen, camera counts for coverage.

**Engine wiring and log keys** (additive, v2 only; v1 sat rows keep exactly `id, role, status, r, v, dv_used`): per sat `fuel_kg`, `fuel_mps_left`, `k`, `payload_ok`, `radio_ok`; `dv_used` keeps its meaning (sum of the applied |a| dt). Coverage counts only imagers whose payload works and that are not DEAD/REENTERED.

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

**Measured fuel demonstration** (`data/scenarios/two_failure.json` with `engine "v2"`, `a_max_mps2` 0.01, spacecraft 0.2 kg / Isp 40 s / F_max 0.04 N, duration 17028 s = 3 orbits; sats 1 and 2 die at 1200 and 1500 s; the controller is the v1 PD seat-holder with no recovery, so this measures seat-holding against drag and J2, not a planner):

| sat | role | final status | dv_used m/s | propellant used kg | tank left m/s | ran dry |
|---|---|---|---|---|---|---|
| 0 | leader | NOMINAL | 1.6608 | 0.016900 | 18.4598 | no |
| 1 | imager | DEAD (t=1200) | 0.0653 | 0.000665 | 20.0554 | no |
| 2 | imager | DEAD (t=1500) | 0.1192 | 0.001215 | 20.0014 | no |
| 3 | imager | NOMINAL | 1.6733 | 0.017026 | 18.4473 | no |
| 4 | imager | NOMINAL | 1.6730 | 0.017023 | 18.4476 | no |
| 5 | downlink | NOMINAL | 1.6765 | 0.017059 | 18.4441 | no |

No sat runs dry in 3 orbits: the survivors use about 8.5% of the 0.2 kg tank (1.66-1.68 of 20.12 m/s). Not claimed: any lifetime extrapolation, any recovery cost (a re-formation transfer is Phase 5).

**Honest limits (Phase 2 fuel-first):** no power or eclipse model; no SEU, impact or aging; no propellant leak; the heartbeat rule is still the only detector, so PARTIAL_THRUST and THRUSTER_STUCK_OPEN are never declared (Phase 4); the recovery planner does not read `fuel_mps_left` yet (Phase 5); `wire.py` (inject message model `Literal`) still lists only the three v1 modes and `_STATUS_TO_WIRE` does not map the new statuses (a status string passes through unmapped); `wire.py`, `session.py` and `api.py` are outside this change.

**Mutation check (Phase 2).** Method as above on a scratch copy (`/tmp/kmut`, script kept out of the repo): one string replacement at a time, run the three Phase 2 test files with `-x`, first failing test recorded. 13 of 14 mutants killed; the survivor is an equivalent mutant.

| Mutant | First failing test |
|---|---|
| thrust cap comparison flipped | `test_spacecraft.py::test_accel_saturates_at_k_fmax_over_m` |
| mass flow dropped (`dm = 0`) | `test_spacecraft.py::test_command_below_cap_passes_through_unchanged` |
| negative propellant allowed (no truncation) | `test_spacecraft.py::test_propellant_never_negative_over_a_long_saturated_burn` |
| truncated burn not scaled | same |
| FUEL_DEPLETED skipped | `test_sim_v2_resources.py::test_fuel_never_negative_and_depleted_status_and_event_once` |
| k ignored in the cap | `test_spacecraft.py::test_accel_saturates_at_k_fmax_over_m` |
| PARTIAL_K = 1.0 | `test_failure_modes_v2.py::test_mode_PARTIAL_THRUST_semantics` |
| stuck-open treated as nominal | `test_failure_modes_v2.py::test_mode_THRUSTER_STUCK_OPEN_semantics` |
| coverage ignores payload_ok | `test_failure_modes_v2.py::test_payload_failed_sat_excluded_from_coverage_but_still_seat_holds` |
| radio failure not silent | `test_failure_modes_v2.py::test_radio_failed_sat_keeps_flying_and_is_declared_by_the_heartbeat_rule` |
| snapshot restore drops `fuel_out` | `test_sim_v2_resources.py::test_snapshot_restore_carries_fuel_state[35]` |
| v2-only mode validator off | `test_failure_modes_v2.py::test_v1_scenarios_with_v2_modes_are_rejected_with_a_plain_message[PAYLOAD_FAIL]` |
| `fuel_mps_left` wrong formula | `test_spacecraft.py::test_delta_v_budget_20p1` |
| survivor (equivalent): engine PD gate `sat.k > 0` removed | none: `thrust_limited` already returns zero for k = 0, so behaviour is identical |
