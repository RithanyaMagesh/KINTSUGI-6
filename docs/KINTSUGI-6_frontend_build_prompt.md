# Build prompt — KINTSUGI-6 frontend redesign

Paste everything below into your coding agent, run from the repo root.

---

You are redesigning the frontend of the KINTSUGI-6 CubeSat swarm self-healing simulator (`frontend/`). This is a **reskin plus missing-feature catch-up**. Keep every existing page, every feature, all data wiring and all written content. Change presentation and add the items in Phase 4. Work in phases. After each phase, run the gates, show me screenshots, and STOP until I say go.

## Read first (before any code)
1. `docs/FRONTEND_SPEC.md` — especially §13 (design law). Where this prompt conflicts with §13, this prompt wins for colours, fonts and the landing page only; everything else in §13 stands.
2. `frontend/src/styles/tokens.css` — the ONLY file allowed to contain raw hex.
3. `cubesat/wire.py` — the exact WebSocket and REST contract. Never invent fields.
4. `frontend/src/pages/Router.tsx`, `App.tsx`, `stores/*`, `api/deserializer.ts` — how data flows.
5. Every page component under `src/components/` — inventory all existing copy, controls and panels before moving anything.

## Hard rules
- Stack is locked: React 18 + TypeScript, Vite 7, Zustand, Recharts, plain Three.js, CSS Modules. **No new dependencies.**
- Raw hex/rgb only in `tokens.css`. Check: `grep -rnE '#[0-9a-fA-F]{3,8}' src | grep -v tokens.css` must return nothing.
- Fonts are vendored woff2 in `src/assets/fonts/` (no CDN). To add Space Grotesk, download the OFL woff2 files into that folder, add `@font-face` in `globals.css`, and copy its licence next to `OFL.txt`. If you can't vendor it, use IBM Plex Sans 600 for display.
- **No invented numbers.** Every number on screen comes from the wire or a committed result. A missing value renders the word "unmeasured".
- Do not change any Python file. If you find a backend bug, list it in your report instead.
- Keep the hash router routes: `#/`, `#/live`, `#/replay`, `#/tutorial`, `#/faq`, `#/docs`.
- Accessibility: real `<button>`/`<a>`/`<label>`, visible focus ring, text contrast ≥ 4.5:1, honour `prefers-reduced-motion`.
- Projector-readable: body ≥ 16 px, narration ≥ 24 px, key metrics ≥ 28 px mono.
- Must work at 1920×1080, 1366×768 and 390×844 (phone), with no horizontal page scroll.

## Design concept — "repaired with gold"
Kintsugi is the Japanese art of repairing broken pottery with gold. The product does that to a satellite swarm. Gold is the brand's signature, and it means exactly one thing: **healed**.

Tokens to add to `tokens.css` (dark is the primary theme; keep the existing light theme toggle working):
- Ground `#05070A`, panel `#0B0F14`, raised `#10151C`, hairline `#1C232D`, strong line `#2A333F`
- Ink `#E8ECF2`, muted `#8A94A3`, faint `#6B7684`
- State colours (colour = state only, never decoration):
  - healthy / holding slot → green `#2FBF71`
  - battery fading (status `degraded`) → amber `#F0A830`
  - lost / failed → red `#E5484D`
  - manoeuvring to a new slot → blue `#5B9BF0`
  - **recovered / healed links → gold `#D4A84B`** (new; the only place gold appears)
- One action colour for primary buttons: `#3D6BFF`.
- Type: display = Space Grotesk 600–700; body = IBM Plex Sans; numbers = IBM Plex Mono with tabular figures.
- Style: thin 1 px lines, 6–8 px radii, no gradients-as-decoration, no drop shadows, no emoji.

## Phase 1 — Tokens and fonts
Add the tokens and fonts. Map existing semantic tokens onto them. Map the `recovered` status and the RECOVERED mission state to gold. The app must look the same structurally, only recoloured. Gates (below), then STOP.

## Phase 2 — Landing page (`#/`)
If `src/components/landing/landingScene.ts` exists (the scroll-story CubeSat scene), keep and extend it; don't rebuild it.
1. **Hero, Cosmos.so style:** centred wordmark "KINTSUGI-6" with the tagline "The swarm that heals itself." Around it, six small procedural CubeSats orbit in a slow tilted 3D swirl (Three.js). Floating among them are 4–6 small telemetry cards in the orbit. When connected, cards use live wire values; offline, they use committed measured values labelled as such ("Detection 4 s", "Coverage restored 27.0% vs 22.1%", "75 benchmarked runs"). A small top nav pill sits above, plus one primary CTA "Launch live demo" → `#/live` and a secondary "Watch a replay" → `#/replay`.
2. **Scroll beat — the break:** one satellite cracks red and drifts out of the orbit.
3. **Scroll beat — the repair:** survivors re-form. The new links between them draw in as gold lines (the kintsugi moment).
4. Then keep the existing landing content: the workflow-mode descriptions (live sandbox vs scenario replays), the measured-stats section, and footer links to Tutorial / FAQ / Docs, restyled.
5. Reduced motion: a static composition, no swirl.

