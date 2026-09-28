# CubeSat Swarm Self-Healing (Problem #b2ef60e9)

A 6-CubeSat formation flying under Hill–Clohessy–Wiltshire dynamics. Two satellites fail;
the swarm detects the failures, reassigns roles among survivors (Hungarian allocation),
and recovers mission coverage — measured against a no-recovery baseline.

**Status: Gate 0 (project skeleton).** All metrics: *unmeasured* — this README gets its
numbers from committed run logs at Gate 7, not before.

## Commands (target; scenarios arrive in G3/G4)

```
uv sync --frozen
uv run pytest
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
uv run uvicorn cubesat.api:app --port 8000
```

## Honesty section (expanded at G7 with measured values)

Simulation-only. Linearized HCW equations with a circular chief; no J2, drag, or attitude
dynamics; ideal comms and sensing; centralized replanner. Coverage is defined as the
fraction of a ground-target grid inside the union of healthy imagers' footprints
(definition finalized at G3). Results are not flight predictions.

- A dead satellite stays on a bounded relative orbit only in linear, unperturbed HCW;
  J2 and drag would make it drift. Nonlinear CW-vs-Kepler cross-check error: *unmeasured*
  (recorded at G1).
- The default `a_max` of 1e-2 m/s^2 assumes an ~8 kg CubeSat with ~150 mN of cold-gas
  thrust — an assumption, not a verified thruster specification.
