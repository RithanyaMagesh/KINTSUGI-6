# Track C implementation plan (superpowers: writing-plans format)

Spec: `docs/superpowers/specs/2026-11-01-track-c-comms-decentral-formations.md`. Branch `comms` (off `backend`). Commit prefix `v2: C<n> — <summary>`.

Each task follows the same loop: write a failing test, implement, run the gates (`uv run ruff check .`, `uv run python -m pytest -m "not slow" -q`), then STOP at the phase gate.

Golden pins: every phase re-runs `tests/test_cli.py`, `test_failure_modes.py` and `test_policy_selection.py`, plus every `tests/v2/*` hash test, unchanged.

**Coordination:** `backend` is being changed by another session (P5a/P5c merged; 5b ψ sweep and 5d certificate next). Touch `sim_v2.py`, `scenario_models.py`, `faults_v2.py` and `roles_v2.py` only in C2–C4. Rebase `comms` on `backend` before each of those phases, and never edit `frontend/`.

## C1 — pure modules (DONE)
- `cubesat/formations.py`, `cubesat/isl.py`, `cubesat/decentral.py`, `tests/test_comms_track.py` (33 tests).
- Gate: full fast suite green; ruff clean; no core file touched.

## C2 — laser links in EngineV2 (needs C1)
1. Test: scenario without `comms` → v2 golden hashes unchanged. Test: `comms.model="laser"` validates only with `engine: "v2"` (same pattern as v2-only failure modes in `scenario.py:110`).
2. Add `Comms` + `TerminalSpec` pydantic models to `scenario_models.py` (fields mirror `isl.Terminal`, all with defaults, assumptions noted in `description`).
3. `cubesat/comms_v2.py` (new, <300 lines): a `CommsState` holding links, timers and the last topology, with `step(pos_lvlh, radio_ok, alive, sun_lvlh, dt) -> (links, components, events)`. Topology replans only on death or link loss (`keep=` current LOCKED). Events: `LINK_LOCKED`, `LINK_LOST{reason}`, `PARTITION{components}`.
4. EngineV2: construct `CommsState` iff laser. In `step()` call it after positions are known, put `links` and `components` on the tick line (optional keys), and add `comms` to `snapshot()/restore()`.
5. Heartbeat over links: in `faults_v2`, `silent` becomes `not radio_ok or not reachable_from_any_component_member`. Simplest correct rule: a sat whose component contains no other alive sat is silent to the swarm. Test: kill the star hub → leaves declared silent by K ticks; ring → nobody spuriously declared.
6. Tests: link locks after `ceil(acquire_s/dt)` ticks in a 2-sat run; a dead partner drops the link the same tick; sun-in-cone drops the link (force the geometry with `initial_lvlh`); determinism (same scenario+seed → byte-identical log); snapshot/restore mid-acquisition replays identically.
7. Gate: commit `v2: C2 — laser crosslink model in EngineV2 (opt-in)`, STOP.

## C3 — formation shape field (needs C1; independent of C2)
1. Test: v1 and v2 golden pins unchanged with no `shape` key, and `shape: "cartwheel"` gives a byte-identical log.
2. `Formation.shape: Literal[...] = "cartwheel"` in `scenario_models.py`. `sim.build_slots` calls `formations.formation_slots(shape, ...)`. The v1 engine only accepts `cartwheel` (422 otherwise), because the allocator's ψ sweep assumes the cartwheel family (`allocate.py` step 1).
3. Scenarios `data/scenarios/formation_{pco,gco,helix,string}_6sat.json` (engine v2, no failures, 1 orbit), added to `tests/test_scenario_zoo.py`.
4. Analysis: `uv run python -m cubesat.benchmark --mode formations` writes `data/eval/formations_report.json` with per shape min separation, mean range, ring link margin, imaging coverage, and the Δv to switch shape (via `transfer.lp_transfer` from P5c), plus the command and sha256.
5. Gate, commit, STOP.

## C4 — decentralised authority (needs C2)
1. Test: `recovery.authority="decentral"` without `comms.model="laser"` fails validation (decentralising over ideal comms is meaningless and would be a misleading demo).
2. In EngineV2 recovery, on each topology or failure event run `decentral.auction(default_bids(degree, fuel_frac, ground_wait_s, radio_ok), links, alive)`:
   - `degree` comes from LOCKED links;
   - `fuel_frac` comes from the spacecraft model;
   - `ground_wait_s` comes from `ground.py`.
   The `leader` label leaves `roles_v2` assignment in this mode, while downlink and imagers still go through `assign_roles`.
3. Log per-sat `functions: []`, a `FUNCTION_HANDOFF{function, from, to}` event, `consensus_rounds`, and `split_brain: []`. A "rounds" figure is a count, not seconds. Seconds = rounds × one hop per tick (dt) is a stated assumption.
4. Tests: leader kill under a ring gives zero vacancy after the declaration tick plus consensus rounds; under a star it gives split-brain until the topology replans; a radio-dead sat never holds a function; determinism.
5. Gate, commit, STOP.

## C5 — pre-registered benchmark (needs C2–C4)
1. Write the hypotheses and the run matrix into GATES.md and commit BEFORE running.
2. Run `benchmark --mode comms` → `data/eval/comms_results.json` + manifest.
3. Report every cell, including any that contradict the story.

## C6 — wire (needs C2–C4), backend only
Add optional `wire.py` pass-through for `links`, `components`, `functions`, the `FUNCTION_HANDOFF` / `LINK_*` / `PARTITION` events with plain sentences, and `consensus_rounds`. Pin these in `tests/test_wire.py`. Then document them in `docs/frontend-requests.md` § Track C. Do not touch `frontend/`.

## Risks
- `faults_v2` detection change can shift v2 hashes. Keep the old path byte-identical when `comms` is absent, and test that first.
- With 2 terminals and n ≥ 7, greedy topology can make two rings. Measure the component count and do not assume a ring.
- Split-brain in a partition is real behaviour, not a bug. The UI must show it honestly.
