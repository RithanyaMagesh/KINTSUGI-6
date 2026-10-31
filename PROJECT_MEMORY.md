# PROJECT_MEMORY.md — agentic memory for KINTSUGI-6 (CubeSat swarm self-healing)

Built 2026-10-31, refreshed 2026-10-31 after v2 Phase 0 + audits, by reading AGENTS.md, README, GATES.md, docs/{ARCHITECTURE,HANDOFF,IMPLEMENTATION_NOTES,LIVE_IMPORT_DESIGN,...}, the source tree and git history (HEAD `c56f13b`, 2026-10-30).
**Master spec for the current work: `docs/superpowers/specs/KINTSUGI-6_v2_master_map.md`; order, merged problem map and decisions: `docs/superpowers/plans/2026-10-31-v2-plan.md`; physics tasks: `docs/superpowers/plans/2026-10-31-physics-v2-plan.md`; audits: `docs/audit/2026-10-31-{a,b,c}.md`.**
**Read this first, then the doc named in "Where to read deeper" for the area you touch. The tree beats every doc (including this one) — verify before relying.**
Repo root = `AVISHKHAR/backend/` (git remote `dptel22/Cubesat`, branch master). `AVISHKHAR/` itself holds only `.claude/`.

---

## 1. What it is
Deterministic simulator of a 6-CubeSat formation under linearized Hill–Clohessy–Wiltshire (HCW) dynamics. Satellites fail → heartbeat detector notices → Hungarian assignment re-seats survivors on a re-phased formation → PD controller (thrust-saturated) flies them there → coverage is scored against a no-recovery baseline. FastAPI streams it over WebSocket and replays committed JSONL logs; React + Three.js console is the operator UI. Product name in UI: **KINTSUGI-6**. Origin: hackathon #b2ef60e9 (submitted 2026-10-03); work continued after.

Honest headline results (all have commands in GATES.md): recovery buys **worst-case protection and determinism, not mean coverage** (15-pair benchmark mean gain −2.13 pts; worst pairs +4.93 pts; Monte Carlo 20 runs mean +4.886 pts on two_failure). Predictor (LightGBM) was **CUT** by its own pre-registered kill switch. a_max=0.1 m/s² in the demo exceeds cold-gas hardware class.

## 2. Invariants — never violate (AGENTS.md)
1. No number in README/UI/pitch without a committed log + producing command; else write **"unmeasured"**.
2. **Byte-determinism** in the sim: no wall clock, no unseeded RNG, no set/dict-order dependence. Same scenario+seed ⇒ identical JSONL. Golden SHA pins in `tests/test_cli.py` (canonical two_failure line-hash `450d5371…`; short nominal `c95f31b8…`). Writers must force LF newlines + `sort_keys`.
3. SI internally (m, s, rad, m/s²); convert only at the UI edge.
4. LVLH frame: x radial, y along-track, z cross-track; state `[x,y,z,vx,vy,vz]`.
5. Dead sats coast ballistically (never freeze) and remain obstacles.
6. `linear_sum_assignment`: rows = survivors, cols = candidate slots; index-epsilon tie-break (`_TIE_EPS=1e-9`).
7. Locked decisions (docs/MASTER_PROMPT.md §2) change only with user approval + evidence. Research patches override the master prompt.
8. Coverage metric is fixed by fiat — tune spacing/FOV, **never the metric**.
9. Style: small diffs, no new deps without asking, files ≲300 lines, tests first, one gate per session, update GATES.md, tag `gate-N-pass` only when green. **Agents don't commit unless asked; use explicit `git add` paths, never `-A`.**

