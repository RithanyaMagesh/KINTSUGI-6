# Semantic Light/Dark Theme Tokens & Seamless 3D Camera Perspectives

This plan completes the semantic color token system across Dark and Light themes (`tokens.css` + `uiStore`) and refines the 3D scene controller (`SwarmSceneController`) to support seamless, zero-remount transitions between **Global Orbit** (Earth-centered wide orbital ring) and **Formation Array** (close-up LVLH relative coordinate grid).

## User Review & Critical Decisions

> [!IMPORTANT]
> Both features build directly on the confirmed workspace architecture while enforcing `docs/FRONTEND_SPEC.md` §13 design laws (zero raw hex values outside `tokens.css`, no `text-transform: uppercase`, and deterministic SI physics).

- **Confirmed Decision 1 — Semantic Light & Dark Theme Architecture**: All surface, border, typography, status, and 3D scene colors live exclusively in `tokens.css` under `:root` (Dark default) and `:root[data-theme="light"]` (Light mode). Toggling `theme` in `uiStore` updates `document.documentElement.dataset.theme`, flushes the Three.js token color cache, and refreshes all 3D materials (`Environment`, `SlotLayer`, `FormationLines`, and satellite markers/trails) in-place.
- **Confirmed Decision 2 — Two Seamless 3D Camera Perspectives (`Global Orbit` vs `Formation Array`)**: Switching `orbitViewMode` in `uiStore` between `"global"` (**Global Orbit**) and `"local"` (**Formation Array**) updates the active `SwarmSceneController` instance Imperatively via Zustand subscription—never unmounting or recreating the `<canvas>` or `WebGLRenderer`.

---

## 1. Overview & Core Concept

- **What It Does**:
  1. Provides a calibrated dual-theme token palette (Dark obsidian console and Light clinical lab slate) that cascades automatically to every CSS module, SVG chart, and Three.js material.
  2. Equips the 3D orbital viewport with two distinct, operator-selectable perspectives—**Global Orbit** (wide Earth-centered LEO constellation view) and **Formation Array** (close-up LVLH relative grid with 2:1 Clohessy–Wiltshire slot geometry)—switching smoothly without losing WebGL context.
- **Target Audience / Persona**: CubeSat flight dynamics engineers and mission operators evaluating autonomous self-healing swarm behavior in both ambient-lit control rooms (Dark mode) and daylight/report environments (Light mode).
- **Key Value**: Eliminates visual artifacts when toggling themes and lets operators inspect both macro orbital geometry around Earth and micro relative slot-reassignment geometry on a single persistent WebGL canvas.

---

## 2. User Experience & Visual Design

- **Key User Flows**:
  1. **Theme Switching**: Clicking the `Light mode` / `Dark mode` toggle in the top status bar immediately flips `data-theme` on `<html>`, updating all panel backgrounds, hairline borders, text hierarchy, Recharts axes, and Three.js scene background/materials in a single frame.
  2. **Perspective Switching (`Global Orbit` ↔ `Formation Array`)**: Clicking `Global Orbit` or `Formation Array` in the top-left 3D viewport control bar transitions the camera target, framing radius, coordinate transform, and reference geometry (Earth globe + inclined LEO ring vs. local LVLH relative coordinate grid + 2:1 CW ellipse) seamlessly without canvas flicker.
- **Visual Identity & Theme**:
  - *Aesthetic Direction*: Calibrated aerospace telemetry console (`docs/FRONTEND_SPEC.md` §13).
  - *Color Palette & Mood*:
    - **Dark Theme (`:root`)**: `--bg: #0b0d10`, `--panel: #11151b`, `--panel-raised: #181e26`, `--border: #222933`, `--ink: #e8ecf2`, `--ink-muted: #98a2b0`, `--scene-earth-ocean: #0c2b3f`, `--scene-earth-land: #24523f`.
    - **Light Theme (`:root[data-theme="light"]`)**: `--bg: #f4f6f9`, `--panel: #ffffff`, `--panel-raised: #eaeef4`, `--border: #d5dce6`, `--ink: #11161f`, `--ink-muted: #4b5666`, `--scene-earth-ocean: #14496b`, `--scene-earth-land: #2d6b4f`.
    - **Semantic Status Accents**: `--status-nominal`, `--status-caution`, `--status-failed`, `--status-info`, and `--status-leader` tuned for WCAG AA contrast in both themes.
  - *Typography & Hierarchy*: `IBM Plex Sans` for UI labels in sentence case and `IBM Plex Mono` (`tabular-nums`) for all coordinates, timers, and telemetry readouts.
