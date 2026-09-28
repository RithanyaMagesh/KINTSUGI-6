# CubeSat swarm self-healing (hackathon #b2ef60e9)
Submit Oct 1. Feature freeze Sep 30, 18:00 IST.
Full spec: docs/MASTER_PROMPT.md — read the relevant sections at gate start. State ledger: GATES.md
Frontend: docs/FRONTEND_SPEC.md (v2.0, React — supersedes the master prompt's frontend locked decision, user-approved; §13 design law is mandatory for all UI work and replaces the design skills if you don't have them).
Backend (G5): docs/BACKEND_SPEC.md (v1.0 — FastAPI + WS + replay architecture, wire contract, test plan, build order; the sim core G1–G4 is done and must not be modified by G5).

## Commands
- `uv sync --locked`
- `uv run ruff check .`
- `uv run pytest -q`                    (full suite)
- `uv run pytest -m "not slow" -x -q`   (fast loop)
- run:   `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl`   (two_failure.json lands at G4; only nominal.json exists today)
- serve: `uv run uvicorn cubesat.api:app --port 8000`

## Invariants (never violate)
1. No number in README, dashboard, or pitch without a committed log AND the command that produced it. Unmeasured = write "unmeasured".
2. Determinism: no wall-clock, no unseeded RNG, no set/dict-order dependence inside the sim. Same scenario + seed => byte-identical log.
3. Units: SI internally (m, s, rad, m/s^2). Convert only at the UI edge.
4. Frame: LVLH, x radial, y along-track, z cross-track.
5. Dead satellites coast ballistically (never freeze) and count as obstacles.
6. linear_sum_assignment: rows = survivors, cols = candidate slots. Break ties with an index epsilon.
7. Locked decisions (docs/MASTER_PROMPT.md section 2) change only with user approval, with evidence.
8. Research patches (docs/MASTER_PROMPT.md final section) override the master prompt where they conflict.

## Gate protocol
- One gate per session. Start with the gate skill (/gate N). Tests first. Stop at the end of the gate.
- Update GATES.md every gate. Tag `gate-N-pass` only when everything is green.
- Time-box exceeded or a test cannot pass: stop, report failure + 2 options with tradeoffs.
- The gate/verify/redteam skills live in `.zcode/skills/`; ZCode docs only guarantee user-level discovery (`~/.zcode/skills/`), so copy them there if they are not picked up.

## Style
Small diffs. No new dependencies without asking. Test names as in docs/MASTER_PROMPT.md 3.8. Files under ~300 lines.
