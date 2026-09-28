# CubeSat Self-Healing Swarm — Frontend Specification

**Project:** CubeSat Swarm Self-Healing Formation Control After Partial Failure  
**Document Type:** Frontend Requirements, Feature Specification, and Adversarial Review  
**Version:** 2.0 (repo-aligned, design law added — changelog in Appendix A)  
**Status:** Approved — build against this  
**Primary Audience:** Frontend developers, backend developers, demo presenter, judges  
**Primary Goal:** Build a professional, reliable, visually clear React frontend that proves the swarm can detect failure, reallocate roles, and recover mission performance.

> **Authority.** This document is the single source of truth for all frontend work. It supersedes the
> master prompt's locked decision "Frontend: Plain Three.js, single page, vendored locally" and the
> §8 anti-goal "no React" — **for the frontend only** — by explicit user approval on 2026-09-28,
> recorded in the `GATES.md` decisions log. Everything else in `docs/MASTER_PROMPT.md` (physics,
> gates, determinism, no-fabricated-numbers, deploy shape) still applies unchanged.
>
> **If you are implementing this without the superdesign / frontend-design / avoid-ai-design skills
> installed: that is fine and expected.** Section 13 embeds the complete design law — direction,
> tokens, banned patterns, review checklist, and the scanner gate. Follow §13 exactly; it replaces
> those skills.
>
> **Reading order for the implementing agent:** this header → §13 (design law) → §7 (must-haves) →
> §5 (locked stack) → the rest.

---

## 1. Executive Summary

The frontend is not just a visualization layer. It is the main proof-of-concept interface for the hackathon demo.

The system must show, in a clear and professional way:

1. A healthy CubeSat swarm maintaining a formation.
2. A failure event affecting one or more satellites.
3. The system detecting the failure.
4. The swarm autonomously reallocating roles.
5. The remaining satellites moving into a new stable formation.
6. Mission metrics dropping after failure and recovering after replanning.

The frontend must be:

- **Fast**: maintain at least 30 FPS, ideally 60 FPS.
- **Clear**: judges must understand the system within seconds.
- **Robust**: if live simulation fails, replay mode must work immediately.
- **Professional**: clean mission-control UI, readable fonts, no visual clutter.
- **Demo-friendly**: optimized for a 3-minute live presentation.

---

## 2. Product Vision

Build a React-based mission-control dashboard with a 3D swarm visualization, telemetry panels, failure/recovery indicators, and a replay fallback system.

The frontend should feel like a lightweight aerospace operations console:

- Dark theme
- High-contrast telemetry
- Clear mission state
- Real-time 3D swarm view
- Charts proving recovery
- Event log explaining what happened
- Replay mode for emergency fallback

The most important product statement is:

> The frontend must make the self-healing behavior obvious, credible, and visually measurable.

---

## 3. Primary Users and Their Needs

The “impacted users” are not normal consumers. They are hackathon stakeholders.

### 3.1 Judges

Judges need to understand the project quickly.

They want:

- Clear visual evidence of failure.
- Clear visual evidence of recovery.
- Quantitative proof that mission performance improves after replanning.
- A professional interface that looks credible.
- Large readable text.
- No confusing or overly technical clutter.

### 3.2 Presenter

The presenter needs control and reliability.

They want:

- Big, obvious buttons.
- A guided demo flow.
- A fallback replay mode.
- No accidental clicks.
- A clean presentation mode.
- A system that recovers quickly if the backend fails.

### 3.3 Technical Evaluators

Technical judges or teammates want evidence of engineering quality.

They want:

- Clear separation between live mode and replay mode.
- Reproducible scenario selection.
- Event logs.
- Replanning latency.
- Role reallocation details.
- Cost matrix or assignment table if possible.
- Deterministic behavior.

### 3.4 Frontend and Backend Developers

Developers need a maintainable structure during the hackathon.

They want:

- Clear component structure.
- Clear WebSocket message contract.
- Simple state management.
- Easy fallback mode.
- Low risk of performance problems.
- Minimal unnecessary dependencies.

---

## 4. Core Demo Narrative

The frontend must support this story:

> All numbers in the narrative examples below (coverage percentages, timestamps, latencies) are
> **illustrative mock data for design only**. Repo invariant #1: no number may appear in the running
> UI, README, or pitch unless it comes from a committed run log — until then the UI renders
> `unmeasured`.

### Act 1 — Nominal Operation

The swarm is healthy.

UI shows:

```txt
MISSION STATE: NOMINAL
Coverage: 95%
Formation Error: Low
All satellites healthy
```

### Act 2 — Failure Injection

A satellite fails.

UI shows:

```txt
MISSION STATE: FAILURE DETECTED
SAT-3 failed
Coverage drops
Event log updates
Failed satellite turns red
```

### Act 3 — Self-Healing

The system replans.

UI shows:

```txt
MISSION STATE: REALLOCATING
New roles assigned
New formation targets shown
Remaining satellites begin moving
```

### Act 4 — Recovery

The swarm stabilizes.

UI shows:

```txt
MISSION STATE: RECOVERED
Coverage recovers above acceptable threshold
Formation error decreases
Replanning latency displayed
```

This narrative must be visible without explanation.

---

## 5. Recommended Technology Stack

The stack below is **locked** (user-approved, 2026-09-28). The repo rule "no new dependencies without asking" applies: nothing beyond this table without user sign-off. Where v1 offered alternatives, this version decides — ambiguity is how the AI-default look sneaks in.

### Locked Stack

| Layer | Technology | Decision + reason |
|---|---|---|
| Framework | React 18 + TypeScript | User-approved change from the master prompt's plain-Three.js line |
| Build Tool | Vite | Fast dev, simple static production build |
| 3D Rendering | **Plain Three.js inside one React component** (imperative, `useEffect`-managed) | Decided: NOT React Three Fiber. The 3D module is isolated so it can be rewritten without touching dashboard code. React never re-renders the scene per frame — positions update through refs/mutable objects |
| UI Styling | **CSS Modules + one `tokens.css`** | Decided: NOT Tailwind. Tailwind's default palette and class reflexes are the single biggest source of the AI-generated look (§13). Raw tokens give full control and add zero dependencies |
| State Management | Zustand | Lightweight, per-subscription updates suit real-time telemetry |
| Charts | Recharts | One choice, no alternates. Styled per §13.4 — strip the default palette and gradient fills |
| Real-Time Communication | WebSocket (JSON) + 30 s client ping | The ping is mandatory: Render's free tier spins down without incoming client messages (master prompt research patch #3) |
| Fallback Data | Committed JSONL run logs (`data/logs/*.jsonl`) | The sim's own log files — one schema, one serializer (§18) |
| Fonts | IBM Plex Sans + IBM Plex Mono, **vendored woff2** | §13.2. No CDN, no Google Fonts link at demo time |
| Testing | Manual demo checklist + minimal unit tests | Hackathon-appropriate; replay parsing gets a unit test |

### Vendoring rule (demo-hard)

Everything must work with the network cable pulled: fonts, Three.js, the chart library, and the built JS/CSS are bundled by Vite and served by the one FastAPI service as static files (build output in `frontend/dist`, mounted by `cubesat.api`; the static replay mirror is the same build plus committed JSONL logs). Loading anything from a CDN at the venue is a hard failure — this is also a locked master-prompt decision, unchanged by the React approval.

---

## 6. Frontend Operating Modes

The frontend must support three primary modes.

### 6.1 Live Mode

The frontend connects to the FastAPI backend using WebSocket.

Used for:

- Real-time simulation
- Failure injection
- Live telemetry
- Live replanning visualization

Live mode requirements:

- Show connection status.
- Handle disconnect gracefully.
- Show “Waiting for simulation data” if no message received.
- Do not crash if backend is slow.
- Automatically attempt reconnection.

### 6.2 Replay Mode

The frontend loads a recorded simulation file.

Example file:

```txt
data/logs/two_failure.jsonl
```

produced by the repo's own run command:

```txt
uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
```

