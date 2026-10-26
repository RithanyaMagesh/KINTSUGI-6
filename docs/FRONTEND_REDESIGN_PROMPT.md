# FRONTEND REDESIGN PROMPT — CubeSat swarm console, round 4

You are the AI agent redesigning the frontend of this repo. The current console went through three rebuild
rounds and the user still rejects it: "it's shit, like really shit." Your job is a full redesign pass — not a
fresh rewrite from zero (the architecture underneath is sound), but a ruthless re-examination of every page,
panel, and pixel against the acceptance bar below, fixing everything on the issue list and designing for the
roadmap that is being added. This prompt is your contract. Read all of it before touching a file.

Repo: `C:\Users\dhruv\PycharmProjects\Cubesat` (git, branch `master`, HEAD `7a7b043` + uncommitted work — see §5).

---

## 1. Mandatory reading, in this order (before writing any code)

1. `AGENTS.md` — invariants (byte-determinism, SI units, no number without a command, agents never commit).
2. `docs/HANDOFF.md` — the full project history: every decision, every measured result, every mistake, open
   warts, roadmap. **§7 (frontend) and §8 (mistakes 8–15, 22) are about you.**
3. `graphify-out/GRAPH_REPORT.md` (+ query `graphify-out/graph.json` for structural questions) — the code map.
4. `docs/FRONTEND_SPEC.md` v2.1 — the frontend law. **§5 (locked stack — nothing beyond it without user
   sign-off), §13 (design law — mandatory, replaces design skills you may or may not have), Appendix B (hex
   grep gate), Appendix D (risk field rules).** Note: the spec describes a single-page app; the hash-router
   pages (§4 below) are the newer, user-approved reality.
5. `docs/BACKEND_SPEC.md` v1.1 — §6 wire contract (what the backend actually sends — your only data source),
   §7.1 error semantics (what your error states must render).
6. `audit_out/AUDIT.md` — the safe-claims and do-NOT-claims lists. The UI is a claims surface: a readout that
   implies something on the do-NOT list (e.g. that AI is in the control loop) is a defect.
7. Skim `docs/ENDGAME_PLAN.md` §7 (AI-layer decisions) — why the predictor is display-only.

Do not skip §13 and the wire contract. Every past UI failure traces to violating one of those two.

## 2. The product definition (user's words, the acceptance bar)

> "LIVE = you control the satellites, you choose satellites, you choose everything, it does the 3D simulation
> (select no. of satellites, define roles, select a failure, way of recovery algo, see how it pans out on our
> physics engine). REPLAY = just play a simulation and watch."

- **`#/live` is THE control seat.** One page: build the scenario (satellite count, roles, formation geometry,
  failure list with sat/time/mode, recovery policy, seed/speed/duration, AI-risk overlay) → start → the 3D sim
  plays on the same page, with live injection and controls.
- **`#/replay` is playback-only.** Gallery of committed runs, one transport (play/pause/seek/speed), no control
  chrome. It must never grow controls.
- **`#/` landing** explains what this is in 10 seconds: the self-healing story, live-vs-replay, and where to
  click. `#/tutorial`, `#/faq`, `#/docs` carry the deeper explanation.
- The console must **explain itself**: what a failure is, what recovery did, why satellites moved, what the AI
  risk number means (and does NOT mean). An operator who has never seen the sim should be able to follow the
  recovery story without asking anyone.

## 3. Every issue the user has raised — the full charge sheet

### 3.1 Fixed in rounds 1–3 — DO NOT REGRESS (each was a real bug)

- Zoom made satellites giant blobs → constant-screen-size markers.
- Labels piled up / 8 labels fan around Earth overlapping → declutter with priority hiding + leader ticks.
- Yellow wireframe slot spheres dominated; trails sliced the view; red lines everywhere → toned down.
- Double top bar + double transport + stale dropdown on replay → replay made playback-only, ONE transport.
- Right-panel overlap (Role reassignment / chart caption / Selected satellite rendered on top of each other) →
  restacked; caption under its chart.
- `simStore.reset()` clobbered connection state → lying "Disconnected" badge over a working replay (fixed
  `b33a9fa`; also: never render the live connection overlay in replay mode).
- NarrationStrip narrated non-movers → movers filtered via `prevSlot !== targetSlot`.
- Nav markup without CSS → default blue links (markup and its CSS land together).
- MissionBrief auto-open retired → landing page replaces it.

### 3.2 Still broken or ugly — FIX THESE

1. **Density and clutter**: "cluttered, bloated signs, wasted space." Audit every panel for information the
   operator cannot act on; kill or fold it. Readout rows, not metric-card grids (§13).
2. **Explanation debt**: failures/recovery still not explained in the flow. The recovery story (detect →
   replan → reconfigure → recovered, who moved where and why) must be readable WHILE the sim runs.
3. **"Where is the model"**: the AI-risk overlay exists but is opt-in and quiet. It must be discoverable, and
   honest: display-only annotation, offline LightGBM, cut from the control loop (see §6).
