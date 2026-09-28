---
name: gate
description: Run one build gate (G0–G7) of the CubeSat swarm project with tests-first discipline, then stop. Use as /gate N.
---
Run gate $ARGUMENTS following AGENTS.md.

1. Read GATES.md and this gate's row in docs/MASTER_PROMPT.md section 6, plus the relevant domain brief in section 3.
2. State the hypotheses (what must be true) in at most 8 lines.
3. Write the tests FIRST. Show them. Confirm they fail for the right reason.
4. Implement the minimum code to pass.
5. Run `uv run ruff check . && uv run pytest -q`. Paste the real output tail, not a summary.
6. Update GATES.md: status, evidence, measured numbers WITH the command that produced each.
7. Commit `gate-$ARGUMENTS: <summary>`. Tag `gate-$ARGUMENTS-pass` only if all tests pass.
8. Report: `GATE $ARGUMENTS: PASS/FAIL | tests x/y | key numbers | risks found | next`. Then STOP. Do not start the next gate.

If the time-box is exceeded or a test cannot pass, stop and report: what failed, evidence, 2 options with tradeoffs. Do not silently simplify.
