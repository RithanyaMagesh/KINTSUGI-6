# CubeSat Swarm Console — Adversarially Audited Redesign Plan

A full-scale redesign of the CubeSat Swarm Self-Healing Console that fixes the 3D Earth orbital geometry, separates **Live Simulation (`#/live`)** from **Scenario Replay (`#/replay`)**, eliminates all duplicate recovery panels, adds **Simplified vs. Advanced** workspace views and **Light vs. Dark** themes, and replaces the cluttered landing page with a clean product introduction.

---

## User Review & Critical Decisions (Adversarial Audit Findings)

> [!WARNING]
> **7 Concrete Mistakes & Contradictions Found Across Our Previous Pass, Prior Agent Work, and Project Specs**
> Per your request, I audited our previous draft, the prior agent's code (`Round 1–3`), `HANDOFF.md`, `FRONTEND_SPEC.md`, `FRONTEND_REDESIGN_PROMPT.md`, and the Python backend (`scenario.py`, `hcw.py`, `sim.py`). Even the project docs had contradictions that caused the bugs you saw:

1. **Contradiction in `HANDOFF.md` ("Earth restaged as the orbit center, projection-verified 14/14") vs. Reality ("Satellites sitting on top of Earth")**:
   - **What went wrong**: The previous agent wrote in `HANDOFF.md` that Earth was at the orbit center, but in code (`sceneEarth.ts`) actually placed Earth at `[0, -centerDist, 0]` *below* the origin while leaving all satellites clustered in raw LVLH coordinates around `[0, 0, 0]`. Their automated 2D camera projection test passed only because the camera aimed through `[0, 0, 0]` toward `[0, -centerDist, 0]`, visually stacking the satellites in a tiny flat circle on top of Earth's north pole! Worse, in our last turn we colored the continents yellow (`#d4a84b`) and added green nadir cones.
   - **Correction**: Restore a natural blue-ocean / green-continent shaded Earth centered at `[0, 0, 0]`, remove the yellow dots and green cones, and add a **[ Earth orbit view | Formation array view ]** toggle inside the 3D viewport:
     - **Earth orbit view (Default)**: Earth sits at `[0, 0, 0]` and the satellites are mapped around the **orbital ring encircling Earth**, visibly orbiting all the way around the planet as simulation time advances while preserving their relative formation spacing and slot transfers.
     - **Formation array view**: Zooms into the local 2:1 Clohessy–Wiltshire relative formation plane on a clean reference grid (with Earth hidden so it never sits underneath).

2. **Contradiction in `FRONTEND_REDESIGN_PROMPT.md` & `ScenarioBuilder` ("Live = Replay")**:
   - **What went wrong**: The previous agent put a `COMMITTED_PRESETS` dropdown at the top of `#/live` and initialized Live with `two_failure.json` (which has pre-scheduled failures at `t = 1200 s` and `t = 1500 s`). That turned Live into a scripted replay.
   - **Correction**: Remove all pre-made replay presets from `#/live`. Initialize `#/live` as a **100% unscripted custom sandbox (`failures: []`)** where the swarm flies nominal until the user clicks a satellite (in 3D or in the list) and clicks **Inject failure** live so the physics engine solves an unscripted recovery on the fly. All 6 pre-recorded scenarios belong exclusively on `#/replay`.

3. **False Assumption in Our Previous Plan ("Circle / Line / Triangle" Array Shapes)**:
   - **What went wrong**: Our previous draft proposed a `Circle / Line / Triangle` shape selector. Auditing `cubesat/scenario.py` and `cubesat/hcw.py` shows the backend `Formation` validator only accepts `n_slots` ($2\text{–}50$), `radial_amp_km` ($>0$), and `phase_offset_deg`—any custom shape string would fail validation with HTTP 422.
   - **Correction**: Expose the real orbital array controls supported by the physics engine: **Satellite count (`2–50`)**, **Formation radius (`km`)**, **Orbit altitude (`km`)**, **Phase offset (`deg`)**, **Satellite roles (`leader`, `imager`, `downlink`)**, and **Recovery algorithm (`Hungarian`, `Even split`, `Keep-out`)**.