- **Interactive Feedback & Motion**:
  - Camera transitions between **Global Orbit** and **Formation Array** use `AutoFitController` exponential damping (`1 - Math.exp(-FIT_RESPONSE * dt)`) so the camera glides smoothly between the wide Earth-centered frame and the tight relative formation frame.

---

## 3. Key Product Decisions & Trade-Offs

- **Decision 1 — Imperative Three.js Material Refresh on Theme Toggle**:
  - *Chosen Approach*: Call `clearColorCache()` in `uiStore.setTheme()` and invoke `controller.refreshTheme()` across `Environment`, `SlotLayer`, `FormationLines`, and satellite records.
  - *Why*: Three.js `Color` instances are copied into materials on creation; explicitly refreshing material colors on theme change keeps the single WebGL context alive while matching CSS variables 100%.
  - *Alternatives Considered*: Keying the `<SwarmScene>` component on `theme` to force a remount—rejected because remounting destroys the WebGL context, resets camera orientation, and causes a visible flash.
- **Decision 2 — Local Relative Grid in `Formation Array` Mode**:
  - *Chosen Approach*: When switching to `Formation Array` (`orbitViewMode === "local"`), hide the Earth globe and reveal a scaled local LVLH coordinate grid (`sceneEarth.ts`) centered at `[0, 0, 0]` beneath the 2:1 Clohessy–Wiltshire formation ellipse and slot markers.
  - *Why*: Gives immediate spatial scale and radial/along-track reference in the close-up relative perspective while keeping **Global Orbit** focused on Earth and the inclined LEO ring.

---

## 4. Technical Architecture & Data Strategy

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Zustand Global UI Store                          │
│  • theme: "dark" | "light"  ──► sets <html data-theme="...">             │
│  • orbitViewMode: "global" | "local"                                     │
└───────────────────┬──────────────────────────────────┬───────────────────┘
                    │                                  │
                    ▼                                  ▼
┌───────────────────────────────────────┐  ┌───────────────────────────────┐
│   CSS Modules & Recharts Telemetry    │  │    SwarmScene React Wrapper   │
│  • Inherit semantic vars from         │  │  • Persistent <div ref={host}>│
│    tokens.css (--bg, --panel, --ink)  │  │  • Controls:                  │
│  • Zero hard-coded hex/rgb values     │  │    [Global Orbit |            │
│                                       │  │     Formation Array]          │
└───────────────────────────────────────┘  └───────────────┬───────────────┘
                                                           │
                                                           ▼
                                           ┌───────────────────────────────┐
                                           │     SwarmSceneController      │
                                           │  • setOrbitViewMode(mode):    │
                                           │    - "global": Earth + LEO    │
                                           │      ring + wide camera fit   │
                                           │    - "local": LVLH relative   │
                                           │      grid + 2:1 CW close fit  │
                                           │  • refreshTheme(): updates    │
                                           │    scene.background, Earth,   │
                                           │    SlotLayer & FormationLines │
                                           └───────────────────────────────┘
```

- **Data Model & State**:
  - `uiStore.theme`: `"dark" | "light"`, persisted to `localStorage` (`cubesat_theme`) and mirrored to `document.documentElement.dataset.theme`.
  - `uiStore.orbitViewMode`: `"global" | "local"`, controlling both the UI toggle buttons (`Global Orbit` / `Formation Array`) and `SwarmSceneController.setOrbitViewMode()`.
- **Interactive Component & State Mapping**:
  - **TopStatusBar Theme Toggle**: Calls `toggleTheme()` $\rightarrow$ updates `data-theme` attribute $\rightarrow$ `SwarmScene` subscription triggers `controller.refreshTheme()` updating `scene.background`, `environment.refreshTheme()`, `slots.refreshTheme()`, and `lines.refreshTheme()`.
  - **SwarmScene Perspective Toggle**: Clicking `Global Orbit` or `Formation Array` calls `setOrbitViewMode("global" | "local")` $\rightarrow$ `SwarmScene` subscription calls `controller.setOrbitViewMode(mode)` $\rightarrow$ toggles Earth globe vs. local LVLH relative grid, clears stale trails from the prior coordinate frame, and smoothly dampens the camera to the new target and radius without unmounting the canvas.
