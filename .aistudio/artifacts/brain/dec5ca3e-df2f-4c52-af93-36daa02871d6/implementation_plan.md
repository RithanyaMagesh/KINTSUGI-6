# CubeSat Swarm Self-Healing Console — Round 4 Redesign & Dev Server Boot

A comprehensive redesign of the CubeSat swarm operations console that configures the root development server to boot cleanly on port 3000 (proxying REST and WebSocket traffic to the local FastAPI simulation engine), eliminates visual clutter, surfaces the self-healing narrative (`detect → replan → reconfigure → recover`) continuously in real time, unifies the Live operator workflow without tab-hunting, and brings full read-only telemetry and per-satellite inspection to Replay mode.

## User Review & Critical Decisions

> [!IMPORTANT]
> While Planning Mode is active, code modifications and server processes are paused until you approve the plan. Click **Proceed** to immediately boot the dev server on port 3000 and execute the Round 4 redesign.

- **Confirmed Decision 0 — Dev Server Boot & Port 3000 Proxy Orchestration**: Because the imported repository places the React app inside a subdirectory and the FastAPI backend on port 8000, the preview server cannot start until a root startup configuration launches both the Python FastAPI service (`cubesat.api:app` on port 8000) and the Vite frontend bound to `0.0.0.0:3000` (or serves the built bundle + API/WS directly on port 3000), while keeping all git-uncommitted work intact.
- **Confirmed Decision 1 — Unified Live Control Seat (`#/live`)**: Replace the fragmented 3-tab sidebar with a cohesive operator flow where Scenario Setup (with a quick-load preset selector) collapses cleanly once a run starts, keeping Live Failure Injection, AI Early Warning (display-only), and the step-by-step Recovery Story (`RecoveryLog`) simultaneously visible alongside the Fleet list.
- **Confirmed Decision 2 — Full Read-Only Telemetry & Satellite Inspection on Replay (`#/replay`)**: Mount the read-only telemetry readout rows, underline-tabbed charts, and Selected Satellite Inspector alongside the Replay 3D viewport and playback transport—with zero simulation or injection controls—so clicking any satellite during a replay displays its role semantics, LVLH kinematics, and dynamic task history.
- **Confirmed Decision 3 — Editable Scenario Presets in the Live Builder**: Allow operators to load any committed scenario (`two_failure`, `firefly_swarm`, `cascading_n8`, `leader_failure_6sat`, `single_failure_n4`, `nominal`) directly into the Live builder as an editable template—or run a committed scenario directly without re-uploading when unmodified—while enforcing pydantic schema bounds on all custom edits.
- **Confirmed Decision 4 — Strict Wire & Claims Honesty**: Never fabricate numbers or imply AI is in the live control loop. `replanning_latency_ms` renders `unmeasured`; AI risk (`sats[].risk`) is clearly labeled as an offline LightGBM display-only annotation (cut from the control loop by the pre-registered kill switch); `THRUSTER_OUT` is disclosed as heartbeat-invisible; and coverage captions state that Hungarian recovery protects worst-case pairs (+4.93 pts) rather than raising mean coverage (−2.13 pts).

---

## 1. Overview & Core Concept

- **What It Does**: Provides an industrial aerospace ground-segment console for operating, perturbing, and analyzing a self-healing CubeSat formation flying on linearized Hill–Clohessy–Wiltshire (HCW) orbital mechanics with Hungarian role reallocation and PD thrust control.
- **Target Audience / Persona**: Hackathon judges, technical evaluators, and mission operators who need to grasp the self-healing story in under 30 seconds, inspect quantitative telemetry proof, and test custom or preset failure scenarios live or via deterministic log replay.
- **Key Value**: Transforms the console from disconnected tabs into a self-explaining operational instrument where every failure, heartbeat timeout, Hungarian slot reassignment, propellant burn, and coverage recovery is narrated and quantified as it happens.

---

## 2. User Experience & Visual Design

