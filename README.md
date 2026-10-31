# KINTSUGI-6: CubeSat swarm self-healing (simulation)

A simulation of a hypothetical six-satellite swarm flying in formation. When satellites die, the survivors notice,
hand the lost jobs (swarm leader, ground downlink, imaging) to healthy satellites, and, if worthwhile, fly to a new
formation. Real orbit data is used only as context (orbit altitude/inclination, one illustrative ground station);
no real satellite is modelled. Everything here is simulated, seeded and deterministic: same scenario and seed give
a byte-identical log on one machine (across operating systems the pin is `cubesat.canon.canonical_log_hash`).
Not a flight prediction.

## Run it in 30 seconds

Needs: [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you) and Node 22 (>= 20.19 or >= 22.12; the Vite 7 requirement; CI uses 22).
`frontend/dist` is gitignored, so a fresh clone must build the console once.

```
uv sync --locked
npm --prefix frontend ci && npm --prefix frontend run build
uv run uvicorn cubesat.api:app --port 8000
```

Open <http://127.0.0.1:8000/>. Without the build step `/` returns a "frontend not built" placeholder and the API still works.

No browser, one command (sats 1 and 2, both imagers, die at 1200 s / 1500 s; last line of the file is the SUMMARY):

```
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out /tmp/two_failure.jsonl
```

Docker image: not verified yet.

## What it shows

Kill any two of the six satellites (15 possible pairs, failures at 1200 s and 1500 s, 3 orbits). Without recovery
the swarm is left without a leader or downlink at the end on 9 of 15 pairs; averaged over all 15 pairs a critical role
is vacant 9,418 s (2.6 h; worst 15,830 s, 4.4 h). With autonomous recovery a healthy satellite holds both roles again within 5.9 s on average (worst 16 s, including
the 4 s detection window, which is fixed by construction under ideal comms). Both critical roles end up on healthy
satellites on 15 of 15 pairs.

| policy | critical roles held | mean / worst leader+downlink vacancy (s) | mean coverage | worst per-sat fuel use (m/s) |
|---|---|---|---|---|
| do_nothing | 6/15 | 9418.0 / 15830.0 | 0.2911 | 0.0 (8e-11) |
| role_swap_only | 15/15 | 5.9 / 16.0 | 0.2350 | 0.0 (8e-11) |
| wait_for_ground | 15/15 | 14276.8 / 23928.0 | 0.2698 | 237.1 |
| hungarian (matching + move) | 15/15 | 5.9 / 16.0 | 0.2698 | 251.2 |

Source: `data/eval/baselines_results.json` (`policies_summary`; 15 pairs; coverage = `coverage_mean_last_orbit`).
Command: `uv run python -m cubesat.benchmark --mode baselines --base data/scenarios/two_failure.json --out data/eval/baselines --report data/eval/baselines_results.json`.

- `role_swap_only` re-elects the lost roles among survivors with no motion. `hungarian` additionally moves the survivors to a
  new formation using a matching algorithm. The vacancy metric does not separate them.
- `wait_for_ground` holds recovery until the first ground pass: 23,920 s (6.64 h), one fixed start (RAAN 0, phase 0). The
  mean vacancy mixes 9 pairs that lose a role (23,628-23,928 s) and 6 that do not (0 s).
- Pass model (`data/eval/ground_pass_stats.json`, `uv run python -m cubesat.benchmark --mode ground-passes --base data/scenarios/two_failure.json --report data/eval/ground_pass_stats.json`):
  500 km, 97.4 deg orbit, one station (Bengaluru, elevation >= 10 deg), 48 starts: 2.49 passes/day, mean wait 5.57 h, max gap 13.18 h.
  Illustrative; it depends on the station network.

## The honest trade-off

- Recovery protects the critical roles but costs imaging coverage. On the 9 of 15 pairs that contain sat 0 or sat 5 (sat 0 is the leader, sat 5 the downlink), coverage after recovery is below do_nothing's; mean gain over all 15 pairs is -2.13 pts versus do_nothing
  (`data/eval/benchmark_results.json`, `policies_summary.hungarian.mean_gain_vs_do_nothing_pts`). The +4.93 pts of the
  default demo pair (1,2) is the best case, not typical.
- The fuel is far beyond a CubeSat tank. hungarian's worst per-sat use is 251 m/s against an illustrative 20.12 m/s tank
  (4 kg, 0.2 kg propellant, Isp 40 s; not a hardware claim); 0 of 15 pairs fit in it (`data/eval/benchmark_results.json`, `dv_within_cubesat_tank`,
  `per_sat_dv_mps`).
