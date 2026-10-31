# KINTSUGI-6 Physics Engine v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an engine-"v2" path (truth dynamics, spacecraft resources, seeded hazards, model-based detection, certified LP/MPC recovery, mission metrics, failure packs, pre-registered benchmark) without changing one byte of any v1 log.

**Architecture:** `Scenario.engine: Literal["v1","v2"]="v1"` gates everything. v1 code paths (`sim.py:149-667`, `allocate.py`, `pd.py`) are untouched except where Task 0 (phase0-fixes) already changed them. v2 adds new modules (`truth.py`, `spacecraft.py`, `hazards.py`, `detect.py`, `allocate_v2.py`, `certify.py`, `metrics_v2.py`) and ONE seam in `run_scenario`: `if scenario.engine == "v2": return run_scenario_v2(...)` (new `cubesat/sim_v2.py`, so sim.py stays frozen). Planning model = `hcw.py` STM; flight model = `truth.py`.

**Tech Stack:** Python 3.12, numpy, scipy (`linprog(method="highs")`, `linear_sum_assignment`), pydantic v2, pytest, ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-31-physics-v2-brief.md` (formulas in its section 4 are copied verbatim below; on conflict the brief wins except for the user overrides in "Overrides").

## Overrides (decided by the user, win over the brief)
- **Master spec is `docs/superpowers/specs/KINTSUGI-6_v2_master_map.md`** (saved 2026-10-31). It supersedes this plan's phase ORDER; the top-level order and the non-physics tracks live in `docs/superpowers/plans/2026-10-31-v2-plan.md`. This file remains the physics track (brief §4 formulas unchanged).
- Phase 0 is DONE (orchestrator, branch `v2`, commit `8f750ab`; see GATES.md "2026-10-31 — v2 Phase 0"). Task 0 below is historical.
- `EngineV2` is stepper-native from Task 1.5 (map §10): `step() / inject() / snapshot() / restore() / run()`. `sim.py` (v1) stays frozen behind the 3-line seam.
- Answers to the earlier open questions are in "Open questions / discrepancies (RESOLVED)" at the end.
- Branch is `v2` (not `physics-v2`); commit prefix `v2: <track><phase> — <summary>`.

## Global Constraints
- NO NUMBER without a committed artifact AND the command that produced it; unmeasured = "unmeasured"; never pre-state a result.
- Determinism: same scenario + seed => identical log, same machine. No wall clock in the sim. Randomness ONLY via one `numpy.random.Generator(PCG64(SeedSequence(scenario.seed)))` owned by the sim, drawn in the fixed order of the Draw-order table.
- `engine: Literal["v1","v2"] = "v1"`; with "v1" every existing log, test and golden hash stays identical. All new physics behind "v2".
- SI units internally; LVLH x radial, y along-track, z cross-track.
- Do NOT modify: `files/**`, `models/**`, `predictor/runtime.py`, frontend landing files.
- No new dependencies; numpy + scipy only.
- Tests first for every change; `uv run ruff check .` and `uv run python -m pytest -q -m "not slow"` green at every phase end.
- Never push, never merge to master. Commit message `physics-v2: phase N — <summary>`. After a phase commit: STOP and report (diff stat, test tail, validator report, reviewer report, every number with its command).
- Never say "first/novel/state-of-the-art"; say "we couldn't find an open tool that does X". All hazard rates/areas/defaults are ILLUSTRATIVE and labelled so in scenario field descriptions.
- Files under ~300 lines (AGENTS.md style); new modules are new files, not additions to `sim.py` (667 lines).

## Review Focus
Uncovered input classes most likely to bite, each pinned by a test in the owning task:
1. 4-of-6 dead / all-but-one dead (F6): two survivors must not both become leader+downlink with zero imagers; one survivor must not crash `linear_sum_assignment` or the LP. Test: Task 5.1 `test_four_of_six_dead_keeps_imager`, `test_single_survivor_no_crash`.
2. Zero fuel at replan time (all `m_p = 0`): LP infeasible must degrade to hold + flag, never raise or execute. Test: Task 5.4 `test_zero_fuel_holds_and_flags`.
3. 100% packet loss (`p_loss = 1.0`): every sat is silent; the detector must not declare all DEAD and replan with zero survivors. Test: Task 4.3 `test_total_packet_loss_declares_nothing_dead`.
4. Extreme altitudes (schema allows 160 < h < 2000 km): density row choice below 450 km and above 600 km must be defined and finite; eclipse formula valid. Test: Task 1.3 `test_drag_density_defined_at_schema_extremes`.
5. Cancel mid-run: `RunCancelled` raised between ticks including inside a long v2 MPC/LP solve, no partial output. Test: Task 5.3 `test_cancel_event_stops_v2_run`.
Also exercised at every gate by the adversarial reviewer (not Review Focus): simultaneous failures at one `t`, THRUSTER_OUT on the leader.

## Dependencies (phases are reorderable subject to these)
```
Task 0 (phase0-fixes) -> everything
1 truth  -> 2 spacecraft -> 3 hazards -> 4 detector        (4 also needs hcw.py, 2's flags)
5a capability roles   : needs 2 only (flags, k, battery)
5b psi sweep          : needs scenario only (can run before 1)
5c LP + MPC           : needs 2 (k, a_max, fuel) and hcw.py; MPC execution needs 1
5d certify/recovered/monitor : needs 1, 2, 5a-5c
6 metrics             : needs 1 (ECI for ground station), 2 (modes/Δv); delivered coverage needs 5a downlink capability
7 packs               : needs 2, 3, 5 (4 for radiation_glitch_storm)
8 wire/frontend       : needs events from 2, 4, 5
9 benchmark           : needs 7, 5, 6; claims committed first (Task 9.1)
```

## Open interface points for the master map
- Streaming/live sim: v2 loop is a per-tick generator candidate; `sim_v2.run_scenario_v2` yields lines then returns list (Task 1.5). Cancel hook already per tick (Task 5.3). `session.py:134` calls `run_scenario(augmented, cancel_event)`; a streaming track should swap that call, not the phases.
- Inject (`session.py` live failure injection / `Failure` list): new `FailureMode`s (Task 2.3) must be accepted by the live inject endpoint (`api.py`, `session.py:_parse_sat_id` neighbourhood) and `live_import.py`.
- Live/Incidents pages: consume new events CERTIFICATE, SUSPECT, THRUST_ANOMALY, FUEL_DEPLETED, SAFE_MODE (Task 8.1 `wire.py`), per-sat optional fields `fuel_kg, soc, k, mode` (Task 2.4 log schema).
- Visual recovery: per-seat targets + plan history live in ASSIGNMENT payload (additive keys `psi_deg`, `plan_dv_mps`, Task 5.2/5.3).
- Removals: none of the phases removes v1 code; "remove" = not default in v2 (a_max 0.1, PD transfers, heartbeat-only detection).

## Branch setup and file map
Branch is `v2`, created from origin/phase0-fixes; Phase 0 is committed on it (8f750ab).
New: `cubesat/{truth,spacecraft,hazards,detect,allocate_v2,certify,metrics_v2,sim_v2}.py`, `tests/v2/test_*.py`, `data/scenarios/packs/**`, `docs/PHYSICS_V2.md`, `docs/PITCH_NUMBERS.md`, `data/eval/*` artifacts.
Modified (additive): `cubesat/scenario.py` (new fields/blocks), `cubesat/sim.py` (3-line seam), `cubesat/wire.py:77-83,143-160,207-270`, `cubesat/benchmark.py` (`--mode packs`), `frontend` status/event/console files, `GATES.md`.

## Backward compatibility: scenario fields (all default to v1 behaviour; JSON without them validates)
| Field (Task) | Default | Units / meaning |
|---|---|---|
| `engine` (1.1) | `"v1"` | `Literal["v1","v2"]` |
| `chief.inclination_deg` (1.1) | 97.4 | deg, SSO-like (illustrative) |
| `chief.raan_deg` (1.1) | 0.0 | deg |
| `truth` block: `cd` 2.2, `area_active_m2` 0.010, `area_dead_m2` 0.035, `mass_kg` 4.0 (1.3) | as shown | illustrative |
| `spacecraft` block: `m_prop_kg` 0.2, `isp_s` 40, `f_max_n` 0.04, `battery_wh` 20, `eta` 0.28, `panel_m2` 0.06, `sun_vector` (fixed ECI unit, default from a fixed date), loads W bus 1.5/imager 2.0/radio 4.0/thruster 1.0, `omega_max_dps` 3 (2.1-2.2) | as shown | illustrative |
| `hazards` block: `seu_rate_per_sat_day` 0, `impact_flux_per_m2_day` 0, `battery_tau_age_s` None (3.1-3.2) | off | ILLUSTRATIVE rates |
| `detection.p_loss` 0.0, `detection.sigma_pos_m` 0, `detection.sigma_vel_mps` 0, `detection.t_grace_s` (4.3) | off | seeded |
| `role_priority` (5.1) | `["downlink","imager","leader"]` | v2 only |
| `formation.cross_track_phase_deg` (5.2) | 0.0 (v1), packs set 30 | deg |
| `ground_station` {lat_deg 13.03, lon_deg 77.51}, `delivery_latency_s` 10800 (6.2) | as shown | illustrative |
| `FailureMode` += PAYLOAD_FAIL, PARTIAL_THRUST, THRUSTER_STUCK_OPEN, RADIO_FAIL (2.3) | — | v2-only semantics |
v2 scenarios (packs) set `a_max_mps2` 0.01 and `engine: "v2"`; v1 defaults unchanged.

## Randomness: one Generator, one draw-order table
`sim_v2.make_rng(scenario) -> np.random.Generator` = `Generator(PCG64(SeedSequence(scenario.seed)))`, created once at tick 0, passed by reference to hazards and detector. v1 never touches it (seed stays written-but-unused in v1, so v1 bytes are unchanged). Draws happen ONLY in this order per tick `k`, sats in ascending id, and a draw is made whether or not its event fires (so enabling one hazard never shifts another's stream). New draws are APPENDED to the end of the table, never inserted; the table lives in `docs/PHYSICS_V2.md` and is asserted by `tests/v2/test_draw_order.py` (Task 1.2).

| # | Draw | Phase | Per tick, per sat | Notes |
|---|---|---|---|---|
| 1 | heartbeat loss `rng.random()` < `p_loss` | 4 | 1 float | always drawn when engine v2 |
| 2 | measurement noise `rng.standard_normal(6)` | 4 | 6 floats | scaled by sigma (0 => value 0, still drawn) |
| 3 | SEU `rng.random()` < λ_seu·dt/86400 | 3 | 1 float | on hit: duration `rng.uniform(30,120)` appended as #4 |
| 4 | SEU duration `rng.uniform(30,120)` | 3 | 1 float only on SEU hit | extension rule: conditional draws come after the unconditional ones of the same tick |
| 5 | impact `rng.random()` < λ_imp·dt | 3 | 1 float | on hit: component `rng.random()` (#6), f `rng.uniform(0.2,0.6)` (#7) |
| 6-7 | impact component / panel fraction | 3 | only on impact hit | |
Row positions are fixed here so phases can land in any order: a phase not yet implemented still draws its rows and discards them (Task 1.2 `test_reserved_rows_consumed_as_noops`). Phase 4 owns rows 1-2, Phase 3 owns rows 3-7.

---

## Task 0: Phase 0 — DONE (commit 8f750ab on branch `v2`, base origin/phase0-fixes f702c05)

Delivered (details and numbers in GATES.md): one-line like-for-like fix kept (`allocate.py:269`), phase0-fixes' extra `sim.py` change reverted (identical outcomes; `dv_bound.py` fixed instead), `cubesat/canon.py canonical_log_hash` (sig=5 + 1e-6 floor, measured) replacing the per-OS pins in four test files, critical-role metrics + `critical_vacancy_s` in `benchmark.py`, regenerated 15-pair report (hungarian 15/15, do_nothing 6/15), CI (full suite ubuntu, fast windows, frontend job), flaky test verified 0/30. NOT done by design: F3 duplicate-role fix (v2 engine only, map Q5). Cross-platform equality of the canonical pins is unverified until CI runs.

**Consumed by later tasks:** `from cubesat.canon import canonical_log_hash` (v2 goldens use it; never a per-OS map).

---

## PHASE 1 — Truth dynamics (needs: Task 0)

### Task 1.1: engine flag + orbit fields + v2 seam
**Files:** Modify `cubesat/scenario.py:20-30 (Chief), 168-211 (Scenario)`; modify `cubesat/sim.py:149-158` (3-line seam at top of `run_scenario`); Create `cubesat/sim_v2.py`, `tests/v2/test_schema_v2.py`.
**Interfaces:** Produces `Scenario.engine`, `ChiefOrbit.inclination_deg: float = 97.4`, `ChiefOrbit.raan_deg: float = 0.0`; `sim_v2.run_scenario_v2(scenario, cancel_event=None) -> list[dict]` (stub raising `NotImplementedError` until 1.5).
- [ ] **Step 1: Failing tests** — `test_v1_json_validates_without_new_fields` (every `data/scenarios/*.json` validates, `engine == "v1"`); `test_v1_nominal_bytes_unchanged` (run nominal seed 42, hash equals the canonical-hash golden); `test_engine_rejects_other_values`.
- [ ] **Step 2:** `uv run python -m pytest tests/v2/test_schema_v2.py -v` → FAIL: `engine` attribute missing.
- [ ] **Step 3:** add fields (descriptions with units); seam: `if scenario.engine == "v2": from cubesat.sim_v2 import run_scenario_v2; return run_scenario_v2(scenario, cancel_event)` (local import avoids cycles).
- [ ] **Step 4:** same command → PASS; also full fast suite.
- [ ] **Step 5:** `git add -A && git commit -m "physics-v2: phase 1 — engine flag and chief orbit fields"`

### Task 1.2: seeded Generator + draw-order table
**Files:** Modify `cubesat/sim_v2.py`; Create `tests/v2/test_draw_order.py`.
**Interfaces:** Produces `make_rng(scenario: Scenario) -> np.random.Generator`; module constant `DRAW_ORDER: tuple[str, ...]` (names of rows 1-7 above, asserted to match the table in `docs/PHYSICS_V2.md` once that exists — until then, in-test copy).
- [ ] **Step 1: Failing tests** — `test_same_seed_same_stream` (two `make_rng` with seed 7 give equal first 5 draws); `test_different_seed_differs`; `test_reserved_rows_consumed_as_noops` (calling `consume_reserved(rng, k_sats)` advances the stream by exactly the fixed count; documents that a later phase replaces it).
- [ ] **Step 2:** run → FAIL: `make_rng` not defined.
- [ ] **Step 3:** implement `make_rng` (one line) and `DRAW_ORDER`; `draw_tick(rng, n_sats) -> dict` returns the unconditional rows 1-3,5 for every sat in ascending id (reserved values for unimplemented phases are drawn and ignored).
- [ ] **Step 4:** PASS. **Step 5:** commit `physics-v2: phase 1 — seeded generator and draw order`.

### Task 1.3: accelerations (gravity, J2, drag, thrust rotation)
**Files:** Create `cubesat/truth.py`, `tests/v2/test_truth_accel.py`; Modify `cubesat/scenario.py` (`truth` block: `cd`, `area_active_m2`, `area_dead_m2`, `mass_kg`).
**Interfaces:** Produces
`accel_gravity(r: np.ndarray) -> np.ndarray`, `accel_j2(r) -> np.ndarray`, `density(h_m: float) -> float`, `accel_drag(r, v, B: float) -> np.ndarray`, `lvlh_dcm(r_c, v_c) -> np.ndarray` (3x3, rows x̂,ŷ,ẑ), `thrust_eci(a_lvlh, r_c, v_c) -> np.ndarray`. Constants MU=3.986004418e14, J2=1.08262668e-3, RE=6378.137e3, OMEGA_E=7.2921159e-5. Density: the FULL Vallado exponential table (map §10 Q7; Fundamentals of Astrodynamics and Applications, Table 8-4), rows (h0 km, ρ0 kg/m³, H km): (150, 2.070e-9, 22.523), (180, 5.464e-10, 29.740), (200, 2.789e-10, 37.105), (250, 7.248e-11, 45.546), (300, 2.418e-11, 53.628), (350, 9.518e-12, 53.298), (400, 3.725e-12, 58.515), (450, 1.585e-12, 60.828), (500, 6.967e-13, 63.822), (600, 1.454e-13, 71.835), (700, 3.614e-14, 88.667), (800, 1.170e-14, 124.64), (900, 5.245e-15, 181.05), (1000, 3.019e-15, 268.00); choose the row with the largest h0 ≤ h; above 1000 km use the 1000 km row (NOT clamped below: schema minimum is 160 km, first row 150 km). `truth.density_factor` (scenario field, default 1.0, optionally time-scheduled) multiplies ρ for the storm incident.
- [ ] **Step 1: Failing tests:**
```python
def test_j2_matches_potential_gradient():          # central diff of U_J2, rel err < 1e-5
def test_drag_decay_per_rev_king_hele():            # active B: ≈ -1.14 m/rev; dead (A=0.035): ≈ -3.99 m/rev at 500 km, tol 5%
def test_thrust_rotation_roundtrip():               # radial burn on circular orbit points along r_c/|r_c|
def test_drag_density_defined_at_schema_extremes(): # density(161e3), density(1999e3) finite, > 0, non-increasing in h
def test_density_table_matches_vallado_rows():       # all 14 rows equal the table above at h = h0
def test_density_factor_scales_drag_linearly():      # density_factor=3 -> a_drag x3
```
King-Hele decay per rev = −2π·B·ρ·a²; test measures it from an RK4 run in 1.4 order-independent form by formula only here (numeric version in 1.4).
- [ ] **Step 2:** `uv run python -m pytest tests/v2/test_truth_accel.py -v` → FAIL: module missing.
- [ ] **Step 3:** implement per the brief formulas verbatim: `a_J2 = −(3/2)·J2·μ·Re²/|r|⁵·[x(1−5z²/|r|²), y(1−5z²/|r|²), z(3−5z²/|r|²)]`; `a_D = −½ρ(h)B|v_rel|v_rel`, `v_rel = v − ω⊕×r`, `h = |r| − RE`, `B = Cd·A/m`; DCM rows `[x̂;ŷ;ẑ]`, `x̂=r/|r|`, `ẑ=(r×v)/|r×v|`, `ŷ=ẑ×x̂`.
- [ ] **Step 4:** PASS. **Step 5:** commit `physics-v2: phase 1 — truth accelerations`.

### Task 1.4: RK4, chief, LVLH transforms
**Files:** Modify `cubesat/truth.py`; Create `tests/v2/test_truth_integrate.py`.
**Interfaces:** Consumes 1.3. Produces `rk4_step(state6, dt, accel_fn) -> np.ndarray`; `chief_initial(altitude_m, inc_deg, raan_deg) -> np.ndarray` (circular ECI r,v); `eci_to_lvlh(r_d, v_d, r_c, v_c) -> np.ndarray` (6; ρ = C(r_d−r_c), ρ̇ = C(v_d−v_c) − ω×ρ, ω=(0,0,|h|/|r_c|²)); `lvlh_to_eci(rho6, r_c, v_c) -> tuple[np.ndarray, np.ndarray]`.
- [ ] **Step 1: Failing tests:** `test_lvlh_roundtrip_under_1e6_m`; `test_rk4_dt2_vs_rk45_two_body_j2_3orbits_500km` (scipy `solve_ivp` RK45 rtol=1e-12 reference, position error ≈ 1e-3 m, assert < 1e-2 m, print value); `test_drag_decay_numeric_per_rev` (RK4 1 rev, active ≈ −1.14 m, dead ≈ −3.99 m, tol 5%).
- [ ] **Step 2:** → FAIL: `rk4_step` undefined (mark RK45 test `@pytest.mark.slow` if > 5 s).
- [ ] **Step 3:** implement; RK4 loop (algorithm not fixed by tests):
```python
def rk4_step(s, dt, f):
    k1 = f(s); k2 = f(s + .5*dt*k1); k3 = f(s + .5*dt*k2); k4 = f(s + dt*k3)
    return s + dt/6*(k1 + 2*k2 + 2*k3 + k4)
```
where `f(s) = concat(v, accel_total(r, v))`.
- [ ] **Step 4:** PASS. **Step 5:** commit.

### Task 1.5: `EngineV2` stepper-native loop with truth (no resources yet) + CW-vs-truth report
**Files:** Modify `cubesat/sim_v2.py` (≤ 250 lines: init from v1 slot LVLH states via `lvlh_to_eci`, per-tick RK4 of chief and all deputies, log in the SAME schema as `sim.py:365-382`, optional per-sat keys only), reuse `sim.build_slots` (`sim.py:134-146`), `coverage.coverage_fraction`; Create `tests/v2/test_sim_v2_truth.py`; Create `data/eval/cw_vs_truth_report.json` via `uv run python -m cubesat.benchmark --mode cw-truth ...` (new small `_run_cw_truth` in `cubesat/benchmark.py:233-365 neighbourhood`).
**Interfaces:** Consumes 1.1-1.4. Produces `class EngineV2(scenario: Scenario, injections: list[Failure] = ())` with `step() -> dict` (one tick line), `inject(failure: Failure) -> None` (applies at the current tick, appended to `self.injections`), `snapshot() -> bytes` / `restore(blob: bytes) -> None` (full state incl. the Generator state), `run() -> Iterator[dict]`; `run_scenario_v2(scenario, cancel_event=None) = list(EngineV2(scenario).run())` raising `RunCancelled` between ticks. Determinism contract: `EngineV2(s, injections)` replayed from t=0 gives the identical log. v1 `PDController` is reused as seat holder until Phase 5. Cache `stm(dt)`/`forcing_matrix(dt)` once per engine and propagate all sats as one (N×6) product (map L1 speed-ups, v2 only).
- [ ] **Step 1: Failing tests:** `test_v2_no_drag_1km_matches_cw_within_3p1_m` (3 orbits, 1 km formation, drag off, J2 off: max position difference ≤ 3.101 m + 10% margin, brief figure 3.1 m); `test_v2_j2_on_difference_is_reported` (writes measured number; asserts finite); `test_v2_log_schema_same_keys` (v1 tick keys ⊆ v2 tick keys); `test_v2_byte_identical_twice`; `test_replay_with_injections_is_identical` (run to tick k, `inject`, finish; a fresh `EngineV2(s, [f])` yields the same log); `test_snapshot_restore_continues_identically`; `test_events_list_allows_multiple_per_tick` (map C6; `event` kept = first for v1-shaped consumers).
- [ ] **Step 2:** → FAIL: `NotImplementedError`.
- [ ] **Step 3:** implement. Truth initial deputies: `lvlh_to_eci(slot_state, r_c, v_c)`.
- [ ] **Step 4:** PASS; run the report command, commit artifact (GATES row added in the gate task).
- [ ] **Step 5:** commit `physics-v2: phase 1 — v2 truth loop`.

### Task 1.G: Phase 1 gate
- [ ] `uv run ruff check .`; `uv run python -m pytest -q -m "not slow"`; v1 golden/canonical-hash tests unchanged (diff of tests dir shows no edits to v1 golden constants); determinism: run a v2 scenario twice, `cmp` the logs.
- [ ] Dispatch IN PARALLEL: PHYSICS-VALIDATOR (scratch script outside repo re-derives J2 gradient, King-Hele, LVLH roundtrip, RK4-vs-RK45 using only scipy and the public `truth.rk4_step`/`accel_*`) and ADVERSARIAL-REVIEWER (diff + brief only).
- [ ] Fix defects, re-gate, add GATES.md row (numbers + commands), commit `physics-v2: phase 1 — truth dynamics`, STOP and report.

---

## PHASE 2 — Spacecraft resource model (needs: 1)

### Task 2.1: propulsion and mass
**Files:** Create `cubesat/spacecraft.py`, `tests/v2/test_spacecraft.py`; Modify `scenario.py` (`spacecraft` block).
**Interfaces:** Produces `@dataclass class SatState: m_kg, m_prop_kg, k (0..1), stuck_vec (np.ndarray|None), stuck_k, energy_wh, soh, payload_ok, radio_ok, mode: str` and `thrust_limited(sat, a_cmd_lvlh, dt) -> tuple[np.ndarray, float]` returning (applied a, Δm consumed). Constants g0=9.80665.
- [ ] **Step 1: Failing tests:** `test_accel_saturates_at_k_fmax_over_m` (F_max 0.04 N, 4 kg ⇒ 0.01 m/s²; k=0.5 ⇒ 0.005); `test_mass_flow_isp` (ṁ = −|F|/(Isp·g0)); `test_delta_v_budget_20p1` (Isp 40, 4→3.8 kg: 40·9.80665·ln(4/3.8) = 20.1 m/s ±0.05); `test_zero_prop_means_fuel_depleted_and_zero_thrust`.
- [ ] **Step 2:** → FAIL module missing. **Step 3:** implement (clip vector norm; consume propellant; at `m_prop<=0` set `k=0`, return flag). **Step 4:** PASS. **Step 5:** commit.

### Task 2.2: power, eclipse, safe/off modes
**Files:** Modify `cubesat/spacecraft.py`, `tests/v2/test_spacecraft.py`.
**Interfaces:** Produces `in_eclipse(r_eci, s_hat) -> bool` (r·ŝ<0 and |r−(r·ŝ)ŝ|<RE); `power_step(sat, r_eci, s_hat, loads: dict, dt) -> SatState-update` with `E' = clamp(E + (P_in−P_load)·dt, 0, C_bat·SoH)`, `P_in = η·1361·A_panel·0.6·(1−eclipse)` (0.6 = documented cos-average assumption); `update_mode(sat, requested) -> str` (SoC<0.20 ⇒ SAFE, <0.05 ⇒ OFF, OFF until SoC>0.15).
- [ ] **Step 1: Failing tests:** `test_eclipse_fraction_beta0_500km` (sample one orbit, fraction 0.378 ±0.003, 35.75 min); `test_soc_clamps`; `test_mode_hysteresis_off_until_15pct`; `test_safe_blocks_imaging_and_thrust_keeps_heartbeat`.
- [ ] **Step 2-5:** run → FAIL (`in_eclipse` undefined) → implement → PASS → commit `physics-v2: phase 2 — power model`.

### Task 2.3: failure modes as resource damage
**Files:** Modify `scenario.py:12-18 (FailureMode)`, `cubesat/spacecraft.py` (`apply_failure(sat, mode, rng_vec=None)`), `tests/v2/test_spacecraft.py`.
**Interfaces:** `FailureMode` += PAYLOAD_FAIL, PARTIAL_THRUST (k=0.5), THRUSTER_STUCK_OPEN (constant `stuck_k·F_max` along fixed ECI vector until propellant empty), RADIO_FAIL. `apply_failure(sat: SatState, mode: FailureMode, stuck_vec: np.ndarray|None = None) -> None`. DEAD ⇒ mode OFF, all flags false; THRUSTER_OUT ⇒ k=0; EPS_DEGRADE ⇒ `soh` ramps via `degrade_s` (brown-out follows from the energy clamp).
- [ ] **Step 1: Failing tests:** one per mode named `test_mode_<NAME>_semantics` + `test_stuck_open_stops_when_propellant_empty` + `test_eps_degrade_browns_out_naturally` (SoH ramp ⇒ SoC<5% ⇒ OFF without a scripted DEAD).
- [ ] **Step 2-5** as above; v1 enum values untouched (v1 JSON validates).

### Task 2.4: resources wired into the v2 loop + log fields
**Files:** Modify `cubesat/sim_v2.py`; Create `tests/v2/test_sim_v2_resources.py`.
**Interfaces:** per-sat optional log keys `fuel_kg, soc, k, mode` (additive; absent in v1). Statuses emitted: NOMINAL/DEGRADED/DEAD/THRUSTER_OUT plus new `FUEL_DEPLETED`, `SAFE`, `OFF`. Coverage counts only NADIR imagers with `payload_ok`.
- [ ] **Step 1: Failing tests:** `test_fuel_never_negative_and_depleted_status`; `test_imager_in_thrust_mode_not_counted_in_coverage`; `test_v2_with_resources_twice_byte_identical`; `test_v1_unchanged` (goldens).
- [ ] **Step 2-5** standard; commit `physics-v2: phase 2 — resources in loop`.

### Task 2.G: Phase 2 gate
Same checklist as 1.G. Validator re-derives Δv 20.1 m/s, eclipse 0.378, 0.01 m/s² from first principles. Commit `physics-v2: phase 2 — spacecraft resources`, STOP.

---

## PHASE 3 — Physics-caused failures (needs: 1, 2)

### Task 3.1: SEU resets and battery aging
**Files:** Create `cubesat/hazards.py`, `tests/v2/test_hazards.py`; Modify `scenario.py` (`hazards` block), `sim_v2.py`.
**Interfaces:** `seu_step(rng_vals: tuple[float,float], lam_per_day: float, dt: float, sat) -> float|None` (returns reboot-until time) — consumes draw rows 3/4; `aging_soh(t: float, t0: float, tau: float) -> float` = `1 − (t−t0)/τ_age` clamped [0,1].
- [ ] **Step 1: Failing tests:** `test_seu_rate_matches_poisson_over_many_seeds` (mean events over 200 seeds within 3σ of λ·T); `test_seu_off_30_to_120_then_reboot_state_preserved`; `test_same_seed_same_events`; `test_hazards_default_off_changes_no_bytes`; `test_aging_linear`.
- [ ] **Step 2-5** standard.

### Task 3.2: impacts
**Files:** Modify `cubesat/hazards.py`, `tests/v2/test_hazards.py`.
**Interfaces:** `impact_step(rng, lam_per_m2_day, areas: dict[str,float], dt) -> tuple[str, float]|None` (component, f) — rows 5-7. Component chosen with probability ∝ area (panels, tank, camera, radio, bus). Effects: panels `P_in×(1−f)`, f~U[0.2,0.6]; tank leak (propellant loss + small reaction accel along fixed body direction); camera ⇒ PAYLOAD_FAIL; radio ⇒ RADIO_FAIL; bus ⇒ DEAD.
- [ ] **Step 1: Failing tests:** `test_component_probability_proportional_to_area` (chi-square vs areas over 1e4 draws); `test_each_component_effect`; `test_draw_order_unchanged_when_impact_disabled`.
- [ ] **Step 2-5** standard.

### Task 3.G: Phase 3 gate (as 1.G; adversarial seeds: simultaneous SEU+impact same tick). Commit `physics-v2: phase 3 — hazard models`, STOP.

---

## PHASE 4 — Model-based failure detection (needs: 1, 2, 3 for glitch generation; hcw.py)

### Task 4.1: residual + chi-square
**Files:** Create `cubesat/detect.py`, `tests/v2/test_detect.py`.
**Interfaces:** `residual(rho_k: np.ndarray, rho_km1: np.ndarray, a_cmd_km1: np.ndarray, dt: float, n: float) -> np.ndarray` = `ρ_k − [Φ(dt)ρ_{k−1} + G(dt)a_cmd]` using `hcw.stm` (`hcw.py:28`) and `hcw.forcing_matrix` (`hcw.py:85`); `chi2_stat(r, sigma_inv) -> float`; `GAMMA = scipy.stats.chi2.ppf(1−1e-4, 6)` (≈ 27.86; scipy is installed).
- [ ] **Step 1: Failing tests:** `test_gamma_is_27p86` (abs 0.01); `test_residual_zero_for_pure_cw_motion`; `test_residual_detects_unmodelled_thrust`; `test_false_alarm_rate_at_pfa_1e-4_with_nominal_noise` (σ_pos 1 m, σ_vel 0.01 m/s, 1e5 samples, rate ≤ 3e-4).
- [ ] **Step 2-5** standard. Σ from nominal-run residual statistics: committed calibration artifact `data/eval/detector_calibration.json` made by `uv run python -m cubesat.benchmark --mode detector-cal`.

### Task 4.2: classifier + K false-alarm table
**Files:** Modify `cubesat/detect.py`; Create `data/eval/false_alarm_table.json` (command in test docstring).
**Interfaces:** `class Detector: step(tick_obs) -> list[Event]` with states DEAD / SUSPECT / THRUST_ANOMALY / self-reported (silence+ballistic ≥ K ticks ⇒ DEAD; silence+commanded-motion consistent ⇒ SUSPECT, wait `t_grace_s`; heartbeat ok + residual anomaly ⇒ THRUST_ANOMALY; telemetry flag ⇒ self-reported). `false_declarations_per_orbit(p: float, K: int, n_ticks: int = 2838) -> float` = `n_ticks·(1−p)·p**K`.
- [ ] **Step 1: Failing tests:** `test_false_alarm_law_table` — p=0.05,K=3 ⇒ 0.35 (brief F11 states 0.34, test uses formula with 2838·0.95·0.05³ = 0.337; assert within 0.01 of 0.337), K=5 ⇒ 0.0008 (±0.0001); `test_silence_ballistic_is_dead`; `test_silence_with_motion_is_suspect_then_cleared_on_reboot`; `test_stuck_open_is_thrust_anomaly`.
- [ ] **Step 2-5** standard; the table over p∈{0.01,0.05,0.1}, K∈{3,5,7} is written to the artifact.

### Task 4.3: detector in the v2 loop + metrics
**Files:** Modify `cubesat/sim_v2.py`, `benchmark.py` metrics (`detection_latency_s`, `false_declarations`, `missed_detections`), `scenario.py` (`detection.p_loss` etc.); `tests/v2/test_detect_loop.py`.
**Interfaces:** replaces heartbeat-only `missed >= K` (`sim.py:319-345`) in v2 only; v2 default `K=5` (map Q9; K applies to "silence + ballistic" only).
- [ ] **Step 1: Failing tests:** `test_total_packet_loss_declares_nothing_dead` (p_loss=1.0, 6 sats, 1 orbit: zero DEAD declarations and no replan with zero survivors; sats end SUSPECT); `test_glitch_storm_no_replan` (SEU resets on 2 sats + p_loss 0.05, 20 seeds: ≤ 1 replan total); `test_simultaneous_failures_both_detected`; `test_detection_latency_logged_per_mode`.
- [ ] **Step 2-5** standard.

### Task 4.G: Phase 4 gate; validator re-derives chi-square quantile and the false-alarm law. Commit `physics-v2: phase 4 — model-based detection`, STOP.

---

## PHASE 5 — Recovery v2 (needs: 1, 2; sub-phases below). All v2-only; `allocate.py` (v1, `replan` at `:234`) untouched.

### Task 5.1 [5a]: capability roles
**Files:** Create `cubesat/allocate_v2.py`, `tests/v2/test_allocate_v2.py`; Modify `scenario.py` (`role_priority`).
**Interfaces:** `capability(sat: SatState, role: str) -> bool` (imager: payload_ok ∧ SoC margin; downlink: radio_ok ∧ power; leader: radio_ok, stackable); `assign_roles(sats: list[SatState], priority: list[str]) -> list[list[str]]` (a sat may hold `["imager","leader"]`; Hungarian via `linear_sum_assignment` on capability-aware cost, incapable = `1e6`, never inf, ties with index epsilon 1e-9 as `AGENTS.md` invariant 6). Roles list per sat is the new v2 log field `roles`; the single `role` key stays = primary role for wire compatibility. Failed (non-NOMINAL) sats get `roles: []`, `role: "none"` and `original_role` for display (map Q5; v1 keeps its labels); assert exactly one leader and one downlink among NOMINAL sats after every ASSIGNMENT and ROLE_HANDOFF, v2 only.
- [ ] **Step 1: Failing tests:** `test_four_of_six_dead_keeps_imager` (F6: survivors become downlink+imager, leader stacked; coverage > 0); `test_single_survivor_no_crash`; `test_leader_stacks_on_imager`; `test_incapable_never_assigned`; `test_exactly_one_leader_and_downlink_among_nominal_after_every_assignment`.
- [ ] **Step 2-5** standard.

### Task 5.G-a: gate for 5a (own commit and STOP: `physics-v2: phase 5a — capability roles`)

### Task 5.2 [5b]: psi sweep
**Files:** Modify `cubesat/scenario.py` (`formation.cross_track_phase_deg: float = 0.0`), `cubesat/allocate_v2.py` (`candidate_slots(amp_m, phase0, psi_deg, n_slots, n) -> list[np.ndarray]`: `x=A cos θ, y=−2A sin θ, z=B cos(θ+ψ)`, B=A); Create `tests/v2/test_psi.py`, `data/eval/psi_trade_table.json`.
**Interfaces:** v1 default ψ=0 reproduces `hcw.slot_initial_state` (`hcw.py:119`) bytes; v2 packs default 30.
- [ ] **Step 1: Failing tests:** `test_psi0_equals_v1_slots`; `test_psi_table_matches_brief` — A=B=8 km, 6 slots, 4 imagers: (ψ, coverage, worst sep m) = (0, 0.371, 11.8), (30, 0.364, 2929), (45, 0.355, 4330), (60, 0.345, 5657), (90, 0.326, 8000), tolerance 0.002 on coverage and 1% on separation; `test_psi90_bound_d_min_ge_2sin_half_dphi_minA_B`.
- [ ] **Step 2-5** standard; artifact regenerated by `uv run python -m cubesat.benchmark --mode psi-table`.

### Task 5.G-b: gate (own commit and STOP: `physics-v2: phase 5b — psi sweep`)

### Task 5.3 [5c]: LP transfers + MPC
**Files:** Modify `cubesat/allocate_v2.py` (or new `cubesat/transfer.py` if allocate_v2 exceeds ~300 lines); `tests/v2/test_transfer.py`; `data/eval/lp_vs_pd_dv_table.json`.
**Interfaces:** `lp_transfer(x0: np.ndarray, x_target: np.ndarray, T: float, n: float, a_max: float, k: float, N: int, keepout: list[tuple[np.ndarray, np.ndarray, float]] | None = None) -> tuple[np.ndarray, float] | None` — returns (Δv array (N,3), total Δv) or None when infeasible. `best_transfer(..., T_orbits=(0.5,1,2)) -> Transfer | None` (feasible T with least Δv). `mpc_step(...)` re-solves every M=60 ticks from the truth-measured state; PD only for terminal hold.
Algorithm the tests do not fix:
```
vars: [dv+ (N,3), dv- (N,3)] >= 0; min sum(dv+ + dv-)
eq: sum_k Phi[:,3:](T-t_k) @ (dv+_k - dv-_k) = x_target - Phi(T) @ x0     (Phi = hcw.stm)
bounds: each component <= k*a_max*(T/N)/sqrt(3)
keep-out: n_j . (rho_i(t_j) - rho_o(t_j)) >= d_safe, rho_i linear in dv; <=3 sequential-convexification iterations, n_j from previous iterate
linprog(method="highs")
```
- [ ] **Step 1: Failing tests:** `test_lp_8km_leader_transfer_16p4_mps` (a_max 0.01, T=1 orbit, 500 km: total Δv 16.4 m/s, tol 0.5; reference prototype in brief F10); `test_lp_2km_formation_about_4_mps_at_0p002` (≈ 4 m/s, tol 0.5); `test_lp_beats_pd_on_same_transfer` (PD ≈ 155 m/s from `PDController`, assert LP < PD/5 and write table); `test_infeasible_returns_none_not_raise`; `test_zero_fuel_holds_and_flags` (`k=0` ⇒ None ⇒ hold + flag event); `test_cancel_event_stops_v2_run` (set event mid-MPC ⇒ `RunCancelled`, nothing returned).
- [ ] **Step 2-5** standard.

### Task 5.G-c: gate (own commit and STOP: `physics-v2: phase 5c — LP and MPC`)

### Task 5.4 [5d]: certificate
**Files:** Create `cubesat/certify.py`, `tests/v2/test_certify.py`.
**Interfaces:** `certify(plan: Plan, sats: list[SatState], truth_states: list[np.ndarray], scenario: Scenario, hold_coverage: float) -> dict` returning `{"passed": bool, "min_sep_m": float, "worst_fuel_margin_mps": float, "roles_ok": bool, "coverage": float}`; propagates H = 2 orbits with `truth.rk4_step`, including dead sats' drag (`area_dead_m2`); passes iff `min_sep ≥ 2000 m` ∧ each Δv ≤ remaining Δv·(1−0.20) ∧ every critical role on a capable sat ∧ `coverage ≥ hold_coverage`. Event `CERTIFICATE` with that payload. `choose_plan(candidates, ...) -> Plan | None`: first certified; None ⇒ hold + flag.
- [ ] **Step 1: Failing tests:** `test_certificate_fails_on_dead_sat_drift_crossing_slot`; `test_certificate_fails_on_fuel_margin`; `test_uncertified_plan_never_executed`; `test_certificate_event_payload_keys`.
- [ ] **Step 2-5** standard.

### Task 5.5 [5d]: RECOVERED v2 and safety monitor
**Files:** Modify `cubesat/sim_v2.py`, `cubesat/allocate_v2.py`; `tests/v2/test_recovered_monitor.py`.
**Interfaces:** `recovered(dr: list[float], dv: list[float], streak: int) -> tuple[bool, int]` (every NOMINAL sat ‖Δr‖ ≤ 50 m ∧ ‖Δv‖ ≤ 0.05 m/s for ≥ 30 consecutive ticks); `closest_approach_10min(states, n) -> float` (CW-propagated pairwise minimum, `hcw.propagate`); on < 1000 m trigger evasion (reuse `PDController.apply_accel`, `pd.py:79`, as `sim.py:606-636`) AND replan.
- [ ] **Step 1: Failing tests:** `test_not_recovered_with_1092m_offset_and_7p75mps` (F5 case); `test_recovered_needs_30_ticks`; `test_monitor_triggers_evasion_and_replan_below_1km`; `test_monitor_silent_above_1km`.
- [ ] **Step 2-5** standard.

### Task 5.G-d: Phase 5 final gate (as 1.G; additionally: no v2 plan executed without a CERTIFICATE event in the log; adversarial seeds: simultaneous failures, THRUSTER_OUT leader, zero fuel, cancel mid-run). Commit `physics-v2: phase 5d — certificate, recovered, monitor`, STOP.

**5a-5d commit policy:** each sub-phase gets its own commit AND its own STOP (user reviews). Rationale: 5b is independent and cheap to review; 5c carries the numerical risk (LP feasibility); 5d depends on all three. Only 5d is the "Phase 5 complete" report.

---

## PHASE 6 — Mission value metrics (needs: 1, 2, 5a)

### Task 6.1: coverage-hours and ancillary metrics
**Files:** Create `cubesat/metrics_v2.py`, `tests/v2/test_metrics_v2.py`.
**Interfaces:** `coverage_hours(ts: list[float], cov: list[float]) -> float` = `np.trapezoid(cov, ts)/3600`; `critical_uptime(log) -> float`; `min_separation(log) -> float`; `certificate_pass_rate(log) -> float`.
- [ ] **Step 1: Failing tests:** `test_coverage_hours_constant_half_over_1h_is_0p5`; `test_uptime_zero_when_leader_dead_all_run`.
- [ ] **Step 2-5** standard.

### Task 6.2: ground-station delivered coverage
**Files:** Modify `cubesat/metrics_v2.py`, `scenario.py` (`ground_station`, `delivery_latency_s`); `tests/v2/test_delivered.py`.
**Interfaces:** `gs_visible(r_sat_eci, t, lat_deg, lon_deg, min_el_deg=10.0) -> bool` using `el = asin(((r_sat−r_gs)·û_gs)/|r_sat−r_gs|)`, `r_gs` rotating at ω⊕; `delivered_coverage(log, scenario) -> float` (imaged area counts only if a capable downlink sat exists AND a pass occurs within L=10800 s).
- [ ] **Step 1: Failing tests:** `test_overhead_pass_elevation_90`; `test_below_10deg_not_visible`; `test_no_downlink_sat_zero_delivered`; `test_delivery_window_respected`.
- [ ] **Step 2-5** standard.

### Task 6.G: Phase 6 gate; validator recomputes elevation for 3 geometries independently. Commit `physics-v2: phase 6 — mission metrics`, STOP.

---

## PHASE 7 — Failure packs (needs: 2, 3, 5; 4 for glitch storm)

### Task 7.1: pack scenarios
**Files:** Create `data/scenarios/packs/<pack>/*.json` and `tests/v2/test_packs.py`. Packs: `two_dead` (all 15 DEAD pairs), `leader_battery_fade` (EPS_DEGRADE + `reassign_on_degrade`), `debris_strike` (DEAD + neighbour PARTIAL_THRUST), `stuck_thruster`, `radiation_glitch_storm` (SEU on 2 sats + `p_loss` 0.05), `aging_fleet` (battery aging + PAYLOAD_FAIL), `comms_blackout` (RADIO_FAIL on downlink). Each: `engine "v2"`, ψ 30, `a_max_mps2` 0.01, realistic fuel (0.2 kg / Isp 40).
- [ ] **Step 1: Failing tests:** `test_every_pack_file_validates_and_is_v2` ; `test_two_dead_has_15_files_one_per_pair`; `test_each_pack_has_description_in_name_or_readme`.
- [ ] **Step 2-5** standard (generate files with a tiny script run once; do not commit the script).

### Task 7.2: `--mode packs` benchmark
**Files:** Modify `cubesat/benchmark.py:388-511 (main)` (+ `_run_packs`); `tests/v2/test_packs_bench.py`; policies `do_nothing`, `hungarian_v1`, `recovery_v2` (extend `_scenario_for_policy`, `benchmark.py:62-71`), seeds N=20.
**Interfaces:** writes logs with sha256, `data/eval/packs_report.json`, `packs_manifest.json` (same manifest shape as `benchmark_manifest.json`). Does NOT run the pre-registered benchmark (that is 9.2); tests use N=2 on one pack.
- [ ] **Step 1: Failing tests:** `test_packs_mode_writes_report_and_manifest`; `test_packs_logs_have_sha256_in_manifest`; `test_packs_run_is_byte_identical_twice`.
- [ ] **Step 2-5** standard.

### Task 7.G: Phase 7 gate. Commit `physics-v2: phase 7 — failure packs`, STOP.

---

## PHASE 8 — Wire + frontend (needs: events from 2, 4, 5; minimal, no restyle)

### Task 8.1: wire.py
**Files:** Modify `cubesat/wire.py:77-83 (_STATUS_TO_WIRE)`, `:143-160 (_sat_to_wire)`, `:207-270 (event formatters)`; `tests/test_wire.py` additions + `tests/v2/test_wire_v2.py`.
**Interfaces:** new statuses (`FUEL_DEPLETED, SAFE, OFF`) map to `"failed"` or `"degraded"` per decision recorded in the test; events CERTIFICATE, SUSPECT, THRUST_ANOMALY, FUEL_DEPLETED, SAFE_MODE formatted via `_plain_event`/`to_event` shape; per-sat optional fields passed through only when present. v1 wire golden (`tests/fixtures/wire_golden*.json`) unchanged.
- [ ] **Step 1: Failing tests:** `test_new_statuses_mapped`; `test_certificate_event_formats_passed_min_sep_fuel_margin`; `test_v1_wire_golden_unchanged`; `test_sat_row_ok_accepts_v2_extra_keys`.
- [ ] **Step 2-5** standard.

### Task 8.2: frontend
**Files:** Modify existing status colour mapping, event feed formatter, console panel (find via `graphify-out/graph.json` before editing); colours ONLY in `tokens.css`; add vitest cases next to the files modified. No landing-page files.
**Interfaces:** certificate badge (passed + min sep + fuel margin); per-sat fuel/battery bars; leader/downlink readout.
- [ ] **Step 1:** failing vitest for badge text and bar width from fixture `sim_state` with extra fields. **Step 2:** `npm test` → FAIL missing component. **Step 3:** implement. **Step 4:** PASS + `npm run lint`/`tsc` (whatever the CI frontend step added by phase0 runs). **Step 5:** commit.

### Task 8.G: Phase 8 gate (+ frontend CI step). Commit `physics-v2: phase 8 — wire and frontend`, STOP.

---

## PHASE 9 — Pre-registered benchmark (needs: 5, 6, 7)

### Task 9.1: pre-register claims (own commit, BEFORE any benchmark run)
**Files:** Modify `GATES.md` (new "Pre-registration 2026-10-31 physics-v2" section, claims verbatim from brief):
C1 recovery_v2 holds both critical roles in ≥ 95% of pack runs where at least 2 capable sats survive.
C2 recovery_v2 per-sat Δv ≤ fuel budget in 100% of runs (by construction; verified).
C3 0 certified plans violate 2 km in truth-model replay.
C4 radiation_glitch_storm: false replans ≤ 1 per 20 runs.
C5 two_dead: recovery_v2 coverage ≥ do_nothing in ≥ 13/15 pairs OR critical roles held 15/15 (report both).
Plus the exact command (`uv run python -m cubesat.benchmark --mode packs ...` with N=20 seeds, policy set) and the sentence "thresholds cannot change after this commit".
- [ ] **Step 1:** write the section. **Step 2:** `git diff --stat` shows only GATES.md. **Step 3:** commit `physics-v2: phase 9 — pre-register claims C1-C5`. No benchmark run exists in the tree at this commit (`git log -- data/eval/packs_report.json` shows only Task 7.2's N=2 test output is not committed).

### Task 9.2: run (BENCHMARK-RUNNER)
- [ ] Run the exact pre-registered command; write `data/eval/packs_report.json`, manifest; compute C1-C5 pass/fail with a script that reads the thresholds from the GATES.md text (cannot edit them); write `docs/PHYSICS_V2.md` (all formulas, defaults with source or "illustrative", every validation number with command, draw-order table) and `docs/PITCH_NUMBERS.md` (only passed numbers + commands; use the exact F13 statements: Langer & Bouwmeester EPS+COM together ≈ 44% of losses at 30 days; Swartwout ~40% university mission failure rate).
- [ ] Gate (as 1.G) then PHYSICS-VALIDATOR + ADVERSARIAL-REVIEWER check every number against its command. Commit `physics-v2: phase 9 — benchmark results`, STOP and report pass/fail honestly.

---

## Agent roster and skills
| Role | Skills | Rules |
|---|---|---|
| IMPLEMENTER (one per phase, sequential) | ponytail:ponytail, superpowers:test-driven-development, superpowers:verification-before-completion | tests first, watch fail for the stated reason |
| PHYSICS-VALIDATOR (fresh context) | ponytail:ponytail, superpowers:verification-before-completion, superpowers:systematic-debugging | scratch script OUTSIDE the repo; imports only the public function under test |
| ADVERSARIAL-REVIEWER (fresh context) | ponytail:ponytail-review, superpowers:requesting-code-review | sees diff + brief only; fixes nothing; returns defect list |
| BENCHMARK-RUNNER (Phase 9) | superpowers:verification-before-completion, ponytail:ponytail | cannot change thresholds |
| ORCHESTRATOR | superpowers:dispatching-parallel-agents, superpowers:subagent-driven-development, superpowers:using-superpowers | one writer per area; validator and reviewer in parallel |

Prompt templates (fill `<N>`, `<tasks>`):
- IMPLEMENTER: "Implement tasks <tasks> of docs/superpowers/plans/2026-10-31-physics-v2-plan.md on branch physics-v2, tests first, exact signatures from the Interfaces blocks. Engine v1 must stay byte-identical. Run the phase gate; report command outputs; do not commit past the gate."
- PHYSICS-VALIDATOR: "Phase <N> of the brief (docs/superpowers/specs/2026-10-31-physics-v2-brief.md section 4). Without reading the implementer's reasoning, re-derive each formula and check it numerically in a scratch script under /tmp. Import only <public function>. Report pass/fail with numbers."
- ADVERSARIAL-REVIEWER: "Here is the diff for phase <N> and the brief. Break it: simultaneous failures, all-but-one dead, zero fuel, packet loss 100%, extreme altitudes, cancel mid-run; check determinism and every claimed number. Return a defect list; fix nothing."
- BENCHMARK-RUNNER: "Run exactly the command pre-registered in GATES.md. Do not alter any threshold or scenario. Write artifacts; report C1-C5 pass/fail as measured."
- ORCHESTRATOR: "Per phase: dispatch IMPLEMENTER; gates; dispatch VALIDATOR and REVIEWER in parallel; send defects back; re-gate; commit `physics-v2: phase N — <summary>`; STOP and show diff stat, test tail, both reports."

## Execution-order risk notes
- Phase 5 is the largest and the likeliest to slip: split 5a-5d, each its own commit AND STOP (reasons above). 5b can be done any time; 5a is the quickest win for F6.
- Nothing may import `allocate.replan` into v2 paths; v2 never touches `pd.PDController` except as terminal hold.
- Keep `sim.py` frozen: only the 3-line seam; every v2 behaviour lives in `sim_v2.py`.
- Draw-order drift is the silent killer of "same seed => same events": the Task 1.2 test must stay green through Phases 3-4.
- LP size: N burn nodes x 3 axes x 2 x sats; per-tick MPC every 60 ticks keeps runtime bounded; measure and report, do not assume.
- Hashes: after Task 0 the canonical hash is 9-significant-digit; v2 golden pins use the same helper, not new machine maps.

## Open questions / discrepancies
See the report returned with this plan (Q1-Q10); the same list is kept at the end of this file.

1. Q1 F1 numbers: master run today gives hungarian worse than do_nothing in 10/15 pairs (strict, 1e-12 tolerance) vs brief 9/15; mean 0.25943 vs 0.29106 matches (−3.16 pts vs brief −3.17). Probably one tie-ish pair; Task 0 should state the exact comparison tolerance.
2. Q2 F2 reproduced: hungarian critical roles held 15/15, do_nothing 6/15 on master.
3. Q3 Do-no-harm path on master: `allocate.replan` (`allocate.py:263-276`) returns `hold` with re-elected `seats`; `sim.py:487-492` then applies `plan.seat_roles[col]`. The fix is in `allocate.py`/`sim.py`, which Task 0 (Antigravity) owns; the brief's "score with SAME role layout" must be checked against whichever of the two files phase0-fixes edits.
4. Q4 Hash maps are in two places, not one: `tests/test_cli.py:13-18` (nominal, keyed `win32`/`linux`) and `tests/test_failure_modes.py:30-35` (two_failure, a SET of platform hashes); `tests/test_oracle_sweep_v3.py` re-asserts the 450d5371 pin. Task 0 must remove all three.
5. Q5 "none" role: `wire.py` passes `sat["role"]` through unchanged (`wire.py:147`) and `_SAT_REQUIRED_KEYS` requires it; role-clearing to "none" (F3) could surface an unknown role string in the frontend (`AllocationFan.tsx`, `TopStatusBar.tsx` mention "none"; role semantics not verified). Check what phase0-fixes chose (role "none" vs separate field).
6. Q6 Seed: `scenario.seed` is only written to the INIT header (`sim.py:218`); nothing reads it for randomness in `sim.py`. `monte_carlo.py:52` (`mc_rng`) uses its own generator for jitter — that is a different, harness-owned RNG and should not be merged with the sim-owned one.
7. Q7 Density table: brief says "pick the row with h0 ≤ h" but the schema allows 160 < altitude < 2000 km; h < 450 km has no row. Plan clamps to the 450 km row (tested only for finiteness/monotonicity). Needs user confirmation.
8. Q8 ASSIGNMENT assertion points: single emission site `sim.py:547-572`; role re-labelling happens at `:492` (hold) and `:519`, plus oracle/degrade swaps `_swap_critical_seat` (`:98-131`, `:268-279`, `:531-542`). Assert "exactly one leader and one downlink among NOMINAL sats" after `:519` and `:492`, not just at the event. A DEGRADED holder stays assignable=False, so the assertion must count NOMINAL only and the degrade-trigger swap must be included.
9. Q9 Brief never states the v2 default for `missed_ticks_k`; v1 default is 3 (`scenario.py` Detection). Plan assumes v2 packs use K=5 (F11: 0.0008 false/sat/orbit at 5% loss). Confirm.
10. Q10 CI (`.github/workflows/ci.yml`) runs plain `uv run pytest` (all tests incl. slow) on ubuntu AND windows, so Windows/Linux hash divergence (F12) breaks CI today; v2 slow tests (RK45 cross-check) will run in CI. Frontend CI step is added by phase0-fixes.
11. Q11 PHYSICS_ENGINE_EXPLAINED.md was written for c56f13b; line numbers cited in this plan are from eb6c9f1 and must be re-verified after Task 0 changes `sim.py`/`allocate.py`.
12. Q12 Brief F11 says 0.34 false declarations/sat/orbit at p=0.05,K=3; formula `2838·0.95·0.05³` = 0.337 (consistent). K=5 gives 0.0008 (consistent).


## Open questions / discrepancies (RESOLVED by the master map §10, 2026-10-31)
- Q1 (F1 9 vs 10 pairs): pair (2,3) is a 1e-5 tie; compare with tolerance 1e-4 and say so in the test. After the one-line fix hungarian is 0.2698 on all 15 anyway (measured, GATES v2 Phase 0).
- Q3 (do-no-harm path): the fix is one line in `allocate.py`; extra `sim.py` changes need their own failing test (the phase0-fixes `sim.py` change was reverted, see GATES).
- Q4 (hash maps): all removed; helper `cubesat.canon.canonical_log_hash` (sig=5, floor 1e-6, measured; the map's `sig=9` did not survive a perturbation test). There were four test files, not three (test_policy_selection also).
- Q5 ("none" role): v2 only, `roles: []`, `role: "none"`, `original_role`; frontend shows grey "no role".
- Q6 (seed): harness RNG (`monte_carlo.py`) and engine RNG stay separate.
- Q7 (density): full Vallado table, no clamp below 450 km, 1000 km row above 1000 km, `density_factor` multiplier.
- Q8 (assertion points): after the hold and re-seat label sites and after every swap, NOMINAL only; in v2 after every ASSIGNMENT and ROLE_HANDOFF.
- Q9 (K): v2 default 5.
- Q10 (CI): done in Phase 0 (full on ubuntu, fast on windows, frontend job); RK45 cross-checks marked slow.
- Q11 (line numbers): re-verify after any phase that edits `sim.py`/`allocate.py`; regenerate or archive `PHYSICS_ENGINE_EXPLAINED.md` (Track S).
- Q12 (F11 arithmetic): 0.337, consistent.
