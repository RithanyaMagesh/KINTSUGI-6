# Gate ledger (update every gate)

| Gate | Status | Evidence (command + output tail / commit) | Key measured numbers | Date |
|---|---|---|---|---|
| G0 | PASS | `uv run pytest` → 9 passed, in clean clone /tmp/g0clone via `uv sync --frozen` + `uv run pytest`; commits 460f73c, 74854bb | none yet (skeleton) | 2026-09-28 |
| G1 | PASS | `uv run pytest tests/test_hcw.py -s -q` → `test_hcw_stm_vs_ode: max position relative error = 1.353e-12, max velocity relative error = 5.599e-10` and `test_cw_vs_kepler_error_report: max position error over 3 orbits = 3.101 m` (exit 0); `uv run pytest -q` → `............` `[100%]` = 12 passed; tag `gate-1-pass` | CW-vs-Kepler max position error **3.101 m** over 3 orbits, 1 km radial + 500 m cross-track passive ellipse (`uv run pytest tests/test_hcw.py -s -q`, printed by test_cw_vs_kepler_error_report); STM-vs-ODE max relative error position **1.353e-12**, velocity **5.599e-10** (same command, printed by test_hcw_stm_vs_ode; asserted bound 1e-6) | 2026-09-28 |
| G2 | PASS | `uv run pytest tests/test_pd.py -s -q` → `test_pd_step_response: overshoot = 4.99% (limit 5%), t_settle = 746 s (target 1265 s = 2x bang-bang bound 632 s), max \|u\| = 0.0100 m/s^2 (a_max = 0.01), dv_used = 6.411 m/s`, `test_saturation_respected: max \|u\| = 0.010000 m/s^2 (a_max = 0.01), bang-bang lower bound for d = 2236.1 m: t >= 945.7 s, t_settle = 1966 s, dv_used = 20.176 m/s`, `test_passive_slot_low_dv: max position error over one orbit = 2.198e-11 m, dv_used = 1.410e-12 m/s, max \|u\| = 1.411e-15 m/s^2`, `test_forced_propagator_matches_ode: position relative error = 2.283e-13, velocity relative error = 2.323e-13`; `uv run pytest` → `16 passed in 1.97s`; `uv run ruff check .` → `All checks passed!`; tag `gate-2-pass` | 1 km step: overshoot **4.99%**, settle **746 s** (target = 2x bang-bang bound), **6.411 m/s** Δv (bang-bang-optimal Δv = 2√(d·a_max) = 6.32 m/s — near-optimal); 2.24 km quarter-phase reconfig: **20.176 m/s**, settle 1966 s (lower bound 945.7 s); occupied passive slot: error **2.198e-11 m**, Δv **1.410e-12 m/s** over one orbit; forced propagator vs RK45 rel err **2.3e-13** | 2026-09-28 |
| G3 | todo | | | |
| G4 | todo | | | |
| G5 | todo | | | |
| G6 | todo | | | |
| G7 | todo | | | |

## Decisions log
(2026-09-28 | a_max default 1e-4 → 1e-2 m/s^2 (cold-gas class, ~8 kg / ~150 mN assumption) | user research patch #1, overrides master prompt | approved: user)
(2026-09-28 | Docker uses `uv sync --locked` + pinned uv image tag; CI aligned to `--locked` | user research patch #4 | approved: user)
(2026-09-28 | footprint half-angle 1–2 deg (r_f ~9–17 km at 500 km); coverage must drop ≥15 points with 2 dead and no recovery, else change spacing/FOV never the metric | user research patch #2 | approved: user)
(2026-09-28 | frontend locked decision changed: React 18 + Vite + TS + Zustand + plain-Three.js-in-React + Recharts + CSS Modules per docs/FRONTEND_SPEC.md v2.0 — supersedes MASTER_PROMPT §2 "Frontend: Plain Three.js, single page" and §8 "no React" for the frontend only; FRONTEND_SPEC §13 design law (anti-AI-slop tokens/checklist/scanner) is mandatory for all UI work | user supplied + approved spec | approved: user)

## Open risks
(Mimosa full security audit pending — hook flagged incomplete scan at commit time | commit 460f73c hook output | run full audit before submission)
(Dockerfile build VERIFIED 2026-09-28 (G2 session re-ran it first-hand): `docker build -t cubesat-g2-verify .` exit 0, image sha256:391d099d53ea092fa5b5c04d57e4b54c51441a315988068c46fb3fec090b948e, 816 MB, `uv sync --locked --no-dev` inside | Docker 29.8.0 on the dev machine | re-check at G6 deploy, container run/healthcheck not yet exercised)
(CW-vs-Kepler nonlinear error measured at G1: 3.101 m for the 1 km radial / 500 m cross-track passive ellipse over 3 orbits | `uv run pytest tests/test_hcw.py -s -q` | linearization error grows with separation — re-measure with formation-scale states before citing validity for larger reconfigs)
(HCW validity: "dead sat stays bounded" only holds linear unperturbed; J2/drag drift | research patch #5 | state in README limitations at G7)

## Numbers allowed in README/pitch
(metric | value | log file | exact command)
(CW-vs-Kepler max position error, 1 km radial + 500 m cross-track passive ellipse, 3 orbits | 3.101 m | tests/test_hcw.py printed output, recorded in GATES.md G1 row + docs/IMPLEMENTATION_NOTES.md | `uv run pytest tests/test_hcw.py -s -q`)
(1 km rest-to-slot PD reconfiguration, a_max = 1e-2 m/s^2, wn = 0.01, zeta = 1, dt = 2 s | settled in 746 s using 6.411 m/s delta-v, overshoot 4.99%, max \|u\| = a_max | tests/test_pd.py printed output, recorded in GATES.md G2 row + docs/IMPLEMENTATION_NOTES.md | `uv run pytest tests/test_pd.py -s -q`)
(slot-to-slot quarter-phase reconfiguration, same 1 km passive ellipse | 20.176 m/s delta-v, settled in 1966 s (bang-bang lower bound 945.7 s) | tests/test_pd.py printed output, recorded in GATES.md G2 row + docs/IMPLEMENTATION_NOTES.md | `uv run pytest tests/test_pd.py -s -q`)