- `role_swap_only` uses zero fuel and gets the same vacancy as hungarian, at lower mean coverage (0.2350 vs 0.2698), so
  moving buys coverage here, at a fuel cost no CubeSat could pay. No claim is made that moving is better overall.

## Limits

- Orbit equations are linearised. Error versus a full two-body orbit over 3 orbits: 1,578.5 m at the 8 km formation, 3.1 m at 1 km
  (`data/eval/cw_error_report.json`).
- `a_max` is 0.1 m/s^2 in the demo scenarios (`two_failure.json`): about 800 mN at an assumed 8 kg, 5.3x a 150 mN cold-gas
  thruster (0.0188 m/s^2) and 10x the 0.01 m/s^2 default. An assumption, not a hardware spec; the demo makes no flight-realism claim.
- One central planner; ideal communications and sensing; no J2 or drag in the v1 engine (the default).
- The 2 km separation floor is checked on destination formations. In flight, the worst survivor-to-dead-satellite clearance over
  the 15 hungarian runs is 1,852.5 m, below 2 km (`policies_summary.hungarian.worst_min_sep_survivor_dead_m`).
- Failure prediction is display-only and was cut from the control loop after missing its pre-registered bar (GATES.md, predictor note
  and 2026-10-04 Gate-2 entry).
- Ground model: one station, simplifications listed in `cubesat/ground.py`. Failure rates of real missions: unmeasured here.

## Engine v2 (in progress)

Exists and measured (`engine: "v2"` in a scenario; v1 stays the default and byte-identical): a truth model with gravity, J2 and
drag, and a stepping engine with snapshot/restore and replay. It is validated against its own formulas, and compared with the
linear model (6 ring slots, 3 orbits, max position difference in metres, `data/eval/cw_vs_truth_report.json`):

| formation | gravity only | J2 + drag |
|---|---|---|
| 1 km radial amplitude | 18.5 | 184.6 |
| 8 km radial amplitude | 1189.1 | 1944.9 |

The 1 km / 500 m G1 state agrees with the linear model to 3.10 m with J2 and drag off. Command: `uv run python -m cubesat.cw_truth --report data/eval/cw_vs_truth_report.json`.
Formulas, defaults (mass, drag area: illustrative) and checks: `docs/PHYSICS_V2.md`.

Not done: fuel model, safety certificate, recovery ladder (role swap first, move only if certified). No v2 performance
or safety claim is made.

## Reproduce the numbers

Commands of record (from GATES.md); each rewrites its committed `data/eval/` artifact. Checked 2026-10-31 on a fresh clone (macOS arm64): baselines (~2 min), ground-passes and cw_truth rewrote byte-identical files; cw-curve matched to its printed 4 figures but differs in the low digits (about 1e-6 relative) and CSV line endings; the full test suite takes ~2.5 min:

```
uv run python -m cubesat.benchmark --base data/scenarios/two_failure.json --out data/eval/benchmark --report data/eval/benchmark_results.json --policies do_nothing,even_split,greedy,hungarian   # ~2 min
uv run python -m cubesat.benchmark --mode baselines --base data/scenarios/two_failure.json --out data/eval/baselines --report data/eval/baselines_results.json
uv run python -m cubesat.benchmark --mode ground-passes --base data/scenarios/two_failure.json --report data/eval/ground_pass_stats.json
uv run python -m cubesat.benchmark --mode cw-curve --base data/scenarios/two_failure.json --report data/eval/cw_error_report.json --csv data/eval/cw_error_curve.csv --svg data/eval/cw_error_curve.svg
uv run python -m cubesat.cw_truth --report data/eval/cw_vs_truth_report.json
uv run python -m pytest -q
uv run ruff check .
```

Raw log hashes (`benchmark_manifest.json`) are platform-bound; the cross-platform identity is `canonical_log_hash`.

## Repo map

- `cubesat/`: simulator, planner, FastAPI + WebSocket API (`api.py`), benchmark CLI.
- `frontend/`: React + Three.js console (served from `frontend/dist` after the build above).
- `data/scenarios/`: scenario JSON; `data/eval/`: committed measurement artifacts.
- `GATES.md`: every number with its command. `PROJECT_MEMORY.md`: project map and current state.
- `docs/PHYSICS_V2.md`: v2 truth model. `docs/audit/`: evidence audits.
- `docs/superpowers/specs/KINTSUGI-6_v2_master_map.md`: v2 plan.