## 3. Architecture map
```
scenario JSON → scenario.py (pydantic) → sim.run_scenario (pure; list[dict]) → run.py (JSONL, only writer)
                                                  │ hcw / pd / coverage / allocate
        replay.py (parse+bisect seek) ──┐         ▼
        session.LiveSource (1 recompute  ├─▶ session driver ─▶ wire.to_messages ─▶ Hub ─▶ WS /ws/state ─▶ React
        in asyncio.to_thread)  ─────────┘      (pacing only; ≤30 Hz; never drops events)
```
**Core (physics; changes need approval + GATES entry):** `cubesat/{hcw,pd,coverage,allocate,sim,scenario}.py`
- `hcw.py` analytic 6×6 STM, `propagate_controlled`, `slot_initial_state` (common passive 2:1 ellipse, along-track = 2× radial).
- `pd.py` PD on state error vs moving slot ref, ‖u‖≤a_max, `dv_used += ‖u‖dt`, bang-bang lower bound.
- `coverage.py` r_f=h·tan(FOV/2), grid ∩ union of healthy imagers' footprints.
- `allocate.py` step 1 formation sweep (amp×phase; feasible iff min_sep over 72 orbit samples incl. dead obstacles AND matching fits Δv budget; max coverage, first wins ties); step 2 cost = w1·dist + w2·dist/fuel + w3·role-mismatch → Hungarian; greedy fallback by toggle or 4096-cell cap (deterministic, never a timeout).
- `sim.py` fixed dt=2 s; states `NOMINAL→FAILURE_DETECTED→REPLANNING→RECONFIGURING→RECOVERED`; heartbeat K=3 missed ⇒ 4 s latency; failure modes **DEAD / THRUSTER_OUT (self-reports, latency 0) / EPS_DEGRADE (DEGRADED fade of `degrade_s`, then dies)**; bounded **evasive burn** (`safety.evasion_enabled`, 1000 m radius, default-inert on canonical runs); dormant **oracle hooks** (ORACLE_ALERT/ORACLE_SWAP, default-off, byte-inert); `reassign_on_degrade` opt-in (critical-seat swap when a leader/downlink starts degrading).
- Log schema v1: INIT header, tick lines (`sats[]`, `coverage`, `min_sep`, optional `event`), SUMMARY (`coverage_mean_last_orbit`). Event types: FAILURE_DETECTED, DEGRADE_START, STATE, ASSIGNMENT, EVASIVE_MANEUVER, ORACLE_SWAP.

**Web layer:** `api.py` (routes: /health, /scenarios, POST /scenarios/upload [422 invalid/409 collision, name sanitized], /replay/files, /replay/file/{f}, /simulation/{start,pause,resume,speed,reset}, /failure/inject, /replay/{load,pause,resume,seek,speed,stop}, WS /ws/state, static mount of `frontend/dist`) · `session.py` (Hub w/ per-client queue 128 drop-oldest sim_state; **policy seam**; predictor overlay) · `wire.py` (log line → `sim_state`/`event`/`role_reassignment`; `replanning_latency_ms` always null = "unmeasured"; policy echoed only when ≠ hungarian) · `replay.py` · `run.py` CLI.

**Seam pattern (key architectural idea):** recovery policies, predictor, benchmark variants enter by **rebinding `cubesat.sim.replan` at session/benchmark layer** (`session._install_seam/_restore_seam`, `benchmark_policies.py`) or wire passthrough — *no core diff*. `"hungarian"` is deliberately NOT in `_POLICY_REPLANNERS` so default runs stay byte-identical. Process-global ⇒ **one Session per process** is load-bearing.

**Hash pins:** `cubesat/canon.py canonical_log_hash` (5 significant digits + 1e-6 floor) is the ONLY golden-pin form; no per-OS maps (tests: test_cli, test_failure_modes, test_oracle_sweep_v3, test_policy_selection). Same-machine byte identity is tested separately.

**Analysis layer (pure, zero core diff):** `benchmark.py` (modes: 15-pair × 5-policy, pareto, keepout-report, cw-curve, monte-carlo) · `benchmark_policies.py` · `pareto.py` · `keepout.py` (must not import sim) · `cw_curve.py` · `dv_bound.py` (two-impulse CW Δv bounds) · `monte_carlo.py` (jitters scenario params from one PCG64 stream OUTSIDE the core — the sim consumes no RNG so seed sweeps alone are vacuous).

**Import layer:** `cluster_import.py` (CelesTrak OMM → *hypothetical* swarm on a real chief orbit; stdlib, no SGP4, eccentricity gate; FIREFLY demo) · `live_import.py` + `_live_network.py` (newer: GRACE-FO etc. ingestion, 2:1 formation fitting via Hungarian, SSRF-hardened client: host whitelist celestrak/space-track/n2yo, 5 MB cap, 30 s cumulative deadline, credential redaction, atomic TTL cache, protected-dir/file output confinement, `.meta.json` provenance sidecar).

**Predictor (display-only):** repo-root package `predictor/runtime.py` (NOT under cubesat/); frozen `models/predictor.txt` (sha `37900918…`, tau 0.02568, K_ALARM=3, STRIDE=10, L3600, 132 features); sealed pipeline `files/predictor_pipeline.py` (src sha `deefeae1…`, self-enforcing via `out2/test_manifest.json`); CI hash-checks, **never retrains**. Opt-in `predictor:true` → `sats[].risk` on the wire. Nothing in sim/allocation consumes risk (pinned: `tests/test_predictor_wire.py`).