4. **422 silent fallback**: if the backend rejects policy/predictor options, the run silently starts without
   them with one combined note (ScenarioBuilder.tsx:153-160). Make the degraded state visible and persistent,
   per option.
5. **Policy readout "unmeasured"**: frames echo `policy` only when ≠ hungarian; a hungarian run's readout shows
   "unmeasured" unless hello carried it (simStore.ts:96-100,131-134). The uncommitted tree fixes storage —
   verify, then make the readout always show the resolved policy (hello carries it for live runs).
6. **Three copies of fetch/error-format logic**: `api/backend.ts`, `api/scenarios.ts:12-64`, `runApi.ts:33-79`.
   Consolidate to one.
7. **Legacy parallel path**: `backend.simulationStart` still posts only `{scenario, seed}` (api/backend.ts:75-76).
   Route everything through the one start client with speed/policy/predictor.
8. **Role/task history truncates at 50 entries** (roleHistoryStore.ts:98-103) — long live runs lose the story.
   Raise sensibly or summarize; do not silently drop.
9. **Right-panel tab overflow at 1920×1080; tooltip clipping in scroll panels.**
10. **3-curve coverage comparison not built** (wire carries no reference runs) — the chart says so; keep that
    honesty, but make the "why" visible instead of a dead tab.
11. **Housekeeping**: dormant `uiStore.missionBriefOpen`; `.mimosa/` hook-state dirs littered inside
    `frontend/src` and `assets/fonts`; untracked scratch logs at repo root.
12. **Owed verification**: full test suite re-run + a real-browser render pass on EVERY page (never done since
    round 2). You owe both before you report done.

### 3.3 The 3D scene, specifically

The user demanded and got: Earth as a **procedural globe at the orbit center** ("stylized, not to scale"),
formation on the chief-orbit ring, starfield, prograde motion. Current state is close but still criticized.
Checklist: constant-screen-size markers at every zoom; labels never overlap at default camera; slot ghosts and
trails must not dominate; failure lines meaningful, not decoration; camera auto-fit frames the formation with
Earth context; reduced-motion honored; click-a-satellite → role/function + dynamic task history (this
interaction is a core demand, verify it end-to-end).

## 4. Future functionality we are adding — design for it now

The project roadmap (user-pinned, detailed in `docs/HANDOFF.md` §10). The UI does not build these yet, but it
must not paint itself into a corner — leave honest, structural room:

1. **CBBA decentralized coordination** — will sit beside Hungarian as a selectable recovery policy. Policy
   selection (and later side-by-side policy comparison) should be first-class in the builder, not a buried
   dropdown. Backend policies today: `hungarian | even_split | hungarian_keepout` (422 = not accepted).
2. **Realistic failure modes** — battery degradation, comms loss, OBC failure, partial thruster. ScenarioBuilder's
   failure list, status colors, and narration must tolerate failure modes beyond DEAD/THRUSTER_OUT without a
   redesign (render unknown modes honestly, never miscategorize).
3. **Monte Carlo robustness** — distribution charts (coverage/Δv across seeded runs), not just single-line
   telemetry. Today: single run only — do not fake batch UI; just don't hard-code "one run" assumptions.
4. **Continuous collision avoidance** — a separation monitor with evasion events will exist. EventLog/Timeline
   must render new event types generically.
5. **Larger swarms** — the sim core already supports N sats (`n_sats = len(roles)`). The scene, satellite list,
   and label declutter must not fall over at 20–50 sats (test with a generated scenario via the existing
   upload route).
6. **Communication-aware coordination** — link status/delay indicators will come; leave panel space, render
   "not modeled" honestly until then.
7. **Autonomous mission replanning** — objective trade-offs (coverage/fuel/safety/health) will become controls.
8. (Hardware-in-the-loop and high-fidelity dynamics are backend concerns; UI impact is honesty labels only.)

Rule: for any roadmap feature the backend does not serve yet, the honest state is an explicit "not available
on this backend" — the RiskPanel fallback pattern (`RiskPanel.tsx:63`) is the house style. Never simulate data.

## 5. Current state of the tree — protect the uncommitted work

11 frontend files are modified but uncommitted (+337/−100): scenario-draft validator clamp (BOUNDS mirrors the
pydantic constraints — fixes the altitude-min demo blocker), Earth-centred camera fit default, **simStore now
stores `policy`**, **frontend now sends `predictor`**, allocator WHY-line in RecoveryLog/NarrationStrip,
role-history cap, marker size bump. These fix real warts — start from this tree, do not revert, do not commit
(the user orchestrates commits; explicit paths only, never `git add -A`).

Architecture map (details in HANDOFF §7): one shared deserializer (`api/deserializer.ts`) → four Zustand stores
(simStore / recoveryStore / roleHistoryStore / historyStore) → pages via hash router (`uiStore.routeFromHash`;
Router globs `src/pages/*Page.tsx` — components elsewhere need one-line re-export slots). Scene lives in
`components/three/` (swarmScene controller + scene{Earth,Satellites,Labels,Slots,Camera,Lines,Colors}). Stack is
locked: React 18 + TS, Vite, plain Three.js (no R3F), CSS Modules + `tokens.css` (the only file with raw hex),
Zustand, Recharts, vendored IBM Plex. **No new dependencies without user sign-off.**

