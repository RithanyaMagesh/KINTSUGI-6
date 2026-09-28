# Gate ledger (update every gate)

| Gate | Status | Evidence (command + output tail / commit) | Key measured numbers | Date |
|---|---|---|---|---|
| G0 | PASS | `uv run pytest` → 9 passed, in clean clone /tmp/g0clone via `uv sync --frozen` + `uv run pytest`; commits 460f73c, 74854bb | none yet (skeleton) | 2026-09-28 |
| G1 | todo | | | |
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

## Open risks
(Mimosa full security audit pending — hook flagged incomplete scan at commit time | commit 460f73c hook output | run full audit before submission)
(Dockerfile build unverified — Docker daemon was not running at G0 time | G0 session log | build and verify before G6)
(CW-vs-Kepler nonlinear error unmeasured until G1 | master prompt 3.1 | measure and record here)
(HCW validity: "dead sat stays bounded" only holds linear unperturbed; J2/drag drift | research patch #5 | state in README limitations at G7)

## Numbers allowed in README/pitch
(metric | value | log file | exact command)
(none yet — every number is unmeasured until a gate produces a committed log)
