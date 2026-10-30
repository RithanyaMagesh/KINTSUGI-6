"""Pytest arg-repair for the fast-test gate (loaded via pyproject addopts
``-p cubesat._pytest_gate_fix``).

The fast-test gate invokes the documented fast loop (AGENTS.md:18,
``uv run pytest -m "not slow" -x -q``) through a shell that can strip the
quoting, so pytest receives ``-m not`` plus a stray ``slow`` path argument and
dies with "ERROR: file or directory not found: slow" before collecting
anything. ``-m not`` alone is never a valid marker expression, so that exact
shape (``-m not`` immediately followed by a bare ``slow`` token) is
unambiguous: merge the stray token back into the marker value, restoring the
documented command's semantics. Registered via ``-p`` so the repair runs in
``pytest_load_initial_conftests`` -- before pytest validates collection args
(_pytest/main.py:1147) and evaluates marker expressions. Every well-formed
invocation is byte-for-byte untouched; no test behavior changes.
"""


def pytest_load_initial_conftests(early_config, args) -> None:
    i = 0
    while i < len(args) - 2:
        if args[i] == "-m" and args[i + 1] == "not" and args[i + 2] == "slow":
            args[i : i + 3] = ["-m", "not slow"]
        i += 1
