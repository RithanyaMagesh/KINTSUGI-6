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
| Density | exponential, `rho = rho0 exp(-(h-h0)/H)` on the row with the largest `h0 <= h`; 1000 km row above 1000 km; 150 km row below 150 km | table below |
| Thrust | commanded LVLH acceleration rotated to ECI, `a_I = C^T a_LVLH`, `C` from the chief at the start of the step, held over the step | |
| Integrator | classical RK4, fixed `dt = scenario.dt_s` (2 s) on `[r, v]`, batched over (chief + all sats) in one call | |
| Chief | virtual reference: circular orbit at ascending node, gravity + J2 only (no drag, no thrust) | |
| Chief initial | `r = a [cos O, sin O, 0]`, `v = vc [-sin O cos i, cos O cos i, sin i]`, `a = Re + altitude` | i, O from the scenario |
| ECI to LVLH | `rho = C (r_d - r_c)`, `rho_dot = C (v_d - v_c) - w x rho`, `w = (0, 0, abs(h)/abs(r_c)^2)` | |
| LVLH to ECI | exact inverse | |

Density table (Vallado, Fundamentals of Astrodynamics and Applications, Table 8-4; copied from the plan/master map section 10 Q7, all 14 rows asserted by `tests/v2/test_truth_accel.py::test_density_table_matches_vallado_rows`):

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

## EngineV2 (`cubesat/sim_v2.py`), Phase 1 behaviour
- Init: sat i starts on v1 slot i (`sim.build_slots`) mapped to ECI with `lvlh_to_eci`. `initial_lvlh` (N, 6) overrides the start states (validation hook).
- Tick `k` (`step()`): fire failures due at `t = k dt`, heartbeat/detection, consume the reserved random rows, log the LVLH state, then advance one RK4 step. Log schema = v1 tick schema plus optional `events` (all events of the tick; `event` = first) and INIT `engine: "v2"`.
- Seat holding: v1 `PDController.command` on the LVLH state against the slot reference, applied as a zero-order-hold acceleration. The reference is advanced with a cached `stm(dt)` (`hcw.stm`); the cached-Phi iteration differs from a direct `stm(t)` by 2.506e-08 m after one orbit (`uv run python -m pytest tests/v2/test_sim_v2_truth.py -k cached_phi -s`). `forcing_matrix(dt)` is not cached yet: nothing uses it before the Phase 5 planner.
- Failures (Phase 1 minimum): DEAD and EPS_DEGRADE (after its fade) coast in the truth model with the dead area; THRUSTER_OUT coasts with the active area and self-reports on the firing tick; EPS_DEGRADE with `degrade_s > 0` is DEGRADED (still holding) from `t - degrade_s`. Detection is the v1 heartbeat rule (`detection.missed_ticks_k`). No replanning, no recovery, no resources: mission state stays `FAILURE_DETECTED`.
- `inject(failure)`: applies at the current tick (a past time is clamped to now) and is recorded in `engine.injections`; `EngineV2(s, injections)` replayed from t=0 gives the same log. `snapshot()/restore()` pickle the full state including the Generator state (restore only blobs this engine wrote). `run(cancel_event)` raises `RunCancelled` between ticks.
- The chief has no drag, so dragged deputies drift relative to it (a dead sat decays about 3.5 times faster than an active one: area ratio 0.035/0.010).

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

## Validation numbers (each: value, then the command)
| Check | Measured | Threshold | Command |
|---|---|---|---|
| J2 vs central-difference gradient of U_J2, relative error | 2.680e-11 | < 1e-5 | `uv run python -m pytest tests/v2/test_truth_accel.py::test_j2_matches_potential_gradient -s` |
| King-Hele decay per rev at 500 km, active (A = 0.010 m^2) | -1.1415 m | -1.14 m, 5% | `uv run python -m pytest tests/v2/test_truth_accel.py::test_drag_decay_per_rev_king_hele -s` |
| King-Hele decay per rev at 500 km, dead (A = 0.035 m^2) | -3.9952 m | -3.99 m, 5% | same |
| RK4 numeric decay per rev, active / dead (polar orbit, energy-based a) | -1.1401 m / -3.9903 m | 5% | `uv run python -m pytest tests/v2/test_truth_integrate.py::test_drag_decay_numeric_per_rev -s` |
| LVLH round trip, worst absolute error | 4.502e-10 m | < 1e-6 m | `uv run python -m pytest tests/v2/test_truth_integrate.py::test_lvlh_roundtrip_under_1e6_m -s` |
| RK4 (dt = 2 s) vs scipy RK45 (rtol 1e-12), two-body + J2, 3 orbits, 500 km, position | 6.278e-04 m | < 1e-2 m | `uv run python -m pytest tests/v2/test_truth_integrate.py::test_rk4_dt2_vs_rk45_two_body_j2_3orbits_500km -s` |
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

The same file holds `g1_state`: v2 vs CW 3.1026 m, CW vs two-body RK45 (`cw_curve`) 3.1009 m. The 8 km drag-on case is lower than drag-off; it is the measured value, cause not investigated.

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
Spherical-altitude density; no attitude, SRP, third body or tides; constant drag area per status; PD seat holding with the v1 controller (v1 gains and the v1 a_max demand); thrust held in LVLH over each 2 s step and rotated with the chief frame at the step start; no resources, hazards, detector, recovery or certificate (later phases).
