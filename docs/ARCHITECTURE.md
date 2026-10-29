# ARCHITECTURE.md

Self-healing CubeSat swarm: failure detection → replanning → reconfiguration, under
Hill–Clohessy–Wiltshire relative dynamics. Spec: `docs/MASTER_PROMPT.md`; gate ledger:
`GATES.md`.

**Status (2026-09-28):** G0–G4 tagged pass (tags `gate-0-pass` … `gate-4-pass`; GATES.md
is the ledger and the single source for gate numbers and evidence commands). G5 (API/UI)
and G6 (deploy) have not started: `cubesat/api.py` is the G0 `/health` skeleton only
(`cubesat/api.py:1-12`).

Number policy: measured numbers below come only from GATES.md's "Numbers allowed in
README/pitch" list, each with the command that produced it. Anything else is
**unmeasured**.

## Module map

| Module | One line |
|---|---|
| `cubesat/scenario.py` | Pydantic v2 scenario schema + `load_scenario`; validates altitude/step bounds, failure modes, and that every `failures[].sat_id` exists (`scenario.py:117-124`). |
| `cubesat/hcw.py` | Analytic CW machinery: `mean_motion` (`hcw.py:23`), unforced STM + `propagate` (`hcw.py:28,57`), forced `propagate_controlled` = Φ(t)x₀ + G(t)a (`hcw.py:109`), and `slot_initial_state` (`hcw.py:119`) — slots live here, not in sim, so the allocator can build formations without importing the sim loop (`hcw.py:129-130`). |
| `cubesat/pd.py` | PD law `u = -Kp·r_err - Kd·v_err` against the *moving* slot reference, vector-magnitude thrust saturation, per-satellite `dv_used += |u|·dt` accounting (`pd.py:56-77`); `bang_bang_time_lower_bound` = 2√(d/a_max) reference time (`pd.py:30`). |
| `cubesat/coverage.py` | The coverage metric, fixed and never retuned (research patch #2): footprint `r_f = h·tan(FOV/2)` (`coverage.py:24`), square (y, z) target grid (`coverage.py:30`), coverage = fraction of grid points in the **union** of healthy imagers' footprint discs (`coverage.py:38`). |
| `cubesat/allocate.py` | Two-step replanner (G4): sweep (amplitude, phase-offset) candidate formations, feasible iff min pairwise separation holds with coasting dead sats as obstacles *and* a perfect matching fits the Δv budget; keeps the highest measured coverage, ties keep the first in sweep order (`allocate.py:134-179`). Then rectangular `linear_sum_assignment` on `w1·dist + w2·dist/fuel + w3·mismatch` + index epsilon, with a deterministic greedy fallback (`allocate.py:182-230`). Entry point `replan` (`allocate.py:233`). |
| `cubesat/sim.py` | Pure sim loop: fixed-dt stepping, heartbeat failure detection, swarm state machine, coverage + `min_sep` per tick, and the JSONL line model. No I/O — returns a list of dicts (`sim.py:80`). |
| `cubesat/run.py` | CLI I/O edge: load scenario (CLI `--seed` overrides), run, write JSONL with `sort_keys` and `newline="\n"` (`run.py:42-44`). Log is gitignored; commit the hash, not the log (`run.py:7`). |
| `cubesat/api.py` | FastAPI skeleton, `/health` only. `/api`, `/ws` and the static UI arrive at G5 (`api.py:1`). |

## Data flow

```
scenario JSON  ──load_scenario──▶  Scenario (validated)
                                     │
                        run_scenario (pure, cubesat/sim.py:79)
                                     │  list[dict]: INIT, tick…, SUMMARY
                                     ▼
                  run.py writes JSONL (one line per dict, sort_keys)
                                     │
                                     ▼
                  data/logs/*.jsonl  (gitignored; golden SHA pinned in tests)
                                     │
                                     ▼  (G5, not built yet)
                  FastAPI /api + /ws + replay endpoint  ◀── React dashboard
```

- The sim core never touches disk or wall clock; `run.py` is the only writer
  (`sim.py:3-6`, `run.py:3-7`).
- Two runs of one scenario + seed are byte-identical; `tests/test_cli.py` pins a golden
  SHA-256 of the short nominal run (`tests/test_cli.py:13`, digits in the source).
- G5 replay will read this log format; the schema below is the contract.

## Determinism design (AGENTS.md invariant 2)

No wall clock, no RNG anywhere in the core; same scenario + seed ⇒ byte-identical log.
Mechanics that make that hold:

- Fixed-dt steps; the only propagation is the analytic STM (± exact constant-acceleration
  forcing), no adaptive integrator inside the sim (`sim.py:301-308`).
- Failures are pre-sorted by `(t, sat_id)` before the loop (`sim.py:107`); events are a
  FIFO list, at most one popped per tick line (`sim.py:110,195-196`).
- No set/dict-order dependence: role re-election iterates `dict.fromkeys` first-occurrence
  order, never sets (`allocate.py:65`).
- Assignment ties break with a row-major index epsilon `_TIE_EPS = 1e-9`
  (`allocate.py:42,202`); formation-sweep ties keep the **first** candidate
  (`allocate.py:175-176`).
- The greedy fallback is forced by a deterministic **size cap** (`_MAX_COST_CELLS`),
  never a wall-clock timeout — a timeout would break reproducibility
  (`allocate.py:43,212`).
- Output ordering: `json.dumps(..., sort_keys=True)`, LF newlines (`run.py:42-44`).
- Regression pin: the short nominal run is hashed against a committed golden SHA-256 in
  `tests/test_cli.py`; any sim/schema/scenario change moves the hash and must be
  acknowledged there (`tests/test_cli.py:75-92`).

## Units and frame (AGENTS.md invariants 3–4)

- **SI internally**: m, s, rad, m/s, m/s². `cubesat/hcw.py:3-5` states it; µ = 3.986004418e14
  m³/s² and R⊕ = 6378.137e3 m are constants (`hcw.py:19-20`).
- Scenario JSON stores human units (km, deg, half-angle deg) **by field name**;
  conversion happens once at the sim edge: `altitude_km * 1000` (`sim.py:82`),
  `radial_amp_km * 1000` (`sim.py:70`), `math.radians(fov_half_angle_deg)` (`sim.py:92`),
  `min_sep_km * 1000` (`allocate.py:257`).
- **LVLH frame, x radial, y along-track, z cross-track**; state ordering is
  `[x, y, z, vx, vy, vz]` (`hcw.py:4-5`). The 2:1 drift-free ellipse (vy0 = −2n·x0) is the
  common passive orbit all slots sit on (`hcw.py:119-142`).

## Scenario JSON schema

Source: `cubesat/scenario.py` (pydantic v2). Example files: `data/scenarios/nominal.json`,
`data/scenarios/two_failure.json`.

| Field | Type / constraint | Default |
|---|---|---|
| `name` | str, non-empty | — |
| `seed` | int ≥ 0 | — |
| `duration_s` | float > 0 | — |
| `dt_s` | float, 0 < dt ≤ 10 | — |
| `chief.altitude_km` | float, 160 < h < 2000 | — |
| `formation.n_slots` | int ≥ 2 | — |
| `formation.radial_amp_km` | float > 0 | — |
| `formation.phase_offset_deg` | float | 0.0 |
| `a_max_mps2` | float > 0 (thrust saturation; research patch #1 default 1e-2, `pd.py:24-27`) | — |
| `gains.wn` / `gains.zeta` | float > 0 (rad/s / dimensionless) | — |
| `sensor.fov_half_angle_deg` | float, 0 < ≤ 45 — stores the **half** angle | — |
| `sensor.grid_step_km` / `grid_extent_km` | float > 0 | — |
| `roles` | list[str], ≥ 2; index = sat id | — |
| `failures[]` | `{t ≥ 0, sat_id ≥ 0, mode: DEAD \| THRUSTER_OUT \| EPS_DEGRADE, degrade_s ≥ 0 (EPS_DEGRADE fade length, s — Addendum v1.2, 2026-10-26)}` | `[]` / `degrade_s: 0.0` |
| `recovery_enabled` | bool — false = detect but never replan (no-recovery baseline) | true |
| `detection.missed_ticks_k` | int ≥ 1 — missed heartbeats before declaring failure | 3 |
| `allocation.w1/w2/w3` | cost weights (distance / distance-per-fuel / role mismatch) | 1.0 / 0.5 / 2.0 |
| `allocation.min_sep_km` | float > 0, pairwise separation constraint, dead sats included | 2.0 |
| `allocation.dv_budget_mps` | float > 0, per-transfer reachability budget | 100.0 |
| `allocation.amp_sweep` / `phase_sweep_deg` | deterministic sweep grids (≥ 1 each) | `[1.0]` / `[0, 60, …, 300]` |
| `allocation.method` | `hungarian` \| `greedy` (greedy = forced fallback demo toggle) | `hungarian` |
| `safety.evasion_enabled` / `evade_radius_m` / `evade_ticks` | bounded evasive-burn block (Addendum v1.2, 2026-10-26): a sat inside the radius of another starts a discrete away-from-intruder burn — explicitly NOT potential fields; default-inert GEOMETRICALLY (1000 m < every measured clearance), so canonical runs stay byte-identical (`scenario.py:114-133`) | `true` / `1000.0` / `25` |

Cross-field rule: every `failures[].sat_id` must be `< len(roles)` (`scenario.py:161-167`).
`DEAD` = no comms, no thrust, coasts ballistically; `THRUSTER_OUT` = reports, cannot
maneuver (`scenario.py:12-19`). **(2026-10-26, Addendum v1.2):** `THRUSTER_OUT` now
SELF-REPORTS on the firing tick (`self_report: true` — the same recovery path as
silence, detection latency 0), and `EPS_DEGRADE` holds the sat in a `DEGRADED` fade
for `degrade_s` seconds before it dies exactly like `DEAD` (`degrade_s = 0` is
sudden: byte-identical to `DEAD` except the FAILURE_DETECTED mode label).

## JSONL log schema

One JSON object per line, `v = LOG_SCHEMA_VERSION = 1` (`sim.py:49`). Defined in
`sim.py:8-18`; written by `run.py`.

**Line 1 — INIT header** (`sim.py:116-125`):

```json
{"v": 1, "t": 0.0, "state": "INIT", "scenario": "<name>", "seed": <int>, "n_sats": <int>}
```

**Tick lines** — one per fixed-dt step (`sim.py:185-205`):

```json
{"v": 1, "t": <sim s>, "state": "<mission state>",
 "sats": [{"id": <int>, "role": "<str>", "status": "<str>",
           "r": [x, y, z], "v": [vx, vy, vz], "dv_used": <m/s>}, …],
 "coverage": <0..1>, "min_sep": <m>,
 "event": {…}}          // optional key, omitted when no event this tick
```

- Per-sat `status`: `NOMINAL` / `DEGRADED` / `DEAD` / `THRUSTER_OUT` (`sim.py:78-81`;
  `DEGRADED` added 2026-10-26, Addendum v1.2 — an EPS_DEGRADE sat in its fade window:
  keeps reporting and holding its seat but is excluded from replan assignment).
  DEAD and THRUSTER_OUT sats coast ballistically — never frozen — and stay in the
  `min_sep` pairwise loop as hazards (AGENTS.md invariant 5, `sim.py:263-289`).
- Mission `state` machine (`sim.py:20-24`):
  `NOMINAL → FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED`; a new failure
  re-enters `FAILURE_DETECTED` from any state; `recovery_enabled = false` stops at
  `FAILURE_DETECTED`. The replanner runs **between** sim steps — one control cycle per
  transition — so each *decision* state (`FAILURE_DETECTED`, `REPLANNING`) lasts exactly
  one tick in the log, while `RECONFIGURING` spans the physical transfers until every
  survivor settles within tolerance (two_failure: 1208→3114 s) and `RECOVERED` holds to
  the end.
- Event payloads (`sim.py:25-40`):
  - `FAILURE_DETECTED`: `{sat_id, mode, t_fail, t_detect, self_report?}` —
    `self_report: true` marks a failure the sat announced itself (THRUSTER_OUT,
    2026-10-26: t_detect == t_fail for tick-aligned failures)
  - `DEGRADE_START`: `{sat_id, t_fail, degrade_s}` (EPS_DEGRADE fade onset, Addendum v1.2)
  - `STATE`: `{from, to}`
  - `ASSIGNMENT`: `{assignments: [{sat_id, slot_index, role}], method, cost_total,
    formation: {radial_amp_m, phase_offset_rad}, transfer_lower_bound_s}` —
    `transfer_lower_bound_s` is the bang-bang lower bound 2·√(d/a_max) for the largest
    assigned transfer, logged per reconfig (research patch #1).
  - `EVASIVE_MANEUVER`: `{sat_id, other_id, range_m, t}` (Addendum v1.2, 2026-10-26 —
    a bounded evasion episode started; never fires on canonical runs, whose measured
    clearances all exceed the default 1000 m radius)

**Last line — SUMMARY** (`sim.py:310-320`):

```json
{"v": 1, "t": <final t>, "state": "SUMMARY", "coverage_mean_last_orbit": <0..1>}
```

Time-averaged coverage over the final orbit (MASTER_PROMPT 3.4).

## Test layout

Tests-first per gate: each module's test file was written before the module existed and
fails collection until implemented (stated in each file's docstring, e.g.
`tests/test_allocation.py:1-3`). Required test names come from MASTER_PROMPT 3.8.

| File | Covers |
|---|---|
| `tests/test_hcw.py` | G1: STM vs RK45 of the CW ODEs; passive-ellipse closure; CW-vs-Kepler report. |
| `tests/test_pd.py` | G2: step response, saturation respected, passive slot ≈ zero Δv, forced propagator vs ODE. |
| `tests/test_coverage.py` | G3: footprint formula, grid shape, union monotonicity (removing a center can only shrink coverage), nominal-scenario slots. |
| `tests/test_scenario_schema.py` | Schema validation rejects bad altitude / unknown failure mode. |
| `tests/test_cli.py` | G3: CLI end-to-end, valid JSONL, byte-determinism via golden SHA-256. |
| `tests/test_allocation.py` | G4: role re-election, cost matrix, rectangular Hungarian, determinism, greedy fallback not better. |
| `tests/test_fault.py` | G4: injection/detection latency, state-machine sequence, min-separation floor, recovery-beats-no-recovery on `two_failure.json`. |
| `tests/test_smoke.py` | G0: package version + `/health`. |

Commands (AGENTS.md): full suite `uv run pytest -q`; fast loop
`uv run pytest -m "not slow" -x -q`; lint `uv run ruff check .`. The `slow` marker flags
the Kepler cross-check and the byte-determinism hash (`pyproject.toml`
`[tool.pytest.ini_options]`); currently marked on the Kepler cross-check only
(`tests/test_hcw.py:102`).

## Limitations (honesty items — mirrors MASTER_PROMPT §7 + research patch #5)

- **Linearized HCW, circular unforced chief.** No J2, drag, or attitude dynamics; no
  eccentricity. "Dead sat stays bounded" holds only in linear unperturbed HCW — J2 and
  drag cause drift (research patch #5).
- **Nonlinear cross-check, measured:** CW-vs-Kepler max position error **3.101 m** over
  3 orbits for the 1 km radial / 500 m cross-track passive ellipse
  (`uv run pytest tests/test_hcw.py -s -q`). At the **nominal formation scale** (22 km
  along-track slot) the same two-body solve_ivp cross-check gives **2984.5 m** over
  3 orbits — positions in the log are CW-consistent, not Kepler-true. The G3-era scratch
  command was not recorded (docs/IMPLEMENTATION_NOTES.md G3 section describes it only),
  so the command of record is this re-run (2026-09-28; method =
  `tests/test_hcw.py::test_cw_vs_kepler_error_report` with the nominal slot state):

  ```
  uv run python -c '
  import math, numpy as np
  from scipy.integrate import solve_ivp
  from cubesat.hcw import stm_propagate as P, slot_initial_state as S
  M=3.986004418e14; A=6378.137e3+500e3; N=math.sqrt(M/A**3)
  s=S(11000.0,11000.0,math.pi/2,N)
  te=3.0*2.0*math.pi/N; g=np.linspace(0.0,te,601)
  f=lambda st: solve_ivp(lambda t,y: np.concatenate([y[3:],-M*y[:3]/np.linalg.norm(y[:3])**3]),(0.0,te),st,rtol=1e-12,atol=1e-9,t_eval=g).y
  c=f(np.array([A,0.0,0.0,0.0,N*A,0.0]))
  h=f(np.concatenate([np.array([A,0.0,0.0])+s[:3],np.array([0.0,N*A,0.0])+s[3:]+np.cross([0.0,0.0,N],s[:3])]))
  w=np.asarray(P(s,g,N))
  e=[np.linalg.norm(np.array([d@x,d@(np.cross(q,x)),d@q])-w[k,:3]) for k in range(601) for r,x,q,d in [(c[:3,k],c[:3,k]/np.linalg.norm(c[:3,k]),np.cross(c[:3,k],c[3:,k])/np.linalg.norm(np.cross(c[:3,k],c[3:,k])),h[:3,k]-c[:3,k])]]
  print(f"{max(e):.1f} m")
  '
  ```

  Output: `2984.5 m` (matches the GATES.md value).
- **Ideal comms and sensing.** Heartbeat detection is an abstraction: a sat that stops
  reporting is declared DEAD after `missed_ticks_k` misses; no link budget, latency, or
  measurement noise is modeled (`sim.py:42-45`). **(2026-10-26, Addendum v1.2):**
  detection is no longer silence-only — a `THRUSTER_OUT` sat self-reports on the firing
  tick (latency 0) and `EPS_DEGRADE` announces a `DEGRADE_START` fade before death;
  min separation is additionally defended by a bounded evasive burn (`Safety`,
  `scenario.py:114-133`), geometrically inert on every canonical run (default 1000 m
  radius below every measured clearance, e.g. P0 worst survivor-dead 1322.6 m).
- **Centralized replanner.** One ground-side `replan` call; no distributed consensus, no
  CBBA (anti-goal, MASTER_PROMPT §8).
- **Coverage definition is fixed by fiat.** Fraction of a square (y, z) grid inside the
  union of healthy imagers' nadir footprints, `r_f = h·tan(FOV/2)` on a flat ground plane
  h below the chief, formation |x| ≪ h (`coverage.py:1-15`). If a formation change
  doesn't move coverage, spacing/FOV is tuned — never the metric (research patch #2).
- **Simulation-only.** No hardware, no flight software; every result is a sim log.
- **Hardware figures are an unverified assumption.** a_max = 1e-2 m/s² assumes ~8 kg /
  ~150 mN cold-gas thrusters, labelled as an assumption in `pd.py:24-27`.
- **No G4 numbers here.** Recovery-vs-no-recovery, Δv, and min-separation results live in
  GATES.md's G4 row (single source); this doc describes the machinery only.
- **The failure demo needs more thrust than the assumed hardware class.** `two_failure.json`
  carries `a_max = 0.1 m/s²` (~800 mN at 8 kg) against the 1e-2 (~150 mN) default
  (`pd.py:24-27`): at 1e-2 the G2 PD diverges on formation-scale transfers at every spacing
  swept (4–11 km, measured 2026-09-28 — burn-induced Coriolis radial oscillations exceed
  the saturation authority), so the demo flies 0.1 with 8 km slots and per-sat Δv up to
  193.68 m/s. The proper fix is an impulsive/MPC transfer planner (future work). Numbers
  and commands: GATES.md G4 row.