**Frontend** (`frontend/`, React 18 + TS + Vite 7 + Zustand + Recharts + plain Three.js [no R3F] + CSS Modules, vendored IBM Plex): hash router `#/` landing (now a 3D "KINTSUGI-6" page: `components/landing/landingScene.ts`), `#/live` (control seat: ScenarioBuilder → upload → start), `#/replay` (playback only), `#/tutorial`, `#/faq`, `#/docs`. Data flow: `useWebSocket` → one `api/deserializer.ts` → stores (`simStore`, `recoveryStore`, `roleHistoryStore`, `historyStore`, `replayStore`, `sceneStore`, `uiStore`). 3D in `components/three/*` (Earth at ring center, constant-screen-size markers, label declutter). **Design law** FRONTEND_SPEC §13: raw hex ONLY in `styles/tokens.css` (grep gate), color = state only, no metric-card grids, `unmeasured` for missing numbers, avoid-ai-design scanner clean.

**Data:** `data/scenarios/` (nominal, two_failure, single_failure_n4, cascading_n8, leader_failure_6sat, thruster_leader_6sat, eps_{leader,imager,downlink}_6sat, proximity_stress, firefly_swarm, live_{2,6,8,12,16,24}sat) · `data/logs/` (canonical two_failure/nominal JSONL) · `data/eval/` (benchmark, pareto, keepout, cw_error, dv_lower_bounds, oracle_sweep v2/v3, monte_carlo + manifests) · `data/celestrak/` snapshots.

**Tests:** `tests/` (~30 files; 123 collected as of 2026-10-26, more since: test_live_import, test_failure_modes, test_collision_avoidance, test_oracle_sweep_v2/v3). Golden wire fixtures in `tests/fixtures/`.

## 4. Decision log (why things are the way they are)
| Decision | Why / evidence |
|---|---|
| Linear HCW, not high-fidelity (no J2/drag/poliastro) | Locked (MASTER_PROMPT §2). Analytic STM is exactly testable + determinism trivial. Cost: CW-vs-Kepler error 3.101 m (1 km ellipse) → **1578.5 m at 8 km formation scale** — carried as honesty number. |
| a_max = 0.1 in two_failure (default 1e-2) | At 1e-2 PD diverges on formation-scale transfers at all spacings 4–11 km (Coriolis barrier 2n·v_y ≤ a_max caps ~2 km). Formation re-tuned 11→8 km (gap +3.33→+4.93 pts, Δv 280→194 m/s). Fix = impulsive/MPC planner (future). Never claim cold-gas feasibility (~22× budget). |
| Two-step allocation (formation sweep then Hungarian) | Pure Hungarian on fixed slots can't restore coverage; sweep picks formation by measured coverage. |
| Hungarian mean −2.13 pts vs do-nothing | P0 benchmark overturned the demo story. Hungarian coverage is constant 0.26980 on all pairs. Claim worst-case protection + determinism only. |
| Pareto degenerate; keep-out policy CUT | Δv set by formation sweep not weights; keep-out never fired (clearance 1322.6 m); dead-sat drift enters 2 km sphere post-replan. Fix became the evasive-burn feature. |
| Predictor CUT from control loop | Pre-registered GO iff ≥0.5 pp critical-seat gain; measured +0.0235 pp and +191% Δv. Re-opening needs user approval + GATES entry + spec amendment BEFORE diff. Model facts: gradual-fault recall 31/31, sudden-death recall 6.25%, **comms holdout 0/15 (no generalization)** — never claim otherwise. |
| `reassign_on_degrade` shipped as opt-in field (oracle sweep v3: RECOMMENDED) | EPS fade window is itself the warning; no predictor needed; default False keeps canonical sha `450d5371…`. |
| Failure-semantics round (2026-10-26, Addendum v1.2) deliberately touched core | User-approved; every delta additive + default-inert; golden pins re-verified. So "core is untouchable" is **relaxed only with approval + pins re-verified**. |
| Live = one recompute in `to_thread`; replay = cursor over JSONL; same driver | Live ≡ replay by construction (`test_live_equals_replay_frames`); injection = recompute with byte-identical prefix (`test_inject_prefix_byte_identical`). |
| Monte Carlo jitters params outside core | Core uses no RNG; seed only labels the INIT header. |
| Live import is stdlib+SSRF-hardened, scenario is *hypothetical swarm on a real orbit* | No real cluster is HCW-tight; never say "recovering <real mission>". |
| Frontend rebuilt 3+ times; REPLAY playback-only, LIVE = control seat | User rejected v1 (cluttered, nothing explains, 3D blobs). |
| Vite 5→7 bump | Cleared 9 Dependabot alerts; Node ≥20.19/22.12. |
| Phase 0 (v2, commit 8f750ab): canonical hash sig=5 not 9; phase0-fixes' sim.py change reverted | 9 digits flipped the hash 20/20 under platform-scale noise (1,791/12,642 floats are rounding noise; dead sats at ~1.25e6 m); sig=5 flipped 0/20. The sim.py change differed only in hold `slot_index` numbering; dv_bound fixed instead. Cross-OS equality unverified until CI. |
| Roles on failed sats cleared in v2 only (`roles: []`, `role: "none"`, `original_role`) | Map Q5: v1 keeps labels (no golden churn); benchmark counts NOMINAL holders only. |
| Critical-role metrics are the headline (hungarian 15/15, do_nothing 6/15; mean vacancy 5.9 s vs 9,418 s) | Committed in benchmark_results.json via `critical_*` fields. Recovery is NOT a coverage win: gain negative on the 9 pairs containing sat 0 or 5 (−2.84..−10.14 pts), mean −2.13. |
| D1 sgp4 approved (add at start of L2) · D2 predictor retired after P4 measures the detector (hidden from UI now) · D3 v1 retired only after v2 passes C1–C5 · D4 graphify dropped | User decisions 2026-10-31. |

## 5. Do-NOT-claim list (each was measured wrong or doesn't exist)
"Overshoot-free" (4.99%) · runs on standard cold-gas hardware · AI in the live control loop · autonomous THRUSTER_OUT detection (older note; now self-reports — check sim.py) · recovery raises *average* coverage · full physics (J2/drag) · cloud-deployed (localhost; G6 todo) · decentralized consensus (centralized Hungarian) · predictor generalizes to unseen fault families.

## 6. Current state (2026-10-31, after v2 Phase 0 and the three audits)
- Branch `v2` (from origin/phase0-fixes f702c05): `8f750ab` Phase 0, `7e26315` docs/audits. Never merge to master without the user; push of branch `v2` is allowed, master never.
- Gates: full suite (incl. slow) 215 passed, ruff clean, frontend build ok at 8f750ab. G6 (deploy) and G7 todo.
- 15-pair benchmark (committed `data/eval/benchmark_results.json`): hungarian 0.2698 on all pairs, critical roles held 15/15 vs do_nothing 6/15, worst per-sat Δv 251.2 m/s, worst survivor-dead separation 1852.5 m (< 2 km floor).
- Audit headline problems (full lists in docs/audit): false on-screen claims (landing "75 runs / 5 policies", headline pair shown as swarm-wide, "oracle CUT"), unserialized live sessions (inject rewinds playback, abandoned runs keep burning CPU, live EPS injection shows no fade), Docker CMD/healthcheck broken, stale Pareto/dv_bound/keep-out artifacts, no strong baseline (zero-Δv role swap ties/beats hungarian on 6/15 pairs), Monte Carlo varies only pair (1,2).
- Order: Simplify → re-measure stale evidence → EngineV2 (physics 1.1–1.5) → streaming sessions → V1 → fuel → roles → ψ → LP/MPC → certificate+ladder → V2 → metrics → incidents → real-orbit live (adds sgp4) → perf → packs+pre-registered benchmark → deploy. Stop after each phase.
- Stale docs still in tree: ARCHITECTURE.md (2026-09-28), HANDOFF.md (2026-10-26), PHYSICS_ENGINE_EXPLAINED.md (c56f13b tree), JUDGE_PREP/FAQ/Docs page numbers (audit C claims table: 46 of 150 do not reproduce).
- Untracked scratch under data/scenarios (`live_*sat*.json`) come from UI uploads; do not commit.
- Env quirks: use `uv run python -m pytest` (CI uses it); `--basetemp=.pytest_tmp` pinned; Mimosa hook blocks variable-path `open()` writes; `brew install libomp` needed for LightGBM tests on macOS; Docker daemon not running here (image never built); `npm run dev|start` serves on port 3000.

## 7. Commands
```
uv sync --locked
uv run ruff check .
uv run python -m pytest -q                       # full (215 tests at 8f750ab)
uv run python -m pytest -q -m "not slow" -x      # fast
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
uv run uvicorn cubesat.api:app --port 8000       # UI + API + WS in one process
uv run python -m cubesat.benchmark --base data/scenarios/two_failure.json --mode monte-carlo --report data/eval/monte_carlo_results.json
cd frontend && npm run build                     # tsc + vite gate
grep -rnE '#[0-9a-fA-F]{3,8}' frontend/src | grep -v tokens.css   # must print nothing
```