## 6. The wire is your only data source — its honest limits

`sim_state`: `type, sim_time, state, scenario, seed, [policy], sats[], coverage, min_sep, metrics{detection_latency_s, replanning_latency_ms}`.
`sats[]`: `id ("SAT-n"), role, status (healthy|failed), r, v (SI), dv_used, failure_type?, target_slot?, risk?`.

Honesty rules that are defects if violated:
- `replanning_latency_ms` is **always null** → render "unmeasured", never 0.
- `risk` appears only when the predictor is enabled; absent ≠ 0. It is a **display-only annotation** — never
  change status colors or trigger anything on it (FRONTEND_SPEC App D).
- `policy` echoes only when ≠ hungarian; hello carries it for live runs.
- THRUSTER_OUT arrives as `status:"failed"` with `failure_type` — the heartbeat detector never catches it in
  sim; do not imply autonomous detection (do-NOT-claim list).
- Events are never dropped by the backend; sim_state frames can be (30 Hz cap, drop-oldest). Design for gaps.
- Coverage numbers: Hungarian's MEAN gain vs do-nothing is negative (−2.13 pts); the win is worst-case
  protection (+4.93 pts). Never render a "recovery improves coverage" claim.

## 7. Design law (FRONTEND_SPEC §13 — binding, self-contained)

Industrial ops console. Neutral graphite background (`tokens.css`), color = semantic state ONLY (no decorative
accents). Raw hex ONLY in `tokens.css`. Banned: Inter/Roboto/Space Grotesk/Geist/system-ui, gradient text,
ALL-CAPS eyebrows, metric-card grids, glassmorphism, radius >8px panels, gradient chart fills, unexplained
icons. Charts: line style AND color, direct end labels. Motion 120–180 ms, reduced-motion honored. Unmeasured
numbers render the word "unmeasured". Sentence case everywhere. The signature element is the state-machine
timeline spine — build the console around it.

## 8. Gates — all must pass before you report done

1. `cd frontend && npm run build` (tsc + vite) — exit 0.
2. Hex gate: `grep -rn "#[0-9a-fA-F]{3,8}" frontend/src | grep -v styles/tokens.css` → empty.
3. avoid-ai-design scanner: `node detect.mjs frontend/src frontend/index.html` → exit 0 (clone
   `funboy322/avoid-ai-design` if no local copy; findings need inline `avoid-ai-design-ignore:` justification).
4. §13 review checklist: PASS = ≤1 miss per section, zero hard bans.
5. `uv run python -m pytest -q -m "not slow"` — green (use `python -m pytest`, NOT `uv run pytest`, which is
   spawn-blocked on this machine, os error 4551).
6. **Real-browser pass on every page** (`#/`, `#/live`, `#/replay`, `#/tutorial`, `#/faq`, `#/docs`) at
   1920×1080 against a running backend (`uv run uvicorn cubesat.api:app --port 8000`; rebuild + hard-refresh —
   browsers serve stale 304 bundles after rebuilds). Exercise: landing → build a custom scenario → live run →
   inject a failure → watch recovery → click a satellite → replay two_failure with seek. Screenshots or it
   didn't happen.
7. Full suite once at the end: `uv run python -m pytest -q` (123 tests; needs ~15 min).

## 9. Working method

- **Lazy senior dev discipline** (user's standing demand): smallest change that fully solves the task; use what
  the codebase already has; no speculative abstractions; deletion beats addition; every non-trivial change
  leaves the gates green. Proportional effort — don't gold-plate panels nobody looks at.
- **Tests/docs are law**: every displayed number needs a backend field behind it (invariant 1); update
  `docs/IMPLEMENTATION_NOTES.md` with a dated section for what you did; `GATES.md` only via the user.
- **Never commit**; stage nothing; report file lists for the user to commit.
- **Backend is read-only for you.** If the UI genuinely needs a wire field that doesn't exist (e.g. reference
  runs for comparison charts), STOP and write the request up — do not fork data logic client-side, do not
  touch `cubesat/` (the sim core G1–G4 is frozen; session/wire changes are the user's call).
- If §13 or the wire contract makes a user request impossible as stated, escalate with options instead of
  quietly violating either.
- Environment quirks: Windows/Git Bash; `world.run`-style tooling can't spawn `npm.cmd` → use
  `node <npm-cli.js> --prefix frontend ...`; pytest needs `python -m`; locator clicks time out against 30 Hz
  re-renders → use screenshot-coordinate clicks.

## 10. Deliverable

The repo's `frontend/` redesigned per §2, every item in §3.2 fixed or explicitly deferred with a one-line
reason, §3.1 verified non-regressed, all §8 gates green, a dated `docs/IMPLEMENTATION_NOTES.md` section listing
what changed and what was verified (with commands), and a file list for the user to commit. Report what you did
NOT check honestly — an honest gap beats a fabricated pass.