Replay consumes the same JSONL files the simulator writes — the frontend must not define a second format (§18).

Used for:

- Emergency fallback
- Deterministic demo
- Testing reproducibility
- Presenter safety

Replay mode requirements:

- Play
- Pause
- Restart
- Seek timeline
- Speed control
- Show replay badge
- Show current simulation time
- Preserve same UI as live mode

### 6.3 Presentation Mode

A simplified UI for the live pitch.

Visible elements:

- 3D view
- Mission state banner
- Ground coverage chart
- Event banner
- Start failure button
- Replay fallback button

Hidden elements:

- Debug info
- Advanced developer controls
- Extra charts
- Backend logs

---

## 7. Must-Have Functional Requirements

These are mandatory.

### 7.1 Simulation Control Panel

The frontend must allow the user to:

- Select a scenario file.
- Start simulation.
- Pause simulation.
- Resume simulation.
- Reset simulation.
- Inject a failure manually.
- Switch to replay mode.

Scenarios come from `data/scenarios/*.json` — the dropdown lists whatever files exist there, never a hardcoded list. The master prompt §4 defines:

```txt
nominal.json                  healthy 6-sat baseline              (exists)
one_failure.json              single failure                       (lands with G4)
two_failure.json              PRIMARY demo scenario                (lands with G4)
critical_role_failure.json    leader dies + one more               (G4, optional)
timeout_fallback.json         forces greedy-assignment fallback    (G4, optional)
```

Controls:

```txt
Scenario: [one_failure.json]
Seed: [42]
Speed: [1x]

[Start]
[Pause]
[Reset]
[Inject Failure]
[Replay From Log]
```

### 7.2 3D Swarm Visualization

The frontend must display:

- At least 3 CubeSats, ideally 4 to 6.
- Satellite positions in 3D.
- Satellite labels.
- Formation lines.
- Target formation slots.
- Satellite status colors.
- Failed satellite highlight.
- Reconfiguration movement.
- Camera controls.

Required satellite states:

| State | Color | Meaning |
|---|---:|---|
| Healthy | Green | Satellite is active |
| Reconfiguring | Amber / Yellow | Satellite is moving to new assigned slot |
| Failed | Red | Satellite has failed |
| Recovered | Blue / Green | Satellite is stable after replanning |
| Unassigned | Grey | No role currently assigned |
| Leader | Gold outline or badge | Special role |

Colors are the §13.1 status tokens — color carries state meaning only, never decoration. Every state also renders its text label (colorblind rule, §22):

```txt
Healthy        --status-nominal (green)         label "NOMINAL"
Reconfiguring  --status-caution (amber)         label "RECONFIGURING"
Failed         --status-failed  (red)           label "FAILED"
Recovered      --status-info    (blue)          label "RECOVERED"
Unassigned     --ink-faint      (grey)          label "UNASSIGNED"
Leader         --status-leader  (gold outline)  label "LEADER"
```

### 7.3 Failure Visualization

When a failure occurs, the frontend must make it obvious.

Required behavior:

- Failed satellite turns red.
- Failed satellite label changes to `FAILED`.
- Formation lines connected to failed satellite fade or turn red.
- Warning banner appears.
- Event log updates.
- Mission state changes to `FAILURE DETECTED`.
- Coverage chart begins to drop.
- Optional camera focus on failed satellite.

Example banner:

```txt
SAT-3 FAILURE DETECTED
```

### 7.4 Self-Healing Visualization

The frontend must show the recovery process.

Required behavior:

- Show replanning banner.
- Show new role assignments.
- Show new target slots.
- Show healthy satellites moving toward new slots.
- Show formation deviation decreasing.
- Show coverage recovering.
- Show final recovered state.

Example banner sequence:

```txt
FAILURE DETECTED
REPLANNING
RECONFIGURING
RECOVERED
```

### 7.5 Telemetry Dashboard

The dashboard must display mission-critical metrics.

Required metrics (rendered as readout rows per §13.3 — no metric-card grid):

| Metric | Source | Purpose |
|---|---|---|
| Ground coverage — 3 curves | `coverage` in the log | Primary mission metric. Master prompt §3.4 requires three curves: **nominal reference** (committed nominal run), **failed-no-recovery**, **failed-with-recovery**. The headline is recovery vs no-recovery, never an absolute number |
| Formation deviation | derived from `r` vs slot references | Closeness to target formation |
| Minimum inter-satellite distance | `min_sep` | Safety/collision metric |
| Δv used per satellite | `dv_used` | Thrust budget consumed (a fuel % may be derived for display) |
| Detection latency | `t_detect − t_fail` from failure events | Master-prompt-required; shown on the timeline at the failure tick |
| Replanning latency | replan events | Shows responsiveness |
| Active / failed satellite count | `sats[].status` | System degradation |
| Mission health score | derived: 0.5·coverage + 0.3·formation_quality + 0.2·safety (§8.7) | Judge-friendly single number — computed only from measured inputs |

Required charts:

1. Ground coverage over time — **the money chart**, the 3-curve chart above. Distinguish curves by line style (solid / dashed / dotted) AND color, with direct end-of-line labels instead of a legend chip row; event markers at failure/replan/recovery.
2. Formation deviation over time.
3. Minimum inter-satellite distance over time, with the safety threshold drawn as a labeled line.
4. Δv used per satellite (per-sat stepped lines or bars).
5. Mission health score over time.

The most important chart is:

```txt
Ground Coverage Over Time
```

It must show:

- High stable value before failure.
- Sharp drop after failure.
- Recovery after replanning.

### 7.6 Event Log

The frontend must show a chronological event log.

Example:

```txt
00:00.0  Simulation started
00:02.1  Nominal formation achieved
02:00.0  SAT-3 failure injected
02:00.1  Failure detected
02:00.3  Replanning started
02:00.7  New role assignment computed
02:01.2  Reconfiguration started
02:08.0  Formation recovered
```

Event severity colors:

| Severity | Color |
|---|---:|
| Info | Grey / Blue |
| Success | Green |
| Warning | Amber |
| Critical | Red |

### 7.7 Satellite Detail Panel

When a satellite is selected, the frontend should show:

- Satellite ID
- Role
- Status
- Position (LVLH `r`: x radial, y along-track, z cross-track)
- Velocity
- Δv used (`dv_used`)
- Assigned target slot
- Distance to target
- Failure type, if failed

Example:

```txt
SAT-3
Status: FAILED
Failure Type: Propulsion Loss
Previous Role: sensor_3
Position: [12.2, -4.5, 3.1]
Velocity: [0.0, 0.0, 0.0]
Δv used: 4.3 m/s
```

### 7.8 Replay Mode

Replay mode is mandatory.

The frontend must be able to:

- Load a pre-recorded simulation log.
- Play the log.
- Pause the log.
- Seek through time.
- Change playback speed.
- Show replay mode clearly.
- Use the same visualization components as live mode.

Replay controls:

```txt
[Play]
[Pause]
[Restart]
Speed: [1x]
Time: 00:02:15
----------------|----------------
Nominal        Failure       Recovered
```

### 7.9 Connection and Health Indicators

The frontend must show:

```txt
LIVE MODE
CONNECTED
```

or

```txt
REPLAY MODE
```

or

```txt
DISCONNECTED
```

If disconnected:

- Show warning.
- Do not freeze the entire UI.
- Offer replay mode immediately.

---

## 8. Should-Have Features

These are strongly recommended if the core system is stable.

### 8.1 Role Reallocation Table

Show how roles changed after failure.

Example:

| Satellite | Old Role | New Role | Cost | Distance | Fuel |
|---|---|---|---:|---:|---:|
| SAT-1 | leader | leader | 0.1 | 2.1 m | 88% |
| SAT-2 | sensor_1 | sensor_3 | 1.4 | 15.3 m | 76% |
| SAT-4 | sensor_2 | sensor_1 | 0.8 | 9.2 m | 81% |
| SAT-5 | backup | sensor_2 | 1.1 | 12.7 m | 94% |

This helps technical judges understand the reallocation logic.

