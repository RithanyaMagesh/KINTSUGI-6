# Gate ledger (update every gate)

| Gate | Status | Evidence (command + output tail / commit) | Key measured numbers | Date |
|---|---|---|---|---|
| G0 | PASS | `uv run pytest` → 9 passed, in clean clone /tmp/g0clone via `uv sync --frozen` + `uv run pytest`; commits 460f73c, 74854bb | none yet (skeleton) | 2026-09-28 |
| G1 | PASS | `uv run pytest tests/test_hcw.py -s -q` → `test_hcw_stm_vs_ode: max position relative error = 1.353e-12, max velocity relative error = 5.599e-10` and `test_cw_vs_kepler_error_report: max position error over 3 orbits = 3.101 m` (exit 0); `uv run pytest -q` → `............` `[100%]` = 12 passed; tag `gate-1-pass` | CW-vs-Kepler max position error **3.101 m** over 3 orbits, 1 km radial + 500 m cross-track passive ellipse (`uv run pytest tests/test_hcw.py -s -q`, printed by test_cw_vs_kepler_error_report); STM-vs-ODE max relative error position **1.353e-12**, velocity **5.599e-10** (same command, printed by test_hcw_stm_vs_ode; asserted bound 1e-6) | 2026-09-28 |
| G2 | todo | | | |
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
(Dockerfile build unverified — Docker daemon was not running at G0 time | G0 session log | build and verify before G6)
(CW-vs-Kepler nonlinear error measured at G1: 3.101 m for the 1 km radial / 500 m cross-track passive ellipse over 3 orbits | `uv run pytest tests/test_hcw.py -s -q` | linearization error grows with separation — re-measure with formation-scale states before citing validity for larger reconfigs)
(HCW validity: "dead sat stays bounded" only holds linear unperturbed; J2/drag drift | research patch #5 | state in README limitations at G7)

## Numbers allowed in README/pitch
(metric | value | log file | exact command)
(CW-vs-Kepler max position error, 1 km radial + 500 m cross-track passive ellipse, 3 orbits | 3.101 m | tests/test_hcw.py printed output, recorded in GATES.md G1 row + docs/IMPLEMENTATION_NOTES.md | `uv run pytest tests/test_hcw.py -s -q`)