- **Key User Flows**:
  1. **10-Second Orientation (`#/`)**: The Landing view presents the self-healing state machine (`NOMINAL → FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED`), contrasts **Live Control** (build, run, inject failures) against **Deterministic Replay** (watch committed canonical runs), highlights the measured benchmark truth, and links to `#/tutorial`, `#/faq`, and `#/docs`.
  2. **Live Control Seat (`#/live`)**:
     - The operator selects a committed scenario preset (e.g., *Two-failure recovery demo*, *Hypothetical swarm on FIREFLY-1's orbit*, *Cascading 8-sat failure*) to populate the builder or customizes satellite count (up to larger swarm sizes), per-seat roles, orbital/formation geometry, scheduled failures, recovery policy (`Hungarian`, `Even redistribution`, `Hungarian + keep-out`), and the **AI Risk Overlay** toggle.
     - Pressing **Run simulation** collapses the setup accordion into a compact active-mission summary bar (showing resolved Scenario, Seed, Recovery Policy, and AI Overlay status, plus an **Edit setup** toggle and **Pause / Resume / Reset** controls).
     - Below the active bar, **Live Failure Injection**, **Recovery Story (`RecoveryLog`)**, **AI Early Warning (`RiskPanel`)**, and the **Fleet List** remain visible without switching tabs.
  3. **Playback-Only Replay (`#/replay`)**:
     - Left gallery lists committed `.jsonl` runs with doc-verified labels.
     - Center stage houses the 3D Swarm View, plain-language `NarrationStrip`, `Timeline` state-machine spine, and single `ReplayControls` transport (play/pause/restart/seek/speed) above the `RecoveryLog`.
     - Right column provides the read-only Telemetry readout rows, 5 underline-tabbed charts, collapsible Role Reassignment table, and Selected Satellite Inspector.
  4. **Click-a-Satellite Inspection (Live & Replay)**: Clicking any satellite marker in the 3D scene or row in the Fleet list highlights the satellite and updates the Selected Satellite Inspector with its current role, plain-English role semantics, LVLH position/velocity, target slot distance, $\Delta v$ spent, rule-based suspect/offline AI risk annotation, and full chronological role/task history.

- **Visual Identity & Theme (`FRONTEND_SPEC` §13 Law)**:
  - *Aesthetic Direction*: Industrial ops console — Swiss typographic discipline with high-contrast engineering readouts, zero decorative chrome, and color reserved strictly for semantic state.
  - *Color Palette & Mood*: Neutral graphite surfaces (`--bg: #17191a`, `--panel: #1e2123`, `--panel-raised: #24272a`), crisp 1px borders (`--border: #31363a`, `--border-strong: #43494e`), high-contrast primary ink (`--ink: #e8eaec`, `--ink-muted: #9ba3a9`), and semantic state tokens only (`--status-nominal: #46c07a`, `--status-caution: #e0a526`, `--status-failed: #f25555`, `--status-info: #5b9bf0`, `--status-leader: #f2cc46`). Zero raw hex values outside `tokens.css`.
  - *Typography & Hierarchy*: Vendored `IBM Plex Sans` (400/500/600) for functional sentence-case labels, headings, and prose; vendored `IBM Plex Mono` (400/500) with `tabular-nums` for all telemetry values (28px+ primary readouts), timestamps, coordinates, and table numerals.
  - *Component Styling & Layout*: Flat 1px-bordered panels (`radius <= 8px`), ordinary product controls (`radius: 6px`), underline tab strips (no pill tabs or pill badges), readout rows instead of metric-card grids, and a single scroll container per side column with non-clipping inline/anchored tooltips.
- **Interactive Feedback & Motion**:
  - 150ms ease-out color/border/opacity transitions on interactive controls; 2px `--focus-ring` outline on `:focus-visible`; stable layout dimensions across loading, empty, active, and error states; full compliance with `prefers-reduced-motion: reduce`.

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 0 — Dual-Process Dev Server & Single-Port Preview Binding**:
  - *Chosen Approach*: Configure the environment so `uvicorn cubesat.api:app --port 8000` runs the authoritative Python simulation backend while the Vite frontend serves on `0.0.0.0:3000` (with `/ws`, `/health`, `/scenarios`, `/simulation`, `/failure`, and `/replay` proxied to `localhost:8000`), and build `frontend/dist` so FastAPI can also serve the static bundle directly.
  - *Why*: Ensures the preview iframe on port 3000 immediately connects to both the React UI and the live FastAPI WebSocket/REST endpoints without touching any frozen simulation core files.
- **Decision 1 — Unified HTTP Client & Explicit Per-Option 422 Degradation**:
  - *Chosen Approach*: Consolidate the three duplicated fetch/error-formatting implementations into a single typed client module that formats FastAPI string and array `detail` payloads uniformly, routes all simulation starts through one function supporting `{scenario, seed, speed, policy, predictor}`, and probes/retries gracefully if an older backend rejects `policy` or `predictor` with 422—reporting specifically which option was not accepted in a persistent status banner.
  - *Why*: Eliminates code duplication, removes the legacy start path that dropped speed/policy/predictor, and ensures operators never experience silent feature degradation.
- **Decision 2 — Always-Resolved Policy Readout**:
  - *Chosen Approach*: Because `sim_state` frames echo `policy` only when it deviates from `"hungarian"` and `hello` is emitted on initial WebSocket connect, store the confirmed policy returned/accepted at `/simulation/start` (and echoed on `hello` / frames) in `simStore`, while keeping `unmeasured` for replay logs that do not encode a policy field in their frames unless known.
  - *Why*: Fixes the bug where a live Hungarian run displayed `"unmeasured"` for Recovery Mode while remaining 100% faithful to Repo Invariant 1 on unknown replay logs.
- **Decision 3 — Preserving Long-Run Role & Task History Without Unbounded Growth**:
  - *Chosen Approach*: Filter `roleHistoryStore` ingestion so no-op reassignment rows (where a survivor keeps both its prior role and prior target slot) are not stored as redundant entries, and raise the per-satellite history cap to 250 meaningful state transitions with an explicit summary count if truncated.
  - *Why*: Prevents 30 Hz or multi-episode runs from silently dropping early failure/reassignment milestones while keeping memory bounded.
- **Decision 4 — Structural Readiness for the 9-Point Roadmap**:
  - *Chosen Approach*: Make recovery policy selection a primary control card with algorithm descriptions (ready for decentralized CBBA alongside Hungarian), generalize failure-mode rendering and status/event badges so future modes (battery/EPS degradation, comms loss, OBC fault, partial thruster, collision-avoidance evasion events) and larger swarms ($N = 20\text{–}50$ satellites) render cleanly without layout overflow, and display explicit *"not modeled on this backend"* / *"single-run telemetry (reference comparison requires multi-run wire support)"* disclosures rather than dead tabs.
  - *Why*: Prepares the UI for upcoming roadmap capabilities while maintaining strict scientific honesty today.

---

## 4. Technical Architecture & Data Strategy *(Technical Reference)*

- **Architecture & Component Diagram**:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                 Port 3000 Dev Server (Vite + FastAPI Port 8000)                  │
│  [ Wordmark (#/) ]   [ Live · Replay · Tutorial · FAQ · Docs ]   [ Sim Status ]  │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                          ▼
┌───────────────────────────┐ ┌──────────────────────┐ ┌───────────────────────────┐
│   #/live (Control Seat)   │ │ #/replay (Playback)  │ │ #/ · #/tutorial · #/faq   │
│ ┌───────────────────────┐ │ │ ┌──────────────────┐ │ │         #/docs            │
│ │ Collapsible Builder   │ │ │ │ Run Gallery      │ │ │ ┌───────────────────────┐ │
│ │ - Preset Template Load│ │ │ │ - two_failure    │ │ │ │ 10-Sec Mission Story  │ │
│ │ - Swarm & Roles (2..N)│ │ │ │ - firefly_swarm  │ │ │ │ State-Machine Diagram │ │
│ │ - Orbit & PD Physics  │ │ │ │ - nominal        │ │ │ │ Live vs Replay Guide  │ │
│ │ - Scheduled Failures  │ │ │ └──────────────────┘ │ │ │ Benchmark & AI Truth  │ │
│ │ - Policy & AI Overlay │ │ │ ┌──────────────────┐ │ │ │ Safe / Do-Not Claims  │ │
│ ├───────────────────────┤ │ │ │ 3D Swarm View    │ │ │ └───────────────────────┘ │
│ │ Active Run Bar        │ │ │ │ NarrationStrip   │ │ └───────────────────────────┘
│ │ - Pause/Resume/Reset  │ │ │ │ Timeline Spine   │ │
│ │ - Live Failure Inject │ │ │ │ ReplayControls   │ │
│ │ - AI Early Warning    │ │ │ │ RecoveryLog      │ │
│ │ - RecoveryLog (Why)   │ │ │ └──────────────────┘ │ │
│ │ - Fleet SatelliteList │ │ │ ┌──────────────────┐ │ │
│ └───────────────────────┘ │ │ │ Read-Only Right  │ │
│ ┌───────────────────────┐ │ │ │ Telemetry Panel  │ │
│ │ Center: 3D Swarm View │ │ │ │ + Selected Sat   │ │
│ │ + Narration + Spine   │ │ │ │   Inspector      │ │
│ └───────────────────────┘ │ │ └──────────────────┘ │ │
│ ┌───────────────────────┐ │ └──────────────────────┘
│ │ Right: Telemetry Rows │ │
│ │ + 5 Charts + RoleTbl  │ │
│ │ + Selected Sat Panel  │ │
│ └───────────────────────┘ │
└───────────────────────────┘
              ▲                          ▲
              └──────────────┬───────────┘
                             │
┌────────────────────────────┴─────────────────────────────────────────────────────┐
│                Shared Deserializer & Zustand Stores + Unified REST API           │
│  WS /ws/state ──► deserializeMessage ──► simStore · recoveryStore ·              │
│                                          roleHistoryStore · historyStore         │
│  REST /scenarios · /scenarios/upload · /simulation/* · /failure/inject · /replay │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- **Data Model & State**:
  - **`simStore`**: Holds live/replay mode, connection state, `simTime`, `missionState`, `scenario`, `seed`, `policy` (resolved from `hello`, `sim_state`, or confirmed live start), `satellites[]`, `metrics`, `events[]`, and `lastReassignment`.
  - **`recoveryStore`**: Tracks chronological failure episodes (`tFail`, `satId`, `mode`, `detectionLatencyS`, `vacatedSlot`, pre/post coverage), `assignments` (`prevSlot -> targetSlot` movers + `costTotal`), and state-machine `phases` (`tStart`, `tEnd`).
  - **`roleHistoryStore`**: Records per-satellite meaningful transitions (`failed`, `reassignment` where role or slot changed, `recovered`) up to 250 entries per satellite plus rule-based `suspects`.
  - **`historyStore`**: Samples telemetry at 2 Hz (`coverage`, `deviation`, `minSep`, `health`, per-sat `dv_used`) and records timeline event markers (`failure`, `replan`, `recovered`).
  - **`uiStore`**: Manages active hash route, 3D layer toggles (`showLabels`, `showTrails`, `showFormationLines`, `showTargetSlots`), `cameraMode`, `selectedSatelliteId`, and `presentationMode` (with dormant `missionBriefOpen` state cleaned up).

- **Interactive Component & State Mapping**:
  - **Preset Loader in `ScenarioBuilder`**: Selecting a committed scenario populates `nSats`, `roles`, `failures`, and `NumberValues` from the scenario definition (with `clampNumber` validation), or runs the committed file directly if unmodified; editing any field marks the draft custom and uploads via `POST /scenarios/upload` before calling `POST /simulation/start`.
  - **Per-Option 422 Fallback**: If `POST /simulation/start` returns HTTP 422 when `policy` and/or `predictor` are supplied, the client retries selectively to isolate whether `policy`, `predictor`, or both were rejected, starts the run, and displays a persistent banner naming the exact unsupported option(s).
  - **Recovery Narrative & Allocator WHY-Line**: Both `NarrationStrip` and `RecoveryLog` read `simStore.policy` (instead of a hardcoded string) alongside `recoveryStore` movers and `historyStore` $\Delta v$ deltas to explain *who* failed, *how fast* heartbeat timeout caught it, *which* survivors moved to *which* slots, *why* global Hungarian assignment moved multiple satellites, *how much* $\Delta v$ each mover burned, and *what* coverage was restored.
  - **RightPanel & Chart Honesty**: Compact 5-tab bar fits cleanly at 1920×1080 and 1280×800 without horizontal overflow; `ReadoutRow` tooltips stay within panel bounds without scroll clipping; `GroundCoverageChart` includes an explicit benchmark reference callout explaining why the single live wire curve is shown and summarizing the committed P0 benchmark comparison (worst-case protection +4.93 pts vs mean −2.13 pts).
  - **3D Scene (`SwarmScene`)**: Preserves constant-screen-size satellite markers, priority label decluttering with leader ticks, Earth-centered default framing, subtle ghost slots/trails, and raycast click selection (`selectSatellite`) across both `#/live` and `#/replay`, scaled cleanly to support larger swarms ($N \ge 20$).
