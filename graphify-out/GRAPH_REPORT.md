# Graph Report - Cubesat  (2026-09-29)

## Corpus Check
- Corpus is ~42,602 words - fits in a single context window. You may not need a graph.

## Summary
- 295 nodes · 588 edges · 12 communities (10 shown, 2 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 23 edges (avg confidence: 0.9)
- Token cost: 187,951 input · 0 output

## Community Hubs (Navigation)
- Role Allocation & Coverage
- HCW Orbital Dynamics
- Cluster Import (OMM)
- Scenario Schema & CLI
- Docs, Specs & Gate Protocol
- Fault Simulation Core
- HCW Verification Tests
- Scenario Zoo Tests
- Determinism & CLI Tests
- FastAPI Skeleton
- Replanning Concepts
- Project Root

## God Nodes (most connected - your core abstractions)
1. `run_scenario()` - 27 edges
2. `load_scenario()` - 23 edges
3. `propagate()` - 20 edges
4. `Scenario` - 18 edges
5. `replan()` - 13 edges
6. `chief_from_omm()` - 13 edges
7. `mean_motion()` - 12 edges
8. `PDController` - 11 edges
9. `test_coverage_monotonic_in_sats()` - 11 edges
10. `build_swarm_scenario()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `firefly_run()` --uses--> `Scenario`  [INFERRED]
  tests/test_cluster_import.py → cubesat/scenario.py
- `test_generated_scenario_passes_schema()` --uses--> `Scenario`  [INFERRED]
  tests/test_cluster_import.py → cubesat/scenario.py
- `_replan_inputs()` --calls--> `mean_motion()`  [EXTRACTED]
  tests/test_allocation.py → cubesat/hcw.py
- `test_coverage_monotonic_in_sats()` --calls--> `mean_motion()`  [EXTRACTED]
  tests/test_coverage.py → cubesat/hcw.py
- `centers_at()` --calls--> `propagate()`  [EXTRACTED]
  tests/test_coverage.py → cubesat/hcw.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Gate verification workflow (gate -> redteam/physics-reviewer -> verify -> ledger)** — _zcode_skills_gate_skmd_gate_skill, _zcode_skills_redteam_skmd_redteam_skill, _zcode_skills_verify_skmd_verify_skill, docs_physics_reviewer_physics_reviewer, gates_gate_ledger, agents_gate_protocol [EXTRACTED 0.95]
- **Self-healing recovery flow (detect -> replan -> reconfigure -> recover)** — docs_master_prompt_hcw_dynamics, docs_master_prompt_pd_control, docs_master_prompt_hungarian_allocation, docs_master_prompt_coverage_metric, docs_master_prompt_state_machine [EXTRACTED 0.95]
- **G5 streaming pipeline (sim core -> live/replay cursor -> WS wire -> React dashboard)** — docs_backend_spec_cursor_pipeline, docs_backend_spec_fastapi_backend, docs_frontend_spec_react_dashboard, docs_backend_spec_sim_core_frozen, docs_frontend_spec_replay_fallback [EXTRACTED 0.95]

## Communities (12 total, 2 thin omitted)

### Community 0 - "Role Allocation & Coverage"
Cohesion: 0.07
Nodes (60): build_cost_matrix(), _coverage_estimate(), FormationPlan, _min_separation_ok(), ndarray, Two-step allocation (docs/MASTER_PROMPT.md section 3.3, gate G4). Step 1 --…, A perfect matching must exist with every transfer's bang-bang delta-v estimate…, Time-averaged coverage of the imager seats' footprints over one orbit. (+52 more)

### Community 1 - "HCW Orbital Dynamics"
Cohesion: 0.09
Nodes (35): drift_free_state(), forcing_matrix(), propagate_controlled(), ndarray, Hill-Clohessy-Wiltshire linear relative motion (unforced chief, circular…, Propagate state0 for t [s] under CW dynamics with `accel` [m/s^2] held constant…, Slot at ellipse phase `phase_rad` on the COMMON passive relative orbit (radial…, 6x6 analytic CW state-transition matrix at time t [s], mean motion n [rad/s].… (+27 more)

### Community 2 - "Cluster Import (OMM)"
Cohesion: 0.10
Nodes (35): copy, build_swarm_scenario(), chief_from_omm(), _chief_raw(), load_omm_records(), main(), _num(), Path (+27 more)

### Community 3 - "Scenario Schema & CLI"
Cohesion: 0.10
Nodes (30): argparse, BaseModel, main(), parse_args(), CLI: run a scenario and write the versioned JSONL log (gate G3). I/O edge only:…, Allocation, ChiefOrbit, Detection (+22 more)

### Community 4 - "Docs, Specs & Gate Protocol"
Cohesion: 0.08
Nodes (30): CI workflow (uv sync, ruff, pytest), Gate skill (/gate N), Redteam skill (adversarial reviewer launcher), Verify skill (tests + determinism hash + number sourcing), Gate protocol (tests-first, one gate per session, GATES.md update), AGENTS.md repo invariants (determinism, SI, no fabricated numbers), ARCHITECTURE.md data flow (scenario -> sim -> JSONL -> API/UI), Golden SHA-256 determinism pin (tests/test_cli.py) (+22 more)

### Community 5 - "Fault Simulation Core"
Cohesion: 0.10
Nodes (28): mean_motion(), Mean motion n [rad/s] of a circular orbit at altitude_m above Earth., FailureMode, DEAD: no comms, no thrust, coasts ballistically. THRUSTER_OUT: reports, cannot…, Simulate the mission and return the JSONL lines: [INIT header, tick...,…, run_scenario(), StrEnum, MASTER_PROMPT 3.3: leader-failure scenario re-elects a leader -- after the… (+20 more)

### Community 6 - "HCW Verification Tests"
Cohesion: 0.15
Nodes (13): pytest, scipy_integrate, _cw_rhs(), _ode_propagate(), slow, HCW linear relative-motion tests (docs/MASTER_PROMPT.md sections 3.1 and 3.8,…, Nonlinear check (MASTER_PROMPT 3.1c): CW/STM vs independent two-body…, Unforced CW ODEs (MASTER_PROMPT 3.1): x''-3n^2*x-2n*y'=0, y''+2n*x'=0,… (+5 more)

### Community 7 - "Scenario Zoo Tests"
Cohesion: 0.19
Nodes (14): _events(), n4_lines(), n8_lines(), n8_scenario(), fixture, slow, Scenario-zoo structural tests: single-failure N=4 and cascading N=8 runs.…, AGENTS.md invariant 2: same scenario + seed => byte-identical log. Full double… (+6 more)

### Community 8 - "Determinism & CLI Tests"
Cohesion: 0.19
Nodes (10): CompletedProcess, hashlib, pathlib, subprocess, Path, nominal.json trimmed to a 600 s run (301 ticks at dt = 2 s): fast, still…, Two runs of a short nominal scenario produce byte-identical JSONL, matching the…, _run_cli() (+2 more)

### Community 9 - "FastAPI Skeleton"
Cohesion: 0.20
Nodes (6): health(), FastAPI app. G0 skeleton: /health only; /api, /ws and static UI arrive in G5., CubeSat swarm self-healing: HCW dynamics, PD control, reassignment, coverage…, fastapi, fastapi_testclient, get

## Knowledge Gaps
- **6 isolated node(s):** `cubesat-swarm`, `CI workflow (uv sync, ruff, pytest)`, `Redteam skill (adversarial reviewer launcher)`, `Gate protocol (tests-first, one gate per session, GATES.md update)`, `Mission state machine NOMINAL->FAILURE_DETECTED->REPLANNING->RECONFIGURING->RECOVERED` (+1 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 124 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_scenario()` connect `Fault Simulation Core` to `Role Allocation & Coverage`, `HCW Orbital Dynamics`, `Cluster Import (OMM)`, `Scenario Schema & CLI`, `Scenario Zoo Tests`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Why does `propagate()` connect `Role Allocation & Coverage` to `HCW Orbital Dynamics`, `Fault Simulation Core`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `PDController` connect `HCW Orbital Dynamics` to `Role Allocation & Coverage`, `Fault Simulation Core`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `run_scenario()` (e.g. with `FailureMode` and `Scenario`) actually correct?**
  _`run_scenario()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `Scenario` (e.g. with `build_slots()` and `run_scenario()`) actually correct?**
  _`Scenario` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `cubesat-swarm`, `CI workflow (uv sync, ruff, pytest)`, `Redteam skill (adversarial reviewer launcher)` to the rest of the system?**
  _6 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Role Allocation & Coverage` be split into smaller, more focused modules?**
  _Cohesion score 0.06538461538461539 - nodes in this community are weakly interconnected._