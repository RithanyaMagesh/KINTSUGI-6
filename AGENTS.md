# KINTSUGI-6 CubeSat swarm self-healing (hackathon #b2ef60e9)
Deterministic CubeSat swarm simulator: failure detection, role reassignment and re-formation under Hill–Clohessy–Wiltshire dynamics, FastAPI + WebSocket backend, React + Three.js console. Work continues after the hackathon on branch `v2` (never merge to master without the user; pushing branch `v2` is allowed).

## Where things are (read in this order before writing code)
1. `PROJECT_MEMORY.md` — project map, decisions, current state (refreshed each phase).
2. `docs/superpowers/specs/KINTSUGI-6_v2_master_map.md` — the master spec (tracks, problem map, order, decisions D1–D4, §11 console spec).
3. `docs/superpowers/plans/2026-10-31-v2-plan.md` — the order, merged problem map, status. Physics tasks: `docs/superpowers/plans/2026-10-31-physics-v2-plan.md`.
4. `GATES.md` — the ledger: every number with its command. `docs/audit/2026-10-31-{a,b,c}.md` — audit findings.
Older history/specs (`docs/MASTER_PROMPT.md`, `BACKEND_SPEC.md`, `FRONTEND_SPEC.md` §13 design law, `HANDOFF.md`, `ARCHITECTURE.md`) are partly stale: the tree and GATES.md win. The old code graph is archived in `docs/archive/graphify-out/` (dated 2026-09-29; do not rely on it).

## Commands
- `uv sync --locked`
- `uv run ruff check .`
- `uv run python -m pytest -q`                    (full suite, CI uses this)
- `uv run python -m pytest -m "not slow" -x -q`   (fast loop)
- run: `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out /tmp/two_failure.jsonl`
- serve: `uv run uvicorn cubesat.api:app --port 8000`
- frontend: `cd frontend && npm ci && npm run build` (hex gate: `grep -rnE '#[0-9a-fA-F]{3,8}' src | grep -v styles/tokens.css` must print nothing)

## Invariants (never violate)
1. No number in README, dashboard, or pitch without a committed log AND the command that produced it. Unmeasured = write "unmeasured".
2. Determinism: no wall-clock, no unseeded RNG, no set/dict-order dependence inside the sim. Same scenario + seed => byte-identical log.
3. Units: SI internally (m, s, rad, m/s^2). Convert only at the UI edge.
4. Frame: LVLH, x radial, y along-track, z cross-track.
5. Dead satellites coast ballistically (never freeze) and count as obstacles.
6. linear_sum_assignment: rows = survivors, cols = candidate slots. Break ties with an index epsilon.
7. Locked decisions (docs/MASTER_PROMPT.md section 2) change only with user approval, with evidence.
8. Research patches (docs/MASTER_PROMPT.md final section) override the master prompt where they conflict.
9. Golden pins use `cubesat.canon.canonical_log_hash` (5 significant digits, 1e-6 floor), never a per-OS map; same-machine byte identity is tested separately.
10. v1 stays byte-reproducible (canonical pins unchanged) until the user approves retiring it; new physics lives behind `engine: "v2"`.

## Gate protocol
- One gate per session. Start with the gate skill (/gate N). Tests first. Stop at the end of the gate.
- Update GATES.md every gate. Tag `gate-N-pass` only when everything is green.
- Time-box exceeded or a test cannot pass: stop, report failure + 2 options with tradeoffs.
- The gate/verify/redteam skills live in `.zcode/skills/`; ZCode docs only guarantee user-level discovery (`~/.zcode/skills/`), so copy them there if they are not picked up.

## Style
Small diffs. No new dependencies without asking. Test names as in docs/MASTER_PROMPT.md 3.8. Files under ~300 lines.