### 8.2 Cost Matrix Viewer

Optional but highly impressive.

Show the assignment cost matrix used by the Hungarian algorithm.

Example:

|  | Role A | Role B | Role C | Role D |
|---|---:|---:|---:|---:|
| SAT-1 | 0.2 | 1.4 | 2.2 | 3.1 |
| SAT-2 | 1.1 | 0.6 | 1.9 | 2.4 |
| SAT-4 | 2.0 | 1.5 | 0.7 | 1.2 |
| SAT-5 | 1.7 | 2.1 | 1.1 | 0.5 |

Highlight selected assignments.

This is useful because the revised plan recommends a centralized Hungarian algorithm instead of CBBA.

### 8.3 Target Formation Ghost Slots

Display transparent markers where satellites should move.

Visual behavior:

- Old target slots appear faded.
- New target slots appear brighter.
- Slot labels show role names.
- Lines connect assigned satellites to target slots during reconfiguration.

### 8.4 Trails

Show short motion trails behind satellites.

Rules:

- Keep trails short.
- Limit trail history to avoid performance issues.
- Use different colors for different satellite states.
- Failed satellites should have no active trail or a frozen red trail.

Recommended trail length:

```txt
Max trail points: 150 to 250
Update rate: 5Hz to 10Hz
Opacity: 0.25 to 0.45
```

### 8.5 Inter-Satellite Distance Lines

Draw lines between satellites.

Color rules:

| Distance | Color | Meaning |
|---|---:|---|
| Safe | Green | Distance above safety threshold |
| Warning | Amber | Distance approaching limit |
| Danger | Red | Distance below safety threshold |

Example thresholds:

```txt
Safe: > 25 m
Warning: 10 m to 25 m
Danger: < 10 m
```

These thresholds should be configurable.

### 8.6 Ground Coverage Minimap

A simple 2D top-down view can help judges understand coverage.

Show:

- Satellite projections.
- Coverage polygon.
- Failed satellites.
- Target slots.
- Coverage percentage.

### 8.7 Mission Health Score

Create a single combined metric for judges.

Example:

```txt
Mission Health =
  0.5 * ground_coverage
+ 0.3 * formation_quality
+ 0.2 * safety_score
```

Display:

```txt
Mission Health: 86 / 100
```

Color coding:

| Score | Color |
|---|---:|
| 80 to 100 | Green |
| 60 to 79 | Yellow |
| 40 to 59 | Orange |
| 0 to 39 | Red |

### 8.8 Camera Focus Buttons

Recommended camera controls:

```txt
[Reset Camera]
[Top View]
[Formation View]
[Focus Failed Satellite]
[Follow Selected Satellite]
```

### 8.9 Before / After Comparison Panel

Show metrics before failure and after recovery.

Example:

```txt
Before Failure
Coverage: 95%
Formation Error: 1.2 m
Active Satellites: 6

After Failure
Coverage: 61%
Formation Error: 14.8 m
Active Satellites: 5

After Recovery
Coverage: 84%
Formation Error: 2.7 m
Active Satellites: 5
```

This is very powerful for judges.

---

## 9. Nice-to-Have Features

Only implement these after all must-have and should-have features are stable.

### 9.1 Glow and Bloom

Use subtle glow for:

- Healthy satellites
- Failed satellite pulse
- Target slots

Do not overuse bloom.

### 9.2 Particle Effects

Small failure effects are acceptable:

- Red pulse
- Expanding ring
- Small spark burst

Avoid:

- Large explosions
- Heavy particle systems
- Long cinematic animations

### 9.3 Sound Effects

Optional and muted by default.

Possible sounds:

- Failure alert
- Replanning complete
- Recovery complete

Default setting:

```txt
Sound: OFF
```

### 9.4 Communication Graph

Show communication links between satellites.

Useful for communication loss scenarios.

Visual rules:

- Active link: cyan/green line
- Lost link: red dashed line
- Failed satellite: disconnected links fade

### 9.5 Fuel Bars Above Satellites

Small floating fuel indicators:

```txt
High fuel: green
Medium fuel: amber
Low fuel: red
```

### 9.6 Debug Mode

Hidden developer panel showing:

- WebSocket status
- Last message timestamp
- Messages per second
- Frame rate
- Frame time
- Current scenario
- Current seed
- Replay file name
- Backend health

This should not be visible in presentation mode.

---

## 10. Full Feature List

### 10.1 Core Features

- [ ] React frontend with Vite
- [ ] TypeScript support
- [ ] Dark mission-control theme
- [ ] Top status bar
- [ ] Scenario selector
- [ ] Start / Pause / Reset controls
- [ ] Inject failure button
- [ ] Live WebSocket mode
- [ ] Replay mode
- [ ] 3D swarm view
- [ ] Satellite labels
- [ ] Satellite status colors
- [ ] Formation lines
- [ ] Target formation slots
- [ ] Failure highlight
- [ ] Replanning banner
- [ ] Recovery banner
- [ ] Event log
- [ ] Ground coverage chart
- [ ] Formation deviation chart
- [ ] Inter-satellite distance chart
- [ ] Satellite list
- [ ] Selected satellite panel
- [ ] Replay fallback button
- [ ] Connection status indicator

### 10.2 Professional Demo Features

- [ ] Presentation mode
- [ ] Camera reset
- [ ] Focus on failed satellite
- [ ] Role reallocation table
- [ ] Replanning latency badge
- [ ] Mission health score
- [ ] Before/after metrics panel
- [ ] Replay timeline
- [ ] Event markers on timeline
- [ ] Deterministic seed display
- [ ] Scenario name display
- [ ] Large-font projected mode

### 10.3 Advanced Features

- [ ] Cost matrix viewer
- [ ] Ground coverage minimap
- [ ] Communication graph
- [ ] Fuel bars
- [ ] Trail visualization
- [ ] Thrust vector visualization
- [ ] Path prediction lines
- [ ] Sound effects
- [ ] Developer debug panel
- [ ] Automated demo script mode

---

## 11. Visual Effects Specification

Visual effects should support clarity, not distract from it.

### 11.1 High-Impact, Low-Risk Effects

These are recommended.

| Effect | Purpose | Priority |
|---|---|---|
| Status color change | Shows satellite health | Mandatory |
| Red pulsing failed satellite | Highlights failure | Mandatory |
| Formation lines | Shows swarm structure | Mandatory |
| Target ghost slots | Shows desired formation | Mandatory |
| Warning banner | Explains current event | Mandatory |
| Event log entry | Provides traceability | Mandatory |
| Coverage drop/recovery chart | Provides quantitative proof | Mandatory |
| Replanning overlay | Shows autonomy | Strongly recommended |
| Camera focus on failure | Directs attention | Strongly recommended |
| Short trails | Shows reconfiguration motion | Recommended |
| Path lines to targets | Shows planned movement | Recommended |
| Subtle glow | Improves visual polish | Optional |

### 11.2 Failure Effects

When failure occurs:

1. Satellite turns red.
2. Satellite label changes to `FAILED`.
3. Red pulse begins.
4. Small expanding ring appears.
5. Warning banner appears.
6. Event log updates.
7. Coverage chart begins dropping.
8. Optional camera briefly focuses on failed satellite.

This sequence should happen in under one second.

### 11.3 Replanning Effects

When replanning starts:

1. Mission state banner changes to `REPLANNING`.
2. Healthy satellites briefly highlight.
3. Failed satellite dims.
4. New target slots appear.
5. Role table updates.
6. Small progress indicator appears.

Text example:

```txt
Reallocating roles among remaining satellites...
```

### 11.4 Recovery Effects

When recovery begins:

1. New target slots glow.
2. Satellites show path lines to targets.
3. Satellite state changes to `RECONFIGURING`.
4. Formation deviation chart decreases.
5. When stable, satellites change to healthy/recovered colors.
6. Banner changes to `RECOVERED`.

Text example:

```txt
New formation stabilized. Coverage recovered to 84%.
```

### 11.5 Effects to Avoid

Do not use:

