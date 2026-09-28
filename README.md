# CubeSat Swarm Self-Healing (Problem #b2ef60e9)

Six CubeSats fly a formation in LVLH under Hill–Clohessy–Wiltshire dynamics. When satellites
fail, survivors detect the loss (missed heartbeats), a Hungarian assignment (`linear_sum_assignment`)
reassigns each survivor to a new slot on the formation, and a PD controller with thrust saturation
flies them there — restoring a measured part of the lost ground coverage, scored against a
no-recovery baseline. Everything is a deterministic, seeded simulation: same scenario + seed ⇒
byte-identical JSONL log.

**Status:** G0–G4 pass (tags `gate-0-pass` … `gate-4-pass`). G5 (backend + frontend, owned by a
teammate) and G6 (deploy) are in progress — not landed; no numbers below come from them.

## Quickstart

```
uv sync --locked
uv run ruff check .
uv run pytest -q                    # full suite
uv run pytest -m "not slow" -x -q   # fast loop
```

Run the two-failure scenario:

```
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
```

Serve the API:

```
uv run uvicorn cubesat.api:app --port 8000
```

## Measured numbers

Each number below comes from the command shown, as recorded in GATES.md. Nothing else is claimed.

- CW-vs-Kepler max position error, 1 km radial + 500 m cross-track passive ellipse, 3 orbits: **3.101 m**
  (`uv run pytest tests/test_hcw.py -s -q`)
- 1 km rest-to-slot PD reconfiguration (a_max = 1e-2 m/s^2): settles in **746 s** using **6.411 m/s** Δv,
  overshoot **4.99%**, max \|u\| = a_max (`uv run pytest tests/test_pd.py -s -q`)
- Slot-to-slot quarter-phase reconfiguration, same 1 km passive ellipse: **20.176 m/s** Δv,
  settles in **1966 s** (bang-bang lower bound 945.7 s) (`uv run pytest tests/test_pd.py -s -q`)
- Nominal 6-sat run, 1 orbit: mean tick coverage **0.4387** (orbit range 0.4266–0.4547),
  min separation **15.56–17.39 km**, per-sat Δv ~**1e-11 m/s**
  (`uv run python -m cubesat.run --scenario data/scenarios/nominal.json --seed 42 --out data/logs/nominal.jsonl`)
- Coverage metric, no recovery: killing 2 of the 4 imagers drops time-averaged coverage by
  **16.65 pts** (worst pair) to **19.99 pts** (best) (`uv run pytest tests/test_coverage.py -s -q`)
- Two-failure demo (2 imagers DEAD at t = 1200/1500 s, 3 orbits): with-recovery last-orbit mean
  coverage **0.2698** vs no-recovery **0.2205** (+**4.93 pts** — about 31% of the coverage the
  failures destroy); no-recovery drop **15.91 pts** from the pre-failure 0.3796 (patch-#2 target
  ≥ 15); worst min separation **3095.1 m** (threshold 2000 m) including the transfer trajectories;
  detection latency **4 s**; per-sat Δv up to **193.68 m/s**
  (`uv run pytest tests/test_fault.py -s -q`; log regenerates with the run command above)

## Honesty / limitations

- Linearized HCW equations with a circular chief; no J2, drag, or attitude dynamics.
- Ideal comms and sensing; centralized replanner (no distributed consensus).
- Coverage = fraction of a ground-target grid inside the union of healthy imagers' footprints,
  r_f = h·tan(FOV/2).
- Results are simulation-only — not flight predictions.
- Nothing is hardcoded: scenarios are external JSON, the allocation is computed at
  runtime, and every log regenerates from the single commands shown above.
- Nonlinear cross-check error: **2984.5 m** over 3 orbits at the nominal formation scale
  (22 km along-track slot), two-body solve_ivp cross-check — reproduced 2026-09-28 with:

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

  (the G3-era scratch command is not recorded in the repo — docs/IMPLEMENTATION_NOTES.md
  G3 section describes it only — so this re-run, which follows
  `tests/test_hcw.py::test_cw_vs_kepler_error_report` with the nominal slot state, is the
  command of record)
- Dead-sat caveat (research patch #5): a dead satellite stays on a bounded relative orbit only in
  linear, unperturbed HCW; J2 and drag would make it drift.
- The default a_max of 1e-2 m/s^2 assumes an ~8 kg CubeSat with ~150 mN cold-gas thrust — an
  assumption, not a verified thruster specification.
- **The failure demo needs more thrust than that assumption.** `two_failure.json` carries
  `a_max = 0.1 m/s^2` (~800 mN at 8 kg): at 1e-2 the G2 PD diverges on formation-scale transfers
  at every spacing swept (4–11 km, measured 2026-09-28 — burn-induced Coriolis radial oscillations
  exceed the saturated controller's authority), so the demo flies 0.1 m/s^2 with 8 km slots and
  per-sat Δv up to 193.68 m/s — above a realistic cold-gas budget. The proper fix is an
  impulsive/MPC transfer planner (future work). Numbers and commands: GATES.md G4 row.
