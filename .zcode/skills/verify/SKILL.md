---
name: verify
description: Full verification pass for the CubeSat project — tests, determinism hash, and number sourcing. Changes no code.
---
Full verification pass. Change no code.
1. `uv sync --locked && uv run ruff check . && uv run pytest -q` (include slow tests). Paste output tails.
2. Run the primary scenario twice with seed 42 and compare SHA-256 of the two logs. Paste both hashes.
3. Grep README.md, docs/, and static/ for numbers. For each, name the log + command that produced it. List any number with no source as UNSOURCED.
4. Report PASS/FAIL with a bullet list of problems. Nothing else.