- Heavy particle systems
- Large explosions
- Excessive bloom
- Random camera shaking
- Long intro animations
- Overly complex starfields
- Too many colors
- Tiny fonts
- Cluttered panels
- Effects that reduce FPS below 30

---

## 12. UI Layout

### 12.1 Main Layout

```txt
+---------------------------------------------------------------+
| Mission Status Bar                                            |
| NOMINAL / FAILURE DETECTED / REPLANNING / RECOVERED           |
+------------------+---------------------------+----------------+
|                  |                           |                |
| Scenario Panel   |                           | Telemetry      |
| Simulation       |       3D Swarm View       | Dashboard      |
| Controls         |                           |                |
| Satellite List   |                           | Charts         |
|                  |                           |                |
+------------------+---------------------------+----------------+
| Event Log / Timeline / Replay Controls                        |
+---------------------------------------------------------------+
```

### 12.2 Presentation Layout

```txt
+---------------------------------------------------------------+
| Mission Status                                                |
+---------------------------------------------+----------------+
|                                             |                |
|              3D Swarm View                  | Key Metrics    |
|                                             |                |
+---------------------------------------------+----------------+
| Event Banner                                                  |
+---------------------------------------------------------------+
```

---

## 13. Visual Design System — the design law (mandatory)

The UI should look like a professional aerospace mission-control console. This section is **binding and self-contained**: it replaces the superdesign / frontend-design / avoid-ai-design skills for any agent that does not have them installed. It was written against two external rule sets that define "looks AI-generated":

- https://github.com/LeoStehlik/no-slop-ui — banned-pattern list + review checklist
- https://github.com/funboy322/avoid-ai-design — tell catalog + the `detect.mjs` scanner (zero dependencies, Node 18+)

The rule behind both: **replace defaults with decisions.** Every choice below was made for THIS product — a ground-segment ops console for a six-satellite swarm, watched on a projector from the back of a room. Keep it, and derive every new component from these tokens; never from a component library default.

### 13.0 Design direction (the paragraph that governs everything)

Direction: **industrial ops console — Swiss discipline with engineering readouts.** Greyscale chrome carries the structure; saturated color appears ONLY as semantic state (nominal / failed / reconfiguring / recovered / leader). Density is honesty: this is a telemetry tool, so it reads like one — tables, readout rows, tight consistent spacing, near-zero UI motion. The one signature element is the **state-machine timeline spine** (§13.5); spend the visual boldness there and keep everything else quiet. Dark theme is earned here (3D scene contrast, dim demo room, ops-domain convention) — but it is themed as a full palette with AA contrast, not "one neon on black".

### 13.1 Color tokens (single source: `src/styles/tokens.css`)

Raw hex/rgb values are allowed ONLY in `tokens.css`. A color used anywhere else that is not defined here is a review failure (the grep gate in Appendix B catches it mechanically).

| Token | Value | Role |
|---|---|---|
| `--bg` | `#17191a` | Page ground. Neutral graphite — deliberately NOT the Tailwind slate family (`#0f172a`…), which is the stock AI dark palette |
| `--panel` | `#1e2123` | Panel surfaces |
| `--panel-raised` | `#24272a` | Hover / selected rows / raised surfaces |
| `--border` | `#31363a` | 1px panel borders |
| `--border-strong` | `#43494e` | Table headers, emphasis borders |
| `--ink` | `#e8eaec` | Primary text (≈13:1 on `--bg`) |
| `--ink-muted` | `#9ba3a9` | Secondary text — must stay ≥ 4.5:1 on its background (AA); verify, don't eyeball |
| `--ink-faint` | `#6e767c` | Tertiary/disabled only; never body text |
| `--status-nominal` | `#46c07a` | Healthy / success / nominal curve |
| `--status-caution` | `#e0a526` | Reconfiguring / warnings |
| `--status-failed` | `#f25555` | Failure / critical |
| `--status-info` | `#5b9bf0` | Recovered / informational |
| `--status-leader` | `#f2cc46` | Leader marker — always paired with a text label or outline so it never reads as "warning" |
| `--focus-ring` | `#e8eaec` | `outline: 2px solid` on `:focus-visible` for every interactive element |

There is **no decorative accent color**. If a component feels like it needs one, it needs hierarchy (weight, size, position), not paint.

### 13.2 Typography

Two faces, clearly distinct roles, **vendored as woff2 in `src/assets/fonts/`** (IBM Plex is OFL — bundle it; no CDN, no Google Fonts link):

| Face | Role |
|---|---|
| IBM Plex Sans (400/500/600) | UI labels, body, panel titles, buttons |
| IBM Plex Mono (400/500) | Telemetry values, event log, timestamps, axis ticks, table numerals. Mono is for values a reader scans — which is what this console is for — not decorative chrome |

