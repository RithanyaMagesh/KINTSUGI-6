# Frontend hand-off, 2026-11-01

Branch `frontend`. Base: `origin/backend` at 2a4c57f (Block 0 rebase). No `wip/frontend` branch: every change builds and is on `frontend`; nothing is half-done.
Contract: `docs/frontend-requests.md` **on origin/backend** (the copy here is older; read `git show origin/backend:docs/frontend-requests.md`).

Gates at hand-off: `npm run build` green, `npm test` 16/16 (vitest, real captured frames), hex grep prints nothing, `tsc --noEmit` clean.

## a. State table

| Item | State | Files touched | Data | Known bugs |
|---|---|---|---|---|
| **Block 1 (catch-up)** | | | | |
| v2 statuses (REENTERED / FUEL_DEPLETED / RADIO_SILENT / PAYLOAD_FAILED, half thrust, stuck open) | done | `api/deserializer.ts`, `types/satellite.ts`, `components/live/hudFormat.ts` (`satLabel`, `faultLabel`), `FleetTable.tsx`, `SelectedSatellitePanel.tsx`, `SatelliteList.tsx`, `SpectatorBar.tsx`, `three/sceneSatellites.ts` | real | none known. Flying sats are amber (wire `degraded` → `--status-caution`), never grey |
| Fuel bars (fuel_kg / fuel_mps_left vs tank) | done | `components/live/SatBits.tsx` (`FuelBar`), `FleetTable.tsx`, `SelectedSatellitePanel.tsx` | real (tank = `dv_used + fuel_mps_left`, ≈20.12 m/s measured) | `fuel_kg` parsed and stored but not displayed (m/s is the budget unit) |
| Role batons / handoffs (roles[], original_role, ROLE_HANDOFF, role_handoffs) | done | `stores/simStore.ts` (`handoffs`, `soleHolder`), `three/swarmScene.ts` (`handoff()`, `updateBatons`), `three/SwarmScene.tsx` | real (derived from frame-to-frame sole holder of leader/downlink; covers v1 and v2) | Only leader and downlink get batons. Flight is 2.4 s; a headless check saw only the first frame (swiftshader too slow), so it was eyeballed once, not tested frame by frame |
| events[] (all entries, several per tick) | done | `api/deserializer.ts`, `stores/simStore.ts`, `events/EventLog.tsx` (already listed all, with "Show all") | real | none |
| payload/radio/stuck icons | done | `components/live/SatBits.tsx` (`SatFlags`) | real | v2 only (keys absent on v1 → icons hidden) |
| kept_formation label | done | `stores/simStore.ts` (`lastReassignment.keptFormation`), `stores/recoveryStore.ts`, `recovery/RecoveryLog.tsx`, `narration/NarrationStrip.tsx`, `live/TelemetryDrawer.tsx` ("Last replan" row) | real (v1 leader_failure t=2408) | none |
| run_summary card | done | `components/live/RunSummaryCard.tsx`, `LivePage.tsx`, `ImmersiveLive.module.css` | real | At 390 wide it sits behind the selected-satellite sheet when both are open |
| New inject modes + backend rules | done | `components/controls/FailureInjectionPanel.tsx`, `controls/injectRules.ts` (+test) | real | A v1 sat with a failure *scheduled later* in the scenario still looks selectable (frontend can't see the schedule); the backend's 409 text shows |
| **Block 2 (Track C)** | | | | |
| Laser beams | not started | – | wire exists on origin/backend (C6) | – |
| Leader-function chips + FUNCTION_HANDOFF | not started | – | wire exists (C6 part 2, decentral only) | – |
| Swarm-split view (components / split_brain) | not started | – | wire exists (C6) | – |
| Formation picker | not started | – | `hello.formation_shape` (v2 live only); numbers in `data/eval/formations_report.json` | ghost/deviation layer is cartwheel-only today (see c.) |
| Central vs decentral side by side | not started | – | numbers in `data/eval/comms_report.json` | – |
| **Block 3 (Tier 3)** | | | | |
| Decision card (ladder level, rejected, certificate) | not started | – | events defined (ladder chunk 1 merged on backend as ffc48b4); wire pass-through owned by backend T5 | – |
| Critical-roles vacancy timer | not started | – | `critical_vacancy_s` / `shadow` not on the wire yet | – |

## b. Wire → deserializer → store → component

✓ = link exists, ✗ = missing.

| Wire field | Deserializer (`api/deserializer.ts`) | Store | Component |
|---|---|---|---|
| `sats[].status` + `failure_type` (v2 values) | ✓ `status`, `failureType` | ✓ simStore.satellites | ✓ `satLabel` everywhere sats are listed |
| `sats[].fuel_mps_left` | ✓ `fuelMpsLeft` | ✓ | ✓ `FuelBar` |
| `sats[].fuel_kg` | ✓ `fuelKg` | ✓ | ✗ not shown |
| `sats[].k` | ✓ `thrust` | ✓ | ✓ "50% thrust" |
| `sats[].payload_ok` / `radio_ok` / `stuck` | ✓ | ✓ | ✓ `SatFlags` |
| `sats[].roles`, `original_role`, `old_role` | ✓ `roles`, `originalRole`, `oldRole` | ✓ | ✓ `rolesLabel`, "(was imager)"; `oldRole` ✗ not shown (handoffs come from `simStore.handoffs`) |
| `role_reassignment.role_handoffs` | ✓ | ✗ not stored directly (handoffs derived from frames, same result, tested) | ✓ batons |
| `ROLE_HANDOFF` event | ✓ (generic event + `satId`) | ✓ events | ✓ EventLog text; baton from frames |
| `role_reassignment.method`, `kept_formation` | ✓ | ✓ simStore.lastReassignment, recoveryStore.assignments | ✓ RecoveryLog, NarrationStrip, TelemetryDrawer |
| `role_reassignment.transfer_lower_bound_s` | ✓ (type only) | ✗ | ✗ |
| event `from` / `to` / `label` / `sat_id` | ✓ | ✓ | ✓ EventLog uses `message`; `label` ✗ unused |
| `run_summary` | ✓ kind `summary` | ✓ simStore.runSummary | ✓ RunSummaryCard |
| `links` | ✗ | ✗ | ✗ |
| `components` | ✗ | ✗ | ✗ |
| `sats[].functions`, `consensus_rounds`, `split_brain`, `functions_vacant` | ✗ | ✗ | ✗ |
| events `LINK_LOCKED` / `LINK_LOST` / `PARTITION` / `FUNCTION_HANDOFF` / `FAILURE_DETECTED{cause:isolated}` | message only (generic event); ✗ extras `link`, `reason`, `components`, `function`, `cause` | events only | EventLog text only |
| `hello.formation_shape` | ✗ | ✗ | ✗ |
| events `MISSION_STATE` / `RECOVERY_LEVEL` / `CERTIFICATE` | message only; ✗ extras | ✗ | ✗ |
| `chief` / `station` / `hello.orbit_ring` etc. (Earth view data) | ✗ (pre-existing gap, not in this block) | ✗ | ✗ |

## c. Exact next steps

General: run backend from origin/backend (`uv run uvicorn cubesat.api:app --port 8000`), frontend `cd frontend && ./node_modules/.bin/vite --port 5173`. Capture fresh fixtures the way `src/test/fixtures/README.md` describes, write the deserializer test first (`api/deserializer.test.ts` pattern), then store, then component.

1. **Laser beams** (contract § "Track C — C6 wire", item 1).
   - Deserializer: add `links?: Array<{a,b,state,rangeM,rateBps}>` and `components?: string[][]` to `SimFrame` (`types/telemetry.ts`) where the deserializer builds frames; `null` range/rate stays `null` → show "unmeasured".
   - Store: `simStore` keeps `links`, `components` (reset on INIT frame like `handoffs`).
   - Component: new `components/three/sceneLinks.ts` (pattern: `sceneLines.ts` FormationLines, reuse one LineSegments, write into a typed array). LOCKED solid `--status-nominal`, ACQUIRING dashed `--status-caution`, DOWN hidden or faint `--ink-faint`. Wire into `swarmScene.ts` next to `this.lines.update`. Hover text: range, rate, "acquisition time 30 s (assumption)".
   - Test: run a laser scenario from origin/backend (`data/scenarios/decentral_leader_kill_6sat.json` / the central star one, C6), expect beams between talking sats, beams dropping at the sun twice per orbit.
2. **Leader-function chips + FUNCTION_HANDOFF** (contract § "C6 wire part 2", item 3).
   - Deserializer: `sats[].functions` → `Satellite.functions?: string[]`; frame `consensusRounds`, `splitBrain`, `functionsVacant`; event extras `function`, `from[]`, `to[]`.
   - Store: derive chip handoffs like `simStore.handoffs` (or from FUNCTION_HANDOFF events; they come in bursts, animate together).
   - Component: chips as DOM labels in `three/sceneLabels.ts` next to each sat, or a strip in `TelemetryDrawer` Mission tab; flying chips reuse `swarmScene.handoff()` (give it a label). Six names in plain words: detection, time sync, formation reference, collision arbitration, scheduling, ground relay. Show "N rounds", say "consensus auction".
   - Test: `decentral_leader_kill_6sat.json`, kill the first holder, expect several chips to move at once.
3. **Swarm-split view** (item 2, C6 `components`).
   - Uses `components` from step 1. Tint markers per component (status colours stay status; use outline/halo only, colour = state law), banner "Swarm split into N groups" in `NarrationStrip`/`HudTopBar`; `split_brain` non-empty → name the functions with two holders. `FAILURE_DETECTED{cause:"isolated"}` → new label "Cut off" in `satLabel` (not "Lost").
4. **Formation picker** (§ "Track C — C3 additions").
   - Deserializer: `hello.formation_shape`. Store: `simStore.formationShape` (null = unknown).
   - Builder: add a `shape` select to `components/live/ScenarioBuilder.tsx` + `scenarioDraft.ts buildScenario` (`formation.shape`, and `engine: "v2"` when not cartwheel; v1 gives 422).
   - Before anything else: turn the ghost slots / deviation layer off when shape ≠ cartwheel or unknown on v2 (`utils/geometry.ts fitFormation`, `three/sceneSlots.ts`, `swarmScene.ts` `this.slots.update`).
   - Numbers only from `data/eval/formations_report.json` (`shapes.<shape>`), label "planning model (CW), L1 upper bound"; helix-only drift-safety note; coverage-loss badge for helix/string.
   - Test: `data/scenarios/formation_helix_6sat.json` → no bogus km deviation, no cartwheel ghosts.
5. **Central vs decentral side by side** (item 5).
   - New page or tab reading `data/eval/comms_report.json` (static import or a backend endpoint request: file it in docs/frontend-requests.md, do not read repo files at runtime). Show vacancy / split-brain / rounds per cell with the round-time sensitivity rows, never a bare ranking.
6. **Decision card** (§ "Recovery ladder"): needs backend T5 to pass `RECOVERY_LEVEL` / `CERTIFICATE` extras through `cubesat/wire.py`; then deserialize event extras, store latest pair, card in `TelemetryDrawer` or above `NarrationStrip`. Add new mission states (`PLANNING`, `DEGRADED_MISSION`, `MISSION_LOST`) to `hudFormat.STATE_LABEL` and `utils/colors.ts`.
7. **Vacancy timer**: blocked on `critical_vacancy_s` / `shadow` on the wire (contract line 14-15). Interim: compute live vacancy from `simStore.roleHolders` (time since leader/downlink had no live holder) and label it "measured in the console".

## d. Rebase status vs origin/backend

- `frontend` = origin/backend 2a4c57f + frontend commits (merge commit 93f5b14 records old frontend history with `-s ours`; tree unchanged). Outside `frontend/` this branch differs from 2a4c57f only by 3 lines appended to `docs/frontend-requests.md` (request: `min_sep_m` on hello/start).
- origin/backend has moved on to d65c562 (C5/C6, ladder chunk 1, hand-off docs). None of those commits touch `frontend/` → **merging origin/backend into frontend is expected to be conflict-free**, except possibly `docs/frontend-requests.md` (both sides appended; keep both).
- MAX_SATS: backend keeps 32 (`cubesat/scenario_models.py:24`); builder cap matches (`components/live/scenarioDraft.ts` `MAX_SATS = 32`, options up to 32).
- scenario.py / allocate.py: the earlier 50-sat / vectorised-planner / `min_sep_m` edits were **dropped** in the Block 0 rebase. This branch carries no backend code changes; nothing for the backend to refuse. The `min_sep_m` request stands in docs/frontend-requests.md.
- Force-push is blocked by policy here; sync with merge, not rebase.

## e. Design-law checklist (FRONTEND_SPEC §13)

- [x] Hex grep `grep -rnE '#[0-9a-fA-F]{3,8}' src | grep -v styles/tokens.css` prints nothing (fixtures are JSON, outside the grep's hits).
- [x] Colour = state only: fuel bar green/amber/red by fuel state, muted for lost sats; icons red only when that part failed; baton gold = repair.
- [x] "unmeasured" for missing numbers (run summary coverage/time, selected-sat distance).
- [x] Widths checked: 1920 (fleet, selected, summary, inject), 1366 (fleet + summary), 390 (fleet, selected + summary).
- [ ] 390: run-summary card hidden behind the selected-satellite sheet when both are open.
- [ ] Perf items 1-10 in the contract: not done; baseline unmeasured.

## f. Screenshots

`frontend/handoff-shots/`:
- `v2-fleet-table-1366.png`, `v2-fleet-table-390.png`: status causes, icons, fuel bars, stacked roles (v2 run with all four v2 faults + a DEAD).
- `v2-selected-sat-and-run-summary-1920.png`, `v2-selected-and-summary-390.png`: "Leader (was imager)", fuel bar, end-of-run card.
- `role-baton-in-flight.png`: gold baton crossing to the new leader.
- `inject-panel-v1-1920.png`, `inject-panel-v2-1920.png`: v1 offers 3 faults, v2 offers 7; refused satellites greyed out.