## 8. How to build on this (decision guide)
1. **New recovery policy / allocator (e.g. CBBA)?** Add a function with `allocate.replan`'s exact signature + 6-tuple return in `benchmark_policies.py`; register in `session._POLICY_REPLANNERS` and the benchmark driver. No core diff. Honest comparison to a decentralized allocator needs a comms model (core diff, approval).
2. **New failure mode?** Core diff: `scenario.FailureMode`, `sim.py` semantics, `wire.py` status map, frontend colors/narration. Needs approval; default-inert; re-verify golden pins; add scenario + `tests/test_failure_modes.py` case.
3. **New analysis / sweep / Monte Carlo?** Analysis layer only; write machine-readable report with `command` + per-log sha256 + manifest; add GATES.md row quoting the report.
4. **New scenario?** JSON in `data/scenarios/` (`n_slots == len(roles)`, failure `sat_id < len(roles)`); add to `tests/test_scenario_zoo.py`; if it should replay, commit its log.
5. **Wire/UI field?** Backend: additive optional field in `wire.py` (BACKEND_SPEC App. B pattern); frontend: deserializer → store → display; no store = nobody sees it (past bug). Missing value ⇒ `unmeasured`.
6. **Frontend change?** Obey §13 + `docs/KINTSUGI-6_frontend_build_prompt.md` (reskin spec; no new deps; hex only in tokens.css; 1920/1366/390 widths); run build + hex grep + scanner.
7. **Scaling to >6 sats?** `n_sats=len(roles)` already; past the 4096-cell cap allocator silently goes greedy — measure before raising. `live_12sat.json` exists (untracked).
8. **Higher-fidelity dynamics (J2/drag)?** Locked decision; invalidates golden hashes and CW-vs-Kepler framing; user approval + evidence first.
9. **Deploy (G6)?** Dockerfile must COPY scenarios + canonical logs and (per spec) build frontend in a node stage; smoke previously 836 MB, `/health` 200.
10. **Any change:** keep determinism pins green; add the GATES.md entry; record new numbers only with their command.

## 9. Open warts / roadmap candidates
THRUSTER_OUT/predictor-era gaps mostly addressed by Addendum v1.2 — re-read sim.py before assuming · `replanning_latency_ms` always null · run_scenario 2.9–3.2 s vs ~2 s target · three duplicated fetch/error-format helpers in frontend (`backend.ts`, `scenarios.ts`, `runApi.ts`) · predictor/policy 422 fallback silently drops both · roleHistoryStore 50-entry cap · right-panel tab overflow at 1920 · full browser render pass owed · G6/G7 todo · Mimosa full audit owed.
Roadmap (HANDOFF §10): CBBA decentralized control · more realistic failures (battery/comm/OBC/partial thruster) · continuous collision avoidance (partly done: evasive burn) · swarm scaling study · comm-aware coordination · HIL seam · high-fidelity dynamics · autonomous mission replanning (oracle hooks are the designed entry).

## 10. Where to read deeper
| Need | File |
|---|---|
| Rules/invariants, gate protocol | `AGENTS.md`, `GATES.md` (ledger + every number's command) |
| Full spec + locked decisions + research patches | `docs/MASTER_PROMPT.md` |
| API/wire/session/replay law | `docs/BACKEND_SPEC.md` (v1.2 + Addendum) |
| UI law, §13 design, §15 types | `docs/FRONTEND_SPEC.md`, `docs/KINTSUGI-6_frontend_build_prompt.md`, `docs/FRONTEND_REDESIGN_PROMPT.md` |
| History, mistakes (22 listed), roadmap mapping | `docs/HANDOFF.md` |
| Per-gate build notes incl. oracle v3 + security round | `docs/IMPLEMENTATION_NOTES.md` |
| Measurement plan, claims policy | `docs/ENDGAME_PLAN.md`, `docs/AI_LAYER_PLAN.md` |
| Live import design/threat model | `docs/LIVE_IMPORT_DESIGN.md` |
| Predictor provenance + kill switch | `files/INTEGRATION_PROMPT.md`, `files/ORACLE_SWEEP.md`, `models/predictor_manifest.json` |
| Code graph (archived, stale 2026-09-29, do not rely) | `docs/archive/graphify-out/` |

*Maintenance rule: when a gate lands, a decision changes, or a number is re-measured, update §4, §6 and the date at the top of this file in the same change.*