4. **Contradiction in `FRONTEND_SPEC.md` §6 (Single-Density All-Panels Layout) vs. Clutter Prevention**:
   - **What went wrong**: `FRONTEND_SPEC.md` originally required showing all 6 readouts, 5 chart tabs, role table, recovery log, event log, risk panel, and bottom panel at once. In our last turn, we compounded this by adding a third recovery spine in the right panel while keeping `BottomPanel` and `RecoveryLog`.
   - **Correction (Superseding `FRONTEND_SPEC.md` §6)**: Remove `BottomPanel` and all duplicate recovery logs, and add a **`Simplified | Advanced`** view mode toggle in the top bar:
     - **Simplified View (Default)**: Clean, spacious, zero clutter—essential sandbox/playback controls on the left, 3D viewport + 1 compact recovery status bar in the center, and 3 core readouts + 1 coverage chart + compact selected-satellite summary on the right.
     - **Advanced View**: Unlocks full engineering parameters on the left, 3D layer toggles in the center, and all 6 readouts + **strictly tabbed** right-hand inspector panels (`Charts | Satellite detail | Role reassignment | Event log & AI risk`) so panels never stack or overflow.

5. **Contradiction in `FRONTEND_SPEC.md` §13.1 (Dark-Only Palette Lock) vs. Light & Dark Modes**:
   - **What went wrong**: `FRONTEND_SPEC.md` §13.1 locked the console to a dark-only palette, while Appendix B enforces an automated gate forbidding any hex color outside `tokens.css`.
   - **Correction (Superseding `FRONTEND_SPEC.md` §13.1 Dark-Only Lock)**: Add a **`Dark | Light`** theme toggle in the top bar backed by `:root` (dark) and `:root[data-theme="light"]` (light) inside `tokens.css`, and flush the Three.js color cache on toggle so both the UI and 3D canvas switch cleanly while still passing the Appendix B hex gate.

