# Prompt — install the KINTSUGI-6 3D landing page

Paste everything below into your coding agent, from the repo root, with `kintsugi-3d-landing.zip` attached or unzipped at the repo root.

---

Install the new KINTSUGI-6 3D landing page into this repo. The code is already written and builds cleanly. Your job is to place it, verify it, and tune only if something looks wrong. **Do not change any other page.** The Live console (`#/live`), Replay, Tutorial, FAQ and Docs stay exactly as they are.

## Files (unzip at the repo root, paths preserved)
- `frontend/src/components/landing/landingScene.ts` — NEW. The Three.js scene.
- `frontend/src/components/landing/LandingPage.tsx` — REPLACES the current landing page.
- `frontend/src/components/landing/LandingPage.module.css` — REPLACES.
- `frontend/src/styles/tokens.css` — adds the `--hero-*`, `--hero-gold*` and `--cubesat-*` tokens. Merge if tokens.css changed since; keep all existing tokens.
- `frontend/src/App.module.css` — one line: `grid-template-columns: minmax(0, 1fr)` on `.app`, so the page never overflows sideways on phones.
- `frontend/src/components/layout/TopStatusBar.module.css` — the top bar scrolls sideways on narrow screens instead of widening the page. Desktop looks unchanged.

No new dependencies. It uses `three` plus its own bundled addons (`three/examples/jsm/postprocessing/*` for bloom, `three/examples/jsm/lines/*` for thick gold lines).

## What the page does
1. **Hero:** a 3D "KINTSUGI-6" wordmark with a gold kintsugi crack through the letters. Six 3U CubeSats (solar panels, wings, antennas) orbit it on a tilted ring and pass in front of and behind the letters. Five telemetry cards float on an outer ring using measured values only: 4 s detection, 27.0% vs 22.1% coverage, 75 runs, byte-identical reruns. Mouse parallax, slow camera sway, stars and dust. Below the wordmark: tagline, "Launch live demo" → `#/live`, "Watch a replay" → `#/replay`.
2. **Scroll beat 1, "One satellite breaks":** SAT-3 turns red, glows, throws a burst of red debris and tumbles off the ring. The swarm moves right and the copy sits left.
3. **Scroll beat 2, "The swarm repairs itself — with gold":** the five survivors re-space evenly, then glowing gold lines draw between them one by one, with a gold halo on each satellite.
4. **Proof section:** a stats panel (4 measured numbers, each with its source), the ORIGINAL landing content (the "Live simulation sandbox" and "Scenario replays" cards with their bullets), and the footer links Tutorial / FAQ / Technical documentation. The gold formation turns slowly on the right.
5. **Section dots** on the right edge jump between sections.

**Scroll mapping is section-based:** section i reaching the top of the viewport = progress i/3. Don't change it to raw scroll fraction; the proof section is taller than the screen and the beats would drift.

Accessibility: a screen-reader `<h1>` for the wordmark, real buttons and links, a focus ring. With reduced motion there's no orbit or sway, and the scroll beats still play. With no WebGL, the copy still renders on black.

## Verify
1. `cd frontend && npm run build` → exit 0.
2. Hex gate: `grep -rnE '#[0-9a-fA-F]{3,8}' src | grep -v tokens.css` → no output.
3. `npm run dev` with the backend running (`uv run uvicorn cubesat.api:app --port 8000`). Open `#/` at 1920×1080, 1366×768 and 390×844. Scroll top to bottom. Check:
   - the hero wordmark is readable and the gold crack is visible;
   - satellites pass behind and in front of the letters;
   - the red break plays on section 2;
   - the gold lines draw on section 3;
   - the proof panel and original cards render;
   - no console errors; no horizontal scroll.
4. Open `#/live` and confirm it is unchanged.
5. Check performance on the demo laptop: the scene caps pixel ratio at 1.75 and pauses when the tab is hidden. If it stutters, lower bloom strength (`UnrealBloomPass(..., 0.7, 0.5, 0.82)` in landingScene.ts) or the pixel-ratio cap.

## Tuning knobs (landingScene.ts, inside `frame()`)
- Beat timing: `const a` (hero → story), `const f` (break), `const r` (re-space), `const seamT` (gold lines), `const outro`, each a `smooth(start, end, p)`.
- Swarm position in the story sections: `center.set(...)`. Ring size: `const radius`.
- Gold glow: `seamMat` linewidth (px) and the `UnrealBloomPass` arguments (strength, radius, threshold).

Report back: screenshots of the hero, break, repair and proof sections at 1920×1080 and on a phone.

## Known issue (do not fix here, tell the team)
The Live scenario builder offers up to 50 satellites, but the backend now rejects anything above 32 (`MAX_SATS = 32` in `cubesat/scenario.py`). Choosing 50 fails on upload.