Sizes (the projection floor is raised from v1's 14px — judges sit meters away):

```txt
Mission state:    28-36px / 600
Metric values:    28-40px, Plex Mono, tabular numerals
Panel titles:     17-20px / 600, sentence case
Body / labels:    16px minimum
Event log rows:   14px, Plex Mono
Axis ticks:       12-13px, Plex Mono
```

Banned type moves: Inter / Roboto / Space Grotesk / Geist / system-ui as the identity face; gradient text; one accented word in a heading; ALL-CAPS letter-spaced eyebrow labels above headings; decorative numbering (01/02/03) on unordered content. Exception: state-machine literals (`NOMINAL`, `RECOVERED`, …) and satellite IDs render uppercase because they are data values from the backend enum, not styled copy.

### 13.3 Layout, surface and spacing rules

- The first screen is the product (the console itself) — no hero, no marketing band, no pill badge.
- Panels: solid `--panel`, 1px `--border`, radius ≤ 8px. Controls: radius 6px. Shadows: none except a centered modal overlay (`0 2px 8px rgba(0,0,0,0.4)` max). No glassmorphism, no `backdrop-blur`, no gradient borders, no colored glows, no floating shells.
- **No metric-card grid.** Telemetry renders as readout rows — label (sans, muted) · value (mono, ink, 28px+) · optional sparkline — grouped in a table-like column, not boxed cards. No card inside a card.
- One spacing scale (4px base: 4 / 8 / 12 / 16 / 24). Consistent panel padding; density is fine, inconsistency is not.
- Familiar product patterns: a real `<table>` for reallocation/cost tables, a native-styled `<select>` for the scenario dropdown, underline or border tab indicators. No pill buttons, no sliding-pill tabs, no animated underline inputs.
- Every interactive element ships all of its states: `:hover` (background/border change only), `:focus-visible` (2px `--focus-ring` outline), `:disabled`, loading, empty, error — with stable dimensions (loading must not shift layout).
- Responsive constraints, explicit: demo targets are a 1920×1080 projector and a 1280×800 laptop; below 1024px wide, collapse the side panels over the 3D view rather than reflowing charts.

### 13.4 Charts

- Solid 2px lines, no per-point dots, **no gradient area fills**, no library default palette.
- Series distinguishable by line style AND color (solid / dashed / dotted); direct end-of-line labels; axis labels in Plex Mono; hairline gridlines in `--border`.
- Event markers (failure, replan, recovered) as labeled vertical ticks with mono sim-time stamps.

### 13.5 Motion and the signature element

- UI motion: 120–180 ms ease-out, color/border/opacity only. No entrance animations, no bounce/spring/scale, no scroll reveals, no count-up numbers, no transform-on-hover.
- The 3D scene is exempt — it is the product: satellites coast, the failed satellite pulses red, survivors fly to new slots. Under `prefers-reduced-motion: reduce`, the pulse becomes a static red marker plus the `FAILED` label. The motion rules bind the UI chrome, never the data display.
- **Signature element:** the bottom panel's **state-machine timeline spine** — `NOMINAL → FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED` as a horizontal rail with real event ticks and mono sim-time stamps from the log. It is the demo's story in one element.

### 13.6 Copy rules

- Sentence case everywhere. Buttons name the action and its object: "Start simulation", "Inject failure", "Switch to replay" — never "Submit" or "Get started".
- No marketing filler ("command center", "seamless", "elevate", "powerful"), no `→` glyphs glued to buttons or links, no emoji as icons, no sparkle glyphs. If icons are used at all: one consistent set, few, meaning-bearing — otherwise none; this console prefers text labels.
- Errors and empty states say what happened and what to do next, in the same voice as §20 and §24.
- Every displayed number traces to the live stream or a committed log; otherwise render the string `unmeasured` (repo invariant #1). Development mock data lives in `src/dev/mockFrame.ts`, is clearly marked, and never appears in the README, the pitch, or screenshots presented as results.

### 13.7 Compliance gates (run in order, per PR and at the G5 review)

1. **Plan review.** Before writing a component's CSS, re-read §13.0–13.6 and check the component against the banned moves above.
2. **Scanner gate.**

   ```bash
   git clone --depth 1 https://github.com/funboy322/avoid-ai-design /tmp/avoid-ai-design
   node /tmp/avoid-ai-design/scripts/detect.mjs frontend/src frontend/index.html
   ```

   Must exit 0 (no P0/P1 findings). A deliberate choice the scanner flags (e.g. uppercase state literals) gets an inline `avoid-ai-design-ignore: <ID>` comment plus a one-line justification. Everything else gets fixed.
3. **Review checklist** (from no-slop-ui; verdict rules at the end).

   Product fit
   - [ ] First screen is the product, not a hero.
   - [ ] The layout serves the operator workflow: monitor, decide, act.
   - [ ] No decorative metrics, charts, badges, or activity invented to fill space.
   - [ ] The screen still makes sense with real production data, empty states, and long labels.

   Layout
   - [ ] Dense, scannable structure; panels have stable dimensions; nothing floats in a decorative shell.
   - [ ] Cards only for repeated items or modals; no card nested inside a card.
   - [ ] Explicit responsive constraints; nothing overlaps or reflows awkwardly.

   Components
   - [ ] No pill styling; tables, forms, selects, tabs use ordinary product patterns.
   - [ ] Inputs have visible labels, ordinary borders, predictable focus states.
   - [ ] Loading, disabled, active, selected, empty, and error states keep stable dimensions.

   Visual style
   - [ ] No glassmorphism, decorative gradients, gradient text, glow, or floating blobs.
   - [ ] Radius ≤ 8px panels / 6px controls; shadows none-to-subtle.
   - [ ] Palette = §13.1 tokens only; never collapses into one hue or stock dark-blue/purple.
   - [ ] Muted text ≥ 4.5:1 against its background.

   Motion
   - [ ] Hover = color/border only; no transform, bounce, spring, scale, or parallax.
   - [ ] Reduced motion respected (§13.5).

   Copy
   - [ ] Headings and labels are functional; no eyebrow+headline pattern; no SaaS filler; buttons name the action.

   **Verdict: PASS** — at most one miss per section and zero hard bans. **REVISE** — two or more misses, or any hard ban. **ESCALATE** — a rule conflicts with accessibility or a §7 requirement: keep the higher-priority one and document the tradeoff in the PR description.
4. **Render check.** Screenshot the console (at minimum the dashboard panel) and judge what the scanner cannot see: palette dominance, spacing rhythm, hierarchy. Without a render, mark those findings inferred and lower-confidence — but do not skip the checklist because of it.

---

## 14. Component Architecture

Recommended React component tree:

```txt
App
├── TopStatusBar
│   ├── MissionStateBadge
│   ├── SimTime
│   ├── ConnectionStatus
│   └── ReplayModeBadge
│
├── MainLayout
│   ├── LeftPanel
│   │   ├── ScenarioSelector
│   │   ├── SimulationControls
│   │   ├── FailureInjectionPanel
│   │   └── SatelliteList
│   │
│   ├── CenterPanel
│   │   ├── SwarmScene
│   │   │   ├── SceneGrid
│   │   │   ├── SatelliteMesh
│   │   │   ├── FormationLines
│   │   │   ├── TargetSlots
│   │   │   ├── TrailLine
│   │   │   ├── ThrustVector
│   │   │   └── FailureEffect
│   │   │
│   │   └── SceneOverlay
│   │       ├── ReplanningOverlay
│   │       ├── FailureBanner
│   │       └── CameraControls
│   │
│   └── RightPanel
│       ├── TelemetryDashboard
│       │   ├── GroundCoverageChart
│       │   ├── FormationDeviationChart
│       │   ├── InterSatDistanceChart
│       │   ├── DvChart
│       │   └── MissionHealthScore
│       │
│       ├── RoleReallocationPanel
│       └── SelectedSatellitePanel
│
└── BottomPanel
    ├── EventLog
    ├── Timeline              # the state-machine spine — §13.5 signature element
    └── ReplayControls
```

---

## 15. State Management

Use Zustand or a similarly lightweight state manager.

### 15.1 Simulation Store

Field names below mirror the master prompt §5 JSONL log schema (`sats:[{id, role, status, r, v, dv_used}], coverage, min_sep`) so one deserializer serves live WS, replay, and logs. Failure modes are `DEAD` (required) and `THRUSTER_OUT` (optional).

```ts
type MissionState =
  | "NOMINAL"
  | "FAILURE_DETECTED"
  | "REPLANNING"
  | "RECONFIGURING"
  | "RECOVERED"
  | "DEGRADED";

type SatelliteStatus =
  | "healthy"
  | "failed"
  | "reconfiguring"
  | "recovered"
  | "inactive";

interface Satellite {
  id: string;
  role: string;
  status: SatelliteStatus;
  r: [number, number, number];   // LVLH position [m]: x radial, y along-track, z cross-track
  v: [number, number, number];   // velocity [m/s]
  dv_used: number;               // Δv consumed [m/s]
  targetSlot?: string;
  failureType?: string;          // "DEAD" | "THRUSTER_OUT"
}

interface Metrics {
  coverage: number;              // instantaneous, 0-1
  coverageAvg: number;           // rolling orbit average
  formationDeviation: number;    // [m]
  minSep: number;                // [m]
  detectionLatencyS?: number;    // t_detect − t_fail
  replanningLatencyMs?: number;
  missionHealthScore?: number;   // derived, only from measured inputs
}

interface SimState {
  mode: "live" | "replay" | "stopped";
  connection: "connected" | "reconnecting" | "disconnected";
  simTime: number;
  missionState: MissionState;
  satellites: Satellite[];
  metrics: Metrics;
  events: SimEvent[];
}
```

### 15.2 UI Store

```ts
interface UiState {
  showLabels: boolean;
  showTrails: boolean;
  showFormationLines: boolean;
  showTargetSlots: boolean;
  showDebugPanel: boolean;
  presentationMode: boolean;
  selectedSatelliteId: string | null;
  cameraMode: "free" | "formation" | "follow";
}
```

### 15.3 Replay Store

```ts
interface ReplayState {
  isPlaying: boolean;
  currentTime: number;
  playbackSpeed: number;
  frames: SimFrame[];
  activeFile: string | null;
}
```

---

## 16. Backend Data Contract

The frontend and backend must agree on a strict message format.

### 16.1 WebSocket State Message

```json
{
  "type": "sim_state",
  "sim_time": 123.4,
  "state": "RECONFIGURING",
  "scenario": "two_failure.json",
  "seed": 42,
  "sats": [
    {
      "id": "SAT-1",
      "role": "leader",
      "status": "healthy",
      "r": [10.0, 2.0, -1.0],
      "v": [0.01, 0.0, -0.02],
      "dv_used": 0.12,
      "target_slot": "slot_1"
    },
    {
      "id": "SAT-3",
      "role": "sensor_3",
      "status": "failed",
      "r": [-12.0, 4.0, 2.0],
      "v": [0.0, 0.0, 0.0],
      "dv_used": 0.85,
      "failure_type": "DEAD"
    }
  ],
  "coverage": 0.84,
  "min_sep": 21.5,
  "metrics": {
    "detection_latency_s": 0.1,
    "replanning_latency_ms": 420
  }
}
```

Units are SI at this boundary (repo invariant #3): meters, seconds, m/s. Conversion to km or display units happens only in the view layer.

### 16.2 Event Message

```json
{
  "type": "event",
  "sim_time": 120.0,
  "level": "critical",
  "message": "SAT-3 propulsion failure detected"
}
```

### 16.3 Role Reassignment Message

```json
{
  "type": "role_reassignment",
  "sim_time": 121.2,
  "assignments": [
    {
      "satellite_id": "SAT-1",
      "old_role": "leader",
      "new_role": "leader",
      "cost": 0.1
    },
    {
      "satellite_id": "SAT-2",
      "old_role": "sensor_1",
      "new_role": "sensor_3",
      "cost": 1.7
    }
  ]
}
```

### 16.4 Cost Matrix Message

Optional:

```json
{
  "type": "cost_matrix",
  "sim_time": 121.1,
  "satellites": ["SAT-1", "SAT-2", "SAT-4", "SAT-5"],
  "roles": ["leader", "sensor_1", "sensor_2", "sensor_3"],
  "matrix": [
    [0.2, 1.4, 2.2, 3.1],
    [1.1, 0.6, 1.9, 2.4],
    [2.0, 1.5, 0.7, 1.2],
    [1.7, 2.1, 1.1, 0.5]
  ],
  "selected_assignments": [
    { "satellite_index": 0, "role_index": 0 },
    { "satellite_index": 1, "role_index": 1 },
    { "satellite_index": 2, "role_index": 2 },
    { "satellite_index": 3, "role_index": 3 }
  ]
}
```

### 16.5 Client Ping (mandatory)

During live mode the client sends every 30 s:

```json
{"type": "ping"}
```

Render's free tier spins the service down after 15 minutes without incoming HTTP or incoming WebSocket messages from an existing connection — server-to-client streaming does NOT count (master prompt research patch #3). This ping is what keeps the demo warm; it is not optional.

---

## 17. API Requirements

The frontend may use REST endpoints for control and WebSocket for streaming.

### 17.1 REST Endpoints

```txt
GET  /health
GET  /scenarios
POST /simulation/start
POST /simulation/pause
POST /simulation/resume
POST /simulation/reset
POST /failure/inject
GET  /replay/files
GET  /replay/file/{filename}
```

### 17.2 WebSocket Endpoint

```txt
/ws/state
```

The WebSocket should send:

- Simulation state updates
- Metrics
- Events
- Role reassignment messages
- Cost matrix messages, if enabled

The client must send a ping every 30 s during live mode (§16.5).

---

## 18. Replay File Format

Replay files ARE the sim's own JSONL run logs — the exact files `cubesat.run` writes to `data/logs/`, per the master prompt §5 schema. One line per tick:

```json
{"v":1,"t":0.0,"state":"NOMINAL","sats":[{"id":"SAT-1","role":"leader","status":"healthy","r":[10.0,2.0,-1.0],"v":[0.0,0.0,0.0],"dv_used":0.0}],"coverage":0.95,"min_sep":142.0}
{"v":1,"t":120.0,"state":"FAILURE_DETECTED","sats":[],"coverage":0.61,"min_sep":88.0,"event":{"type":"FAILURE_DETECTED","sat_id":"SAT-3"}}
```

Rules:

- The frontend parses THIS schema; it must not define a second, simplified format.
- CSV support is dropped — JSONL is the repo's primary data format (locked decision).
- Validate frames before playing: per-line defensive parse with error reporting; skip-and-log bad lines, never crash.
- Same TypeScript types as the live WS path (§15.1) — one shared deserializer. This kills adversarial risk §21.9 (schema drift between live and replay) at the root.

---

## 19. Performance Requirements

The frontend must remain smooth during the demo.

### Required Performance Targets

| Metric | Target |
|---|---:|
| Minimum FPS | 30 FPS |
| Preferred FPS | 60 FPS |
| WebSocket update rate | 10Hz to 30Hz |
| Chart update rate | 2Hz to 5Hz |
| Satellite count | 3 to 6 |
| Trail points per satellite | 150 to 250 max |
| Failure-to-visual response | < 1 second |
| Replay load time | < 2 seconds |
| Initial app load time | < 5 seconds |

### Performance Rules

- Do not re-render the entire React tree every frame.
- Use refs or transient updates for high-frequency 3D position changes.
- Limit chart history.
- Avoid heavy post-processing.
- Avoid loading large textures.
- Use simple geometry.
- Use throttling for telemetry panels.
- Pause unnecessary effects when tab is hidden.
- Sim time comes only from the data (`t` / `sim_time`); the UI never advances simulation state on wall-clock. Wall-clock is used only for the 30 s ping, reconnection backoff, and FPS measurement.
- The WebSocket ping (§16.5) keeps running while the tab is hidden.

---

## 20. Reliability Requirements

The frontend must not silently fail.

### 20.1 If Backend Is Unreachable

Show:

```txt
Backend disconnected.
Live simulation unavailable.
Switch to Replay Mode.
```

Provide button:

```txt
[Open Replay Mode]
```

### 20.2 If WebSocket Disconnects

Show:

```txt
Connection lost. Reconnecting...
```

If reconnection fails:

```txt
Live connection failed. Replay mode available.
```

### 20.3 If No Data Is Received

Show:

```txt
Waiting for simulation data...
```

Do not show a blank screen.

### 20.4 If Replay File Fails to Load

Show:

```txt
Replay file could not be loaded.
```

Provide:

```txt
[Retry]
[Select Another File]
```

---

## 21. Adversarial Research Check

This section intentionally attacks the plan to find weaknesses before the demo.

### 21.1 Assumption: React Is a Good Choice

**Risk:** React can cause performance problems if the 3D scene is re-rendered too often.

**Impact:** Low FPS, laggy demo, unprofessional feel.

**Mitigation:**

- Use React for UI panels, not per-frame 3D updates.
- Store high-frequency positions in refs or transient Zustand subscriptions.
- Use Three.js directly inside a React component if React Three Fiber becomes unstable.
- Keep satellite count small.
- Test FPS early.

### 21.2 Assumption: React Three Fiber Will Be Easy

**Risk:** React Three Fiber adds abstraction and may be hard to debug under time pressure.

**Impact:** Wasted development time.

**Mitigation:**

- Build a minimal test scene first.
- If the test scene is not stable within 1 hour, switch to plain Three.js inside React.
- Keep the 3D module isolated so it can be replaced without breaking dashboard code.

### 21.3 Assumption: WebSocket Live Mode Will Work at the Venue

**Risk:** Venue network, CORS, backend crash, or laptop issue may break live mode.

**Impact:** Live demo fails.

**Mitigation:**

- Replay mode must be ready at all times.
- Run backend locally on the same laptop.
- Avoid depending on external internet.
- Have a pre-recorded replay file in the repository.
- Test offline mode before presentation.

### 21.4 Assumption: Judges Will Understand the 3D View

**Risk:** 3D views can be confusing from certain angles.

**Impact:** Judges do not understand what happened.

**Mitigation:**

- Use large labels.
- Use clear colors.
- Add a top-down minimap if possible.
- Use camera presets.
- Show text banners for every major state.
- Use charts to prove the story.

### 21.5 Assumption: Visual Effects Improve the Demo

**Risk:** Too many effects reduce FPS and distract from the core story.

**Impact:** Demo looks game-like or unprofessional.

**Mitigation:**

- Use subtle effects only.
- Prefer color, banners, and charts over particles.
- Disable effects if FPS drops below 30.
- Keep failure animation under one second.

### 21.6 Assumption: Telemetry Charts Will Be Convincing

**Risk:** Charts may be too small, noisy, or slow to update.

**Impact:** Judges do not see recovery evidence.

**Mitigation:**

- Make ground coverage chart large.
- Use bold line colors.
- Add event markers for failure and recovery.
- Show before/after summary numbers.
- Update charts at a stable rate.

### 21.7 Assumption: Failure Will Be Obvious

**Risk:** A red satellite may be hard to see.

**Impact:** The core demo moment is missed.

**Mitigation:**

- Add warning banner.
- Add event log entry.
- Pulse the failed satellite.
- Optionally focus camera.
- Change mission state to red.
- Play a subtle alert sound if enabled.

### 21.8 Assumption: Recovery Will Be Obvious

**Risk:** The new formation may look similar to the old one.

**Impact:** Judges do not notice self-healing.

**Mitigation:**

- Show new target slots.
- Show role reassignment table.
- Show `RECOVERED` banner.
- Show coverage recovery chart.
- Show before/after comparison.

### 21.9 Assumption: Replay Data Will Match Live UI

**Risk:** Replay file schema may differ from live WebSocket schema.

**Impact:** Replay mode crashes.

**Mitigation:**

- Use one shared TypeScript type for both live and replay frames.
- Validate replay frames before playing.
- Generate replay files using the same serializer as live messages.
- Test replay after every major schema change.

### 21.10 Assumption: The Team Will Have Time to Polish

**Risk:** Core features take longer than expected.

**Impact:** UI looks unfinished.

**Mitigation:**

- Freeze new features before judging.
- Prioritize demo flow over extra panels.
- Use a simple dark theme with consistent spacing.
- Remove broken or empty panels.
- Rehearse the primary path repeatedly.

---

## 22. Accessibility and Projection Requirements

The demo will likely be shown on a projector.

### Required Rules

- Minimum body font size: 16px (§13.2); event log rows may be 14px mono, axis ticks 12–13px.
- Critical metrics: at least 28px.
- High contrast between text and background.
- Avoid red/green as the only signal; also use text labels.
- Failed satellites should be labeled `FAILED`.
- Replanning state should be written as text.
- Charts should have axis labels.
- Important events should appear in the event log.

### Colorblind Consideration

Do not rely only on color.

Use:

- Text labels
- Icons
- Line styles
- Banner messages

Example:

```txt
SAT-3: FAILED
```

Not just a red dot.

---

## 23. Demo Script Support

The frontend should support a rehearsed 3-minute demo.

### Primary Demo Buttons

```txt
[Start Nominal]
[Inject Failure]
[Show Recovery]
[Open Replay Fallback]
[Reset Demo]
```

### Optional Guided Mode

A hidden or advanced setting can enable:

```txt
Auto-run one_failure.json
Auto-inject failure at t=120s
Auto-switch to recovered banner
```

But manual control should always be available.

---

## 24. Error and Empty States

Professional UI must handle missing data.

### 24.1 No Scenario Selected

```txt
Select a scenario to begin.
```

### 24.2 No Simulation Running

```txt
Simulation stopped.
Press Start to begin.
```

### 24.3 No Satellites Available

```txt
No satellite data received.
```

### 24.4 No Metrics Available

```txt
Waiting for telemetry...
```

### 24.5 Replay Not Loaded

```txt
No replay file loaded.
Select a log file to play.
```

---

## 25. Folder Structure

Recommended frontend structure:

```txt
frontend/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── public/
│   └── favicon.svg
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api/
    │   ├── backend.ts
    │   └── websocket.ts
    ├── components/
    │   ├── layout/
    │   │   ├── TopStatusBar.tsx
    │   │   ├── LeftPanel.tsx
    │   │   ├── RightPanel.tsx
    │   │   └── BottomPanel.tsx
    │   ├── controls/
    │   │   ├── ScenarioSelector.tsx
    │   │   ├── SimulationControls.tsx
    │   │   ├── FailureInjectionPanel.tsx
    │   │   └── ReplayControls.tsx
    │   ├── three/
    │   │   ├── SwarmScene.tsx
    │   │   ├── SatelliteMesh.tsx
    │   │   ├── FormationLines.tsx
    │   │   ├── TargetSlots.tsx
    │   │   ├── TrailLine.tsx
    │   │   ├── ThrustVector.tsx
    │   │   ├── FailureEffect.tsx
    │   │   └── SceneHelpers.tsx
    │   ├── dashboard/
    │   │   ├── GroundCoverageChart.tsx
    │   │   ├── FormationDeviationChart.tsx
    │   │   ├── InterSatDistanceChart.tsx
    │   │   ├── DvChart.tsx
    │   │   ├── MissionHealthScore.tsx
    │   │   └── ReadoutRow.tsx
    │   ├── satellites/
    │   │   ├── SatelliteList.tsx
    │   │   ├── SatelliteCard.tsx
    │   │   └── SelectedSatellitePanel.tsx
    │   ├── events/
    │   │   ├── EventLog.tsx
    │   │   ├── EventItem.tsx
    │   │   └── Timeline.tsx
    │   └── reallocation/
    │       ├── RoleReallocationTable.tsx
    │       └── CostMatrixViewer.tsx
    ├── stores/
    │   ├── simStore.ts
    │   ├── uiStore.ts
    │   └── replayStore.ts
    ├── hooks/
    │   ├── useWebSocket.ts
    │   ├── useReplay.ts
    │   └── useSimFrames.ts
    ├── types/
    │   ├── satellite.ts
    │   ├── telemetry.ts
    │   └── events.ts
    ├── utils/
    │   ├── colors.ts
    │   ├── format.ts
    │   ├── geometry.ts
    │   └── thresholds.ts
    ├── dev/
    │   └── mockFrame.ts        # clearly-marked mock data for development only (§13.6)
    ├── assets/
    │   └── fonts/              # IBM Plex Sans + Mono woff2, vendored (§13.2)
    └── styles/
        ├── tokens.css          # THE only file with raw hex values (§13.1)
        └── globals.css         # reset + tokens import; CSS modules live next to components
```

---

## 26. Implementation Roadmap

**Gate mapping (repo gate protocol — one gate per session, ledger in `GATES.md`):**

| Spec phases | Repo gate | Pass criterion |
|---|---|---|
| Phases 1–6 | **G5** — FastAPI + WS + replay endpoint + React UI + dashboard | Runs locally live AND from replay; §13.7 gates clean |
| — | **G6** — deploy primary + static mirror | Both URLs work from a phone on mobile data; offline check passes (all assets vendored) |
| Phase 7 + README numbers | **G7** | Every README/pitch number traceable to a committed log |

Cut order if time-boxes slip (master prompt: cut UI polish, never the baseline comparison or the tests): presentation mode polish → §8 should-haves → §9 nice-to-haves. The §31 MVP plus the §13 design law is an acceptable demo; a sloppy clone of every feature is not.

### Phase 1 — Foundation

Goal: App shell exists.

Tasks:

- Create Vite React app.
- Add TypeScript.
- Add styling.
- Create layout panels.
- Add fake static data.
- Create top status bar.

Acceptance:

```txt
The UI renders with placeholder panels.
```

### Phase 2 — 3D Scene

Goal: Basic swarm visualization works.

Tasks:

- Render satellites.
- Add labels.
- Add OrbitControls.
- Add formation lines.
- Add status colors.
- Add camera reset.

Acceptance:

```txt
The user can see and rotate a swarm of satellites.
```

### Phase 3 — Live Data

Goal: Backend data drives the UI.

Tasks:

- Add WebSocket hook.
- Parse simulation state.
- Update satellite positions.
- Update mission state.
- Update metrics.
- Show connection status.

Acceptance:

```txt
Live backend updates move the satellites and update telemetry.
```

### Phase 4 — Dashboard

Goal: Telemetry proves the story.

Tasks:

- Add ground coverage chart.
- Add formation deviation chart.
- Add distance chart.
- Add event log.
- Add satellite list.

Acceptance:

```txt
Failure causes visible metric drop; recovery causes metric rise.
```

### Phase 5 — Failure and Recovery UX

Goal: Self-healing is obvious.

Tasks:

- Add failure banner.
- Add red pulse effect.
- Add replanning overlay.
- Add role reallocation table.
- Add target slots.
- Add recovery banner.

Acceptance:

```txt
A judge can understand failure and recovery without explanation.
```

### Phase 6 — Replay Mode

Goal: Demo has a professional fallback.

Tasks:

- Load replay file.
- Play/pause.
- Seek timeline.
- Show replay badge.
- Switch from live to replay.

Acceptance:

```txt
The full demo can be shown without a live backend.
```

### Phase 7 — Polish and Rehearsal

Goal: Demo is stable and professional.

Tasks:

- Improve typography.
- Improve spacing.
- Add presentation mode.
- Test projector resolution.
- Test FPS.
- Rehearse demo.
- Freeze features.

Acceptance:

```txt
The primary demo path works repeatedly without crashing.
```

---

## 27. Acceptance Criteria

The frontend is considered complete when all of the following are true.

### Functional Acceptance

- [ ] User can select a scenario.
- [ ] User can start a simulation.
- [ ] User can inject a failure.
- [ ] UI shows failure clearly.
- [ ] UI shows replanning clearly.
- [ ] UI shows recovery clearly.
- [ ] Telemetry charts update.
- [ ] Event log updates.
- [ ] Replay mode works.
- [ ] Presentation mode works.

### Visual Acceptance

- [ ] Failed satellite is obvious.
- [ ] New formation is obvious.
- [ ] Coverage drop is obvious.
- [ ] Coverage recovery is obvious.
- [ ] Text is readable from a distance.
- [ ] UI does not look cluttered.
- [ ] Colors are consistent.
- [ ] FPS remains above 30.
- [ ] §13.7 scanner exits 0 (no P0/P1 tells) on `frontend/src`.
- [ ] §13.7 review checklist verdict is PASS.
- [ ] All colors and type come from `tokens.css` + vendored IBM Plex (grep gate in Appendix B is clean; no CDN fonts).
- [ ] Works with the network cable pulled.

### Reliability Acceptance

- [ ] Frontend does not crash if backend disconnects.
- [ ] Frontend shows helpful error messages.
- [ ] Replay mode can be activated quickly.
- [ ] Replay file plays without backend.
- [ ] Demo can be reset quickly.
- [ ] No console errors during primary demo path.

### Presentation Acceptance

- [ ] Demo can be completed in under 3 minutes.
- [ ] Presenter can trigger failure with one button.
- [ ] Presenter can switch to replay with one button.
- [ ] The system tells the self-healing story without explanation.

---

## 28. Definition of Done

The frontend is done when:

1. The live demo works.
2. The replay demo works.
3. The failure moment is obvious.
4. The recovery moment is obvious.
5. The telemetry proves recovery.
6. The UI is readable on a projector.
7. The app does not crash during rehearsal.
8. The presenter can operate it confidently.

---

## 29. What Not to Build

To protect the hackathon timeline, do not build:

- Production authentication
- User accounts
- Database admin screens
- Complex deployment dashboards
- Multi-user collaboration
- Full orbital mechanics visualization
- Heavy cinematic intro
- Advanced settings with too many options
- Real-time ground station integration
- Microservice frontend architecture
- Overly complex 3D models

---

## 30. Final Product Principles

Every frontend decision should satisfy these principles:

1. **Clarity over decoration.**  
   If an effect does not help explain failure or recovery, remove it.

2. **Reliability over novelty.**  
   A boring demo that works beats an impressive demo that crashes.

3. **Story over features.**  
   The frontend must prove self-healing in under 3 minutes.

4. **Replay is not optional.**  
   Cached replay is a core requirement, not a bonus feature.

5. **Judges are the primary users.**  
   Design for fast understanding, large projection, and technical credibility.

---

## 31. Recommended MVP

If time is limited, build only this:

```txt
React mission-control dashboard with:
- 3D swarm view
- Start / Inject Failure / Replay controls
- Satellite status colors
- Failure banner
- Replanning banner
- Recovery banner
- Ground coverage chart
- Formation deviation chart
- Event log
- Replay mode
```

This MVP is enough if it is stable, readable, and clearly demonstrates self-healing.

---

## 32. Final Summary

The frontend should be a professional React-based mission-control interface that makes the CubeSat swarm’s self-healing behavior visible, measurable, and credible.

It must show:

```txt
Nominal formation
→ Failure
→ Detection
→ Role reallocation
→ New formation
→ Mission recovery
```

The most important success metric is not visual complexity.

It is this:

> A judge should be able to watch the demo for 30 seconds and understand that the swarm detected a failure and autonomously recovered.

---

## Appendix A — v1.0 → v2.0 changelog

Why this revision exists: the spec was reconciled against the repo's locked decisions and master prompt, and hardened so an implementing agent **without** the design skills still produces UI that passes the two anti-slop rule sets the user adopted on 2026-09-28 ([no-slop-ui](https://github.com/LeoStehlik/no-slop-ui), [avoid-ai-design](https://github.com/funboy322/avoid-ai-design)).

1. **Stack locked (§5):** plain Three.js inside React (no React Three Fiber), CSS Modules + `tokens.css` (no Tailwind), Recharts, vendored IBM Plex fonts. React supersedes the master prompt's "Frontend: Plain Three.js" locked decision and the "no React" anti-goal — frontend only, user-approved 2026-09-28, logged in `GATES.md`.
2. **Design law added (§13):** v1's slate+cyan+Inter palette was itself on the banned lists (Tailwind slate = the stock AI dark; cyan-on-dark-blue explicitly banned by no-slop-ui; Inter = tell T1 and Space Grotesk = tell T2 in avoid-ai-design). New direction: industrial ops console — neutral graphite chrome, color-as-state-only, IBM Plex Sans/Mono, readout rows instead of metric-card grids, plus the full banned-pattern list, review checklist, and scanner gate embedded so no design skills are needed to comply.
3. **Schema alignment (§15, §16, §18):** field names mirror the master prompt §5 JSONL log schema (`sats[{id, role, status, r, v, dv_used}]`, `coverage`, `min_sep`, `state`); failure modes are `DEAD`/`THRUSTER_OUT`; replay reads the sim's own logs — v1's invented format and the CSV option are dropped, which fixes adversarial risk §21.9 at the root.
4. **Metrics aligned (§7.5):** Δv per satellite and detection latency added (master-prompt-required); the coverage chart is explicitly the 3-curve chart (nominal reference / no-recovery / recovery); "fuel proxy" became Δv used.
5. **Repo reality (§6.2, §7.1):** scenario list matches `data/scenarios/` (dropdown reads the directory); replay path is `data/logs/*.jsonl` from the repo's own run command.
6. **Ops requirements (§16.5, §19):** mandatory 30 s client ping (Render spin-down, research patch #3); sim time only from data, never wall-clock.
7. **Accessibility raised (§22):** body floor 16px for projection; state always rendered as text alongside color.
8. **Mock-data rule (§4, §13.6):** all illustrative numbers in this spec are design-only; the UI renders `unmeasured` until a committed log supplies values (repo invariant #1).
9. **Roadmap mapped to gates (§26)** with an explicit cut order; visual acceptance extended with the §13.7 gates (§27).

## Appendix B — implementing-agent quick reference

```bash
# repo quality gates (AGENTS.md protocol)
uv sync --locked
uv run ruff check .
uv run pytest -m "not slow" -x -q

# frontend (once frontend/ exists)
cd frontend && npm ci && npm run dev     # Vite dev server
npm run build                            # static build -> served by FastAPI, reused for the mirror

# design-law gate (§13.7) — before every UI PR and at the G5 review
git clone --depth 1 https://github.com/funboy322/avoid-ai-design /tmp/avoid-ai-design
node /tmp/avoid-ai-design/scripts/detect.mjs frontend/src frontend/index.html   # must exit 0

# drift gate: raw hex may appear only in tokens.css (must print nothing)
grep -rn --include="*.css" --include="*.tsx" -E "#[0-9a-fA-F]{3,8}\b" frontend/src | grep -v "styles/tokens.css"
```

If two rules in this spec ever conflict, precedence is: repo invariants (AGENTS.md) > §7 must-haves + §13 design law > §8 should-haves > §9 nice-to-haves. Report the conflict; never resolve it silently.