6. **Backend Semantic Trap on `THRUSTER_OUT` (`HANDOFF.md` §8 Mistake #6)**:
   - **What went wrong**: In the frozen Python sim core, a `THRUSTER_OUT` satellite keeps sending heartbeats, so the reactive detector **only triggers autonomous replanning on `DEAD` satellites**. If a user injects `THRUSTER_OUT` expecting autonomous recovery, nothing happens.
   - **Correction**: In **Simplified View**, the 1-click **Inject failure** button always injects `DEAD` so every live fault triggers autonomous detection (`4.0 s`), Hungarian slot reassignment, and PD reconfiguration. In **Advanced View**, users can choose `DEAD` or `THRUSTER_OUT` with a clear 1-line note explaining the heartbeat behavior.

7. **Design-Law Violation on Landing Page & ALL-CAPS Headers**:
   - **What went wrong**: The landing page was stuffed with an ugly schematic SVG and internal audit jargon (`+0.0235 pp`, enum chains), and our last turn introduced `ALL-CAPS` headers violating `FRONTEND_SPEC.md` §13.2.
   - **Correction**: Replace the landing page with a clean, normal aerospace product page (clear hero banner, concise explanation of Live vs. Replay, and direct action buttons), and enforce strict **Sentence case** across all UI labels.

---

## 1. Overview & Core Concept

- **What It Does**: An interactive orbital mission console for testing and inspecting autonomous self-healing in a CubeSat imaging constellation using linearized Hill–Clohessy–Wiltshire (HCW) orbital mechanics and Hungarian slot reallocation.
- **Target Audience**: Aerospace engineers, mission operators, and technical evaluators who need to immediately see the problem being solved (coverage loss when satellites fail in orbit, and autonomous formation reconfiguration to heal the gap) without wading through internal audit logs.
- **Key Value**:
  - **Live Sandbox (`#/live`)**: Prove the recovery algorithm works on unscripted, user-created constellations and live fault injections.
  - **Scenario Replay (`#/replay`)**: Inspect deterministic, pre-recorded benchmark missions with instant timeline scrubbing.

---

## 2. User Experience & Visual Design

### Key User Flows
1. **Product Landing Page (`#/`)**:
   - Opens with a clean hero banner: *"Autonomous Fault Recovery for CubeSat Swarms"*, a plain-English summary of how the constellation detects dead satellites and re-phases survivors to restore ground coverage, and two primary CTAs: **Open live sandbox (`#/live`)** and **Browse scenario replays (`#/replay`)**.
   - Below the hero, two clean side-by-side cards explain the difference between **Live simulation** (build your own swarm & inject faults live) and **Scenario replay** (watch pre-recorded canonical missions), followed by links to Tutorial, FAQ, and Documentation.
2. **Live Simulation Flow (`#/live`)**:
   - Starts in a clean, unscripted nominal state (`failures: []`).
   - In the **Left Panel**, the user chooses their satellite count ($N=2\dots 50$), orbit altitude (`km`), formation radius (`km`), and recovery policy (`Hungarian`, `Even split`, `Keep-out`), then clicks **Start live simulation**.
   - In the **Center 3D Viewport**, the user sees the satellites orbiting around a blue/green Earth (`Earth orbit view`) or switches to `Formation array view` to inspect the 2:1 relative ellipse.
   - At any moment, clicking a satellite (in 3D or in the left panel) and pressing **Inject failure** kills that satellite live (`POST /failure/inject`), triggering `FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED` on the single status spine below the canvas.
3. **Scenario Replay Flow (`#/replay`)**:
   - Strictly playback-only. The **Left Panel** shows the 6 pre-recorded scenarios (`two_failure`, `firefly_swarm`, `cascading_n8`, `leader_failure_6sat`, `single_failure_n4`, `nominal`), one playback transport bar (`Play / Pause / Restart`, speed selector, timeline scrubber), and the clickable satellite fleet list.

### Visual Identity & Theme
- **Aesthetic Direction**: Clean, high-precision aerospace operations console (nominal dark graphite `#0b0d10` and crisp daylight technical paper `#f4f6f9` in Light mode), where color is reserved strictly for semantic satellite state:
  - **Healthy / Nominal**: Emerald (`#2fbf71` dark / `#168045` light)
  - **Warning / Reconfiguring / Moving Slot**: Amber (`#e0a020` dark / `#b87800` light)
  - **Failed / Dead Satellite**: Crimson (`#e05252` dark / `#c82828` light)
  - **Selected / Active Target**: Sky Blue (`#5b9bf0` dark / `#1d64c8` light)
  - **3D Earth**: Deep ocean blue (`#0c2b3f`) with natural continental green (`#24523f`) and subtle atmospheric rim (`#5b9bf0`).
- **Typography & Hierarchy**: Vendored `IBM Plex Sans` for Sentence-case UI hierarchy and `IBM Plex Mono` (`tabular-nums`) for all orbital coordinates, timestamps, coverage percentages, and $\Delta v$ readouts.

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 1: Two-View 3D Camera (`Earth orbit view` vs. `Formation array view`)**
  - *Chosen Approach*: Provide a prominent segmented button at the top-left of the 3D canvas switching between **Earth orbit view** (Earth centered at `[0, 0, 0]` with satellites distributed around the orbital ring encircling Earth and advancing with orbital angular velocity) and **Formation array view** (close-up local LVLH 2:1 relative formation grid with Earth hidden).
  - *Why*: Raw LVLH offsets are only a few kilometers across compared to Earth's $6,371\text{ km}$ radius. Separating the global orbital ring view from the local formation array view lets the user see satellites truly orbiting around Earth *and* inspect exact slot-to-slot reconfiguration geometry without satellites ever looking like they sit "on top of" Earth.
- **Decision 2: `Simplified` vs. `Advanced` Workspace Modes**
  - *Chosen Approach*: Default to `Simplified` mode (showing only core setup/playback controls, the 3D viewport + 1 recovery timeline bar, 3 headline metrics, 1 coverage chart, and a compact selected-satellite card) while offering `Advanced` mode via a top-bar toggle (unlocking full orbital/PD/sensor inputs and a 4-tab right inspector).
  - *Why*: Eliminates visual clutter for first-time operators and demo viewers while preserving 100% of the deep engineering telemetry in non-stacking tabs.
- **Decision 3: Strict Separation of Live (`#/live`) and Replay (`#/replay`)**
  - *Chosen Approach*: Live has custom sandbox parameters + live fault injection (`failures: []` by default, zero pre-baked replay presets); Replay has the 6 pre-recorded scenario cards + seekable playback transport (zero builder inputs or fault buttons). Both pages reuse the shared `SwarmScene`, `Timeline`, `NarrationStrip`, and `RightPanel`.
  - *Why*: Gives each page an unmistakable product identity while reusing tested visualization and telemetry components.

---

## 4. Technical Architecture & Data Strategy

### Architecture & Component Diagram

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ TopStatusBar: Brand | Nav (Overview, Live, Replay, Docs) | State Badge                 │
│               [ Simplified | Advanced ] View Toggle   •   [ Dark | Light ] Theme       │
└───────────────┬────────────────────────────────────────┬───────────────────────────────┘
                │                                        │
                ▼                                        ▼
┌───────────────────────────────┐        ┌───────────────────────────────┐
│ #/live (Live Sandbox Page)    │        │ #/replay (Replay Page)        │
├───────────────────────────────┤        ├───────────────────────────────┤
│ Left Panel (Live Controls):   │        │ Left Panel (Replay Gallery):  │
│ • Custom Swarm Setup (N, alt, │        │ • 6 Committed Scenario Cards  │
│   radius, policy; +PD/FOV in  │        │ • Single Playback Transport   │
│   Advanced mode)              │        │   (Play/Pause/Seek/Speed)     │
│ • Live Fault Trigger (1-click │        │ • Fleet List (SAT-1..N)       │
│   DEAD in Simplified; mode    │        │   (No builder / no injection) │
│   picker in Advanced)         │        └───────────────┬───────────────┘
│ • Fleet List (SAT-1..N)       │                        │
└───────────────┬───────────────┘                        │
                └───────────────────┬────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Shared Center & Right Workspace (Reused across #/live and #/replay)                    │
├───────────────────────────────────────────┬────────────────────────────────────────────┤
│ CenterPanel (3D & Single Recovery Spine)  │ RightPanel (View-Aware Telemetry)          │
│ • SwarmScene (Three.js):                  │ • Simplified Mode:                         │
│   [ Earth orbit view | Formation array ]  │   - 3 Readouts (Coverage, Min sep, Sats)   │
│   - Global: Blue/green Earth at [0,0,0],  │   - Ground Coverage Chart                  │
│     satellites orbit around ring          │   - Compact Selected Satellite Summary     │
│   - Local: Close-up 2:1 LVLH grid         │ • Advanced Mode (Strictly Tabbed):         │
│ • Single NarrationStrip + Timeline Spine  │   - All 6 Readouts                         │
│   directly below canvas (No BottomPanel)  │   - Tabs: [Charts] [Satellite detail]      │
│                                           │     [Role reassignment] [Events & AI risk] │
└───────────────────────────────────────────┴────────────────────────────────────────────┘
```

### Interactive Component & State Mapping
- **Global UI Store (`uiStore`)**:
  - `viewMode: "simplified" | "advanced"` (defaults to `"simplified"`): controls panel density across `ScenarioBuilder`, `FailureInjectionPanel`, `CenterPanel`, and `RightPanel`.
  - `orbitViewMode: "global" | "local"` (defaults to `"global"`): switches `SwarmSceneController` between **Earth orbit view** (satellites orbiting around Earth's circumference at `[0, 0, 0]`) and **Formation array view** (local 2:1 CW relative coordinates around `[0, 0, 0]` with Earth hidden).
  - `theme: "dark" | "light"` (defaults to `"dark"`, persisted to `localStorage`): sets `document.documentElement.dataset.theme` and calls `clearColorCache()` in `sceneColors` so Three.js scene background, grid, and orbit lines re-read CSS variables immediately.
- **Unscripted Live Sandbox Flow**:
  - Editing satellite count ($N = 2\dots 50$) automatically resizes the `roles` array (`1 leader`, `1 downlink`, remaining `imager` seats) so `n_slots === roles.length` always holds.
  - Clicking **Start live simulation** posts the custom scenario (`failures: []`) to `POST /scenarios/upload` and starts the live session via `POST /simulation/start`.
  - Clicking any satellite in the 3D scene or fleet list selects it and pre-fills the live fault button; clicking **Inject failure** calls `POST /failure/inject` at the current simulation timestamp.