Gates, then STOP.

## Phase 3 — Live console (`#/live`) — the demo screen
Rearrange the EXISTING components into this layout; do not drop any of them:
- **Top status bar:** wordmark, mission-state chip (colour by state), mission time `T+hh:mm:ss`, scenario + seed, connection badge, pause, speed ×10/×100/×500, primary button "Break a satellite".
- **Centre (≈ 65–70% width):** the 3D swarm scene. Status rings use the state colours above. Transfer paths are dotted blue. Healed formation links are gold once RECOVERED. Legend at bottom-left. View toggle Formation / Earth orbit.
- **Right rail:** coverage chart (recovery vs no-recovery reference when available), readout tiles (detection latency, closest approach vs 2 km floor), satellite list (id, role, status colour + text).
- **Bottom band:** NarrationStrip as one big plain-English sentence (24 px), plus a phase spine NOMINAL → FAILURE DETECTED → REPLANNING → RECONFIGURING → RECOVERED with sim timestamps.
- **Scenario builder, failure injection, recovery policy select, AI-risk toggle, role history, recovery log, event log:** keep them all. Move them into a right-side drawer or tabs opened from the top bar, so the default view stays clean for the projector.

Gates, then STOP.

## Phase 4 — Support the new backend features
The backend added these; the frontend has none of them yet:
1. **`degraded` satellite status** (battery fading): add it to `SatelliteStatus` in `types/satellite.ts`; amber in `utils/colors.ts` (`satelliteStatusColor`) and `components/three/sceneColors.ts` (`statusToken`); label it "Battery fading".
2. **EPS_DEGRADE injection:** `POST /failure/inject` accepts `{sat_id, mode: "EPS_DEGRADE", degrade_s}`. Add it to `FailureInjectionPanel.tsx`, `live/scenarioDraft.ts` (`FAILURE_MODES`) and `live/FailureRow.tsx`, with a "fade duration (s)" number field. Mode labels in plain English: "Kill (no signal)", "Thruster failure", "Battery fade".
3. **Fix the THRUSTER_OUT help text** (currently says the swarm "does not replan" — now wrong). New text: "Thrusters fail; the satellite reports it and the swarm replans immediately." Update the FAQ/Docs/Tutorial wherever they repeat the old claim.
4. **"Hand over roles on degrade" toggle** in the scenario builder → scenario field `reassign_on_degrade: true` in `buildScenario` (it's a scenario field sent via upload, NOT a start-request field).
5. **Narrate the new events** in NarrationStrip, recoveryStore and the event log:
   - `DEGRADE_START` → "SAT-n battery fading — failure expected"
   - `ORACLE_SWAP` → "Leader role handed from SAT-a to SAT-b before SAT-a fails" (3D: gold pulse on the receiving satellite)
   - `EVASIVE_MANEUVER` → already arrives as text "SAT-x evasive maneuver (SAT-y, range Z m)"; show it as an amber event.
   - Note: `DEGRADE_START` and `ORACLE_SWAP` currently arrive as bare type names with no satellite ids. Derive the ids by diffing satellite status/roles between consecutive `sim_state` frames, and list "backend should format these messages" in your report.

Gates, then demo check: start `eps_leader_6sat` with the hand-over toggle on (upload a copy via the builder) → leader turns amber → role handover narrated → leader dies → no gap in leader role. Then `two_failure` → coverage recovers. Screenshot each step, then STOP.

## Phase 5 — Replay, Tutorial, FAQ, Docs
Replay = the Phase 3 console without control chrome plus the transport bar. Document pages: restyle typography and colours only; keep all text. Gates, then a final report.

## Gates (run after every phase)
- `cd frontend && npm run build` → exit 0
- hex grep (above) → no matches
- Start the backend `uv run uvicorn cubesat.api:app --port 8000` and the frontend `npm run dev`. Open every touched page at 1920×1080 and 390×844: no console errors, no horizontal scroll, screenshots attached.

## Final report
What changed per file, screenshots per page, backend issues found (do not fix them), and anything you could not do.
