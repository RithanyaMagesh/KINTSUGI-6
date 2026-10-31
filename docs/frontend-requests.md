# Requests for the frontend owner (branch `frontend`)

Written by the backend session (2026-10-31). The backend session does not edit `frontend/`; this file is the hand-off. Sources: docs/superpowers/specs/KINTSUGI-6_replan_and_judge_kit.md §3 and §5, master map §11, docs/audit/2026-10-31-a.md, docs/audit/2026-10-31-frontend-claims.md (25 stale-claim rows with replacements).

## Today (kit §4)
1. **Clamp the ScenarioBuilder to 32 satellites.** Conflict to resolve: `origin/frontend` raised the backend `MAX_SATS` to 50 (`cubesat/scenario.py`, with a vectorised `allocate._min_separation_ok`); `backend` keeps 32. Backend will adopt whichever limit the two sessions agree on when they merge; until then the builder cap and the backend cap must match.
2. **Remove** the Mission Health score (`utils/health.ts`, `MissionHealthScore`) and the frontend "anomaly advisor" (`utils/suspect.ts`): invented weights and thresholds (master map §11.3).
3. **Copy:** no file paths, spec refs, "invariant", enum names or "allocator/Hungarian" in primary UI; THRUSTER_OUT text must say the satellite reports it and the swarm replans (it does).
4. **Per-sat Δv as % of budget**, pass/fail colour. Backend will add `dv_pct_of_budget` fields to benchmark rows; the live wire already carries `dv_used` per sat and `allocation.dv_budget_mps` is in the scenario.
5. **422 must fail loudly:** `POST /simulation/start` returns 422 with a message for an invalid policy/predictor; the UI currently starts anyway without them. Show the error and do not start.
6. Fix the stale numbers listed in docs/audit/2026-10-31-frontend-claims.md (FAQ, Docs, tooltips, chart captions).

## Next (needs backend data that does not exist yet)
- State banner, critical-roles card with a live vacancy timer, **"without recovery" twin value from `shadow`** (backend will send `shadow: {critical_vacancy_s, coverage, roles_held}` once the stepping engine exists), decision card (ladder level, rejected options, certificate), formation lens, gold-means-repaired seams (`--hero-gold`).
- Wire fields to expect (all optional): `roles_held`, `critical_vacancy_s`, `mission_state`, `t_since_failure`, per-sat `fuel_left_mps`/`fuel_budget_mps`/`soc`/`mode`, `events: []`, ASSIGNMENT `method`/`formation`/`plan_samples`/`level`/`rejected`/`certificate`.


## Wire additions (2026-10-31)

All additive and optional: no existing key, value or message changed meaning, and the shipped deserializer ignores unknown message types (`run_summary`) and drops unknown fields. Two existing event texts changed on purpose (audit A-10, bare type names replaced by sentences): `DEGRADE_START` (also `level` info -> warning) and `ORACLE_SWAP`; `ORACLE_ALERT` too. Examples are from `eps_leader_6sat` and `leader_failure_6sat` (seed 42). Source: `cubesat/wire.py`, pinned in `tests/test_wire.py`.

**`role_reassignment` (from sim event `ASSIGNMENT`)**: `method` (`hungarian` | `greedy` | `do_no_harm_hold` | `even_split` ...), `formation`, `transfer_lower_bound_s` pass straight through; `kept_formation` is `true` iff `method == "do_no_harm_hold"` (say "kept formation, no move" instead of "re-plan"). All four absent when the payload has no `method`.
```json
{"type": "role_reassignment", "sim_time": 2408.0, "assignments": [...], "cost_total": 0.0,
 "method": "do_no_harm_hold", "formation": {"phase_offset_rad": 0.0, "radial_amp_m": 8000.0},
 "transfer_lower_bound_s": 0.0, "kept_formation": true,
 "role_handoffs": [{"role": "leader", "from_sat": "SAT-1", "to_sat": "SAT-3"},
                   {"role": "downlink", "from_sat": "SAT-6", "to_sat": "SAT-5"}]}
```

**`role_handoffs` (on `role_reassignment`)**: derived by the wire from the previous frame, no sim change. Only for roles with one live holder (leader, downlink); `from_sat` is the last sole live holder, even if it is now dead. Absent when no role moved.

**`sats[].old_role` (on `sim_state`)**: the sat's role in the previous frame, present only on the tick its role changed. Absent on the first frame of a run and on the first frame after a backwards seek.
```json
{"id": "SAT-3", "role": "leader", "old_role": "imager", "status": "healthy", "...": "..."}
```

**`run_summary` (new message type, from the `SUMMARY` log line)**: sent just before the unchanged `"Run complete"` event, which stays the last message.
```json
{"type": "run_summary", "coverage_mean_last_orbit": 0.2698, "sim_time": 17028.0, "scenario": "two_failure.json", "seed": 42}
```

**`event` additions**
- `STATE` events keep their text and gain `from`, `to` (raw enum strings) and `label` for the narrated transitions only. The sim emits `STATE` for FAILURE_DETECTED -> REPLANNING and RECONFIGURING -> RECOVERED; REPLANNING -> RECONFIGURING has no `STATE` event (it is the `ASSIGNMENT` tick), so use the `role_reassignment` as that cue.
```json
{"type": "event", "sim_time": 2406.0, "level": "info", "message": "State FAILURE_DETECTED -> REPLANNING",
 "from": "FAILURE_DETECTED", "to": "REPLANNING", "label": "Planning recovery"}
```
  Labels: "Planning recovery", "Moving to new positions", "Recovered". Other transitions: text only.
- `DEGRADE_START`: `{"level": "warning", "message": "SAT-1 battery fading; failure expected at T+30:00", "sat_id": "SAT-1"}` (countdown is `t_fail - sim_time`, mm:ss; omitted if `t_fail` is missing).
- `ORACLE_SWAP`: `{"level": "info", "message": "SAT-1 leader role handed to SAT-2 because its battery is fading", "sat_id": "SAT-1"}`; oracle mode reads "... handed to SAT-2 before SAT-1 fails". `sat_id` is the holder giving the role up.
- `ORACLE_ALERT`: `{"level": "info", "message": "Early warning: SAT-4 expected to fail in 10:00; replanning early", "sat_id": "SAT-4"}`.
- `sat_id` (`"SAT-n"`, optional) is also on `FAILURE_DETECTED` and `EVASIVE_MANEUVER` events (the evading sat). Absent when the payload carries no usable id. Events for no specific satellite (STATE, Run complete) have none.
- `recoveryStore.ts` line ~198 looks for "ORACLE_SWAP" in the message text and then reads `payload.from_sat`; the wire event has no `payload`, so that handler was already inert and still is. Consume `sat_id` and the sentence instead.

Not changed: `metrics.replanning_latency_ms` (still `null`; the client reads it as optional, so removal is safe once the frontend stops expecting it, but it was not touched here).

## Earth view (user spec 2026-10-31, docs/superpowers/specs/KINTSUGI-6_earth_view_spec.md)
Frontend items 1-6 of that spec are for the frontend session (load the frontend-design skill; `lvlhToScene()` "global" mode is to be deleted; formation = one cluster dot on the orbit ring + a Formation lens inset; constellation mode with per-plane rings; time-warp badge; failed red / in-transit amber / healthy green / repaired gold only; hex only in tokens.css; reduced motion; 60 fps at 1920x1080, check 1280x720; visual QA screenshots).
Backend data they depend on (the backend session builds it, in this order; fields are optional/additive): (1) every `sim_state` gets `chief: {r_eci, lat_deg, lon_deg, alt_m}`, hello gets `epoch_utc`, `inclination_deg`, `raan_deg`, `orbit_ring` (256 ECI points of one chief period) and `ground_track` (lat/lon over +-1 orbit); (2) later, constellation layout with per-sat `r_eci`. Frontend steps 1-3 (formation mode) need backend item 1 only; step 4 (constellation) needs backend item 2.

## Earth view data (2026-10-31)

Backend item 1 of the Earth-view spec, engine v2 runs only (live). Everything is additive and optional: engine v1 runs, replays and every committed log keep their exact bytes, so absent keys mean "no globe data, fall back". Source: `cubesat/geo_v2.py`, wire in `cubesat/wire.py` and `Session.hello()`, pinned in `tests/v2/test_earth_wire.py` and `tests/v2/test_earth_tick.py`.

**Frames and units.** ECI, metres, z = Earth rotation axis, x = vernal equinox direction (precession/nutation ignored). Per-sat `r`/`v` stay LVLH, unchanged. `lat_deg`/`lon_deg` in degrees, longitude in [-180, 180], east positive. `alt_m` above a spherical Earth of radius 6378.137 km (no flattening: up to ~0.2 deg latitude difference against a real ellipsoid, same model as `cubesat/ground.py`).

**hello additions (v2 live runs only)**, computed once per run, about 14.8 kB of JSON:
```json
{"type": "hello", "mode": "live", "scenario": "two_failure.json", "seed": 42, "sim_time": null, "skipped": 0, "policy": "hungarian",
 "epoch_utc": "2026-03-20T12:00:00Z", "inclination_deg": 97.4, "raan_deg": 0.0,
 "orbit_ring": [[6878137.0, 0.0, 0.0], [6876062.542, -21740.427, 167391.971], "... 256 points, ECI m, one chief period from t=0"],
 "ground_track": [[-2.7891, 2.5137], [0.0, 1.9658], [2.7891, 1.418], "... 257 [lat_deg, lon_deg] samples, t = -1 period .. +1 period, index 128 is t = 0"],
 "sun_vector_eci": [0.999998, -0.001749, -0.000758],
 "ground_station": {"name": "Bengaluru", "lat_deg": 13.03, "lon_deg": 77.51, "min_elevation_deg": 10.0}}
```
`orbit_ring[k]` is the chief at t = k * T / 256 (T = 2 pi / n, 5677.0 s at 500 km). The ring is the engine's own chief trajectory (gravity + J2, no drag), so it does NOT close exactly: the end of one period is 32.5 km from the start (J2 nodal-period phase drift). Draw it as an open loop of 256 points, or close it visually with a line back to point 0. `time_warp`: not sent, there is no existing hello field for it; the speed is the one you set via `/simulation/speed` and the start response.

**sim_state additions (every v2 tick, about 160 bytes)**:
```json
{"type": "sim_state", "sim_time": 1500.0, "...": "...",
 "chief": {"r_eci": [-614967.24, -882850.85, 6786655.15], "lat_deg": 80.99, "lon_deg": -129.16, "alt_m": 493274.68},
 "station": {"elevation_deg": -40.2, "visible": false}}
```
`station.visible` is true while the chief is at least `ground_station.min_elevation_deg` above the Bengaluru horizon: show the visibility cone only then. The station moves with the Earth, so place it from `ground_station` lat/lon on the rotating globe.

**Rotating the Earth.** Earth-fixed to ECI rotation about +z by GMST(t) = GMST(epoch) + 7.2921159e-5 rad/s * sim_time. The frontend needs GMST at the epoch: `gmst0 = (280.46061837 + 360.98564736629 * d + 0.000387933 * (d/36525)^2) deg` with `d` = days from 2000-01-01T12:00:00Z to `epoch_utc` (IAU-1982, UT1 = UTC). Rotate the globe mesh (texture with longitude 0 on +x at GMST = 0) by `gmst0 + 7.2921159e-5 * sim_time` about the z axis. A point at (lat, lon) sits at ECI angle lon + GMST. For lighting, `sun_vector_eci` is fixed at the epoch (the sun moves 1 deg/day: at most 0.07 deg over a one-orbit-day run, so keep it constant for a run). Use the sat positions in ECI: chief `r_eci`; satellites = chief + LVLH offset rotated by the LVLH basis (x radial, y along-track, z cross-track), or simply draw the formation as one cluster at `chief.r_eci` as the spec says. The `ground_track` is Earth-fixed (lat/lon at the sample times), draw it on the surface without rotating it with sim time.

Simplifications: spherical Earth, UT1 = UTC, constant rotation rate, sun direction from the low-precision almanac formula (about 0.01 deg), no precession/nutation, replays of v2 logs carry the per-tick keys but no hello extras (the hello needs the scenario).


## Wire additions: v2 statuses, fuel keys, events (2026-10-31)

All additive and v2-only: a v1 run never carries a v2 status, key or event, and its wire bytes are unchanged (checked on `nominal` and `two_failure` logs). Source: `cubesat/wire.py`, `cubesat/session.py`; pinned in `tests/test_wire_v2.py` and `tests/v2/test_inject_v2_modes.py`.

**Frontend owner: render these statuses.** Every v2 status now maps to one the UI already knows, so no satellite arrives as an unmapped uppercase string. Draw `degraded` amber (the satellite is still flying). `failure_type` keeps the raw status for the label.

| raw log status | wire `status` | meaning |
|---|---|---|
| `NOMINAL` | `healthy` | unchanged |
| `DEGRADED` | `degraded` | unchanged (EPS fade, partial or stuck-open thruster) |
| `DEAD`, `THRUSTER_OUT` | `failed` | unchanged |
| `REENTERED` | `failed` | burnt up; the sat shows its state at re-entry |
| `FUEL_DEPLETED` | `degraded` | flies and images, cannot maneuver |
| `PAYLOAD_FAILED` | `degraded` | flies, cannot image |
| `RADIO_SILENT` | `degraded` | flies, silent |

Any other future status still passes through unchanged.

**`sats[]` keys (on `sim_state`, only when the log carries them, so absent for v1):** `fuel_kg` (propellant left, kg), `fuel_mps_left` (delta-v left, m/s), `k` (thrust health, 1.0 full, 0.5 half, 0 none), `payload_ok` (camera works), `radio_ok` (heartbeat works), `stuck` (thruster stuck open).

**v2 events** (all carry the optional `sat_id`, `"SAT-n"`; a missing or odd payload falls back to "A satellite"):

| source | level | message |
|---|---|---|
| `FAILURE_DETECTED`, mode `PAYLOAD_FAIL` | warning | `SAT-n camera failed; it keeps flying but can no longer image` |
| `FAILURE_DETECTED`, mode `RADIO_FAIL` | warning | `SAT-n lost its radio; it keeps flying but is silent` |
| `FAILURE_DETECTED`, mode `THRUSTER_STUCK_OPEN` | critical | `SAT-n thruster stuck open; it is burning fuel it cannot control` |
| `FAILURE_DETECTED`, mode `PARTIAL_THRUST` | warning | `SAT-n lost half its thrust` |
| `FAILURE_DETECTED` mode `FUEL_DEPLETED`, and the `FUEL_DEPLETED` event | warning | `SAT-n ran out of propellant and can no longer maneuver` |
| `FAILURE_DETECTED` mode `REENTRY`, and the `REENTRY` event | critical | `SAT-n re-entered the atmosphere` |

The v1 modes (`DEAD`, `THRUSTER_OUT`, `EPS_DEGRADE`) keep their wording and `critical` level. The engine logs the fuel-out report twice (`FAILURE_DETECTED` and `FUEL_DEPLETED`) with the same sentence; the wire sends it once.

**Several events on one tick (v2 only).** A v2 log line carries `events` (a list) beside `event` (its first entry). When `events` has more than one entry the wire emits one `event` message per entry, in order, then any `role_reassignment`; with one entry, or only `event`, nothing changes. v1 lines never carry `events`, so the rule never applies to them. Every `event` message needs to be shown, not just the first per `sim_time`.

**`POST /failure/inject` modes.** `mode` also accepts `PAYLOAD_FAIL`, `PARTIAL_THRUST`, `THRUSTER_STUCK_OPEN`, `RADIO_FAIL`, only while the running scenario uses engine `v2`; otherwise 422 `failure mode X requires engine "v2"; the running scenario uses engine "v1"`. On v2 a satellite that lost only a resource (camera, radio, thrust) can take another injection; 409 `SAT-n is already dead` / `already scheduled to die` / `has already re-entered` for a dead or re-entered one. The v1 rule (one failure per satellite) is unchanged. A v2 injection takes effect on the next tick, so its event appears in the first message after the one already streamed.

## Roles (2026-10-31, engine v2 only; v1 sats are unchanged)

Source: `cubesat/roles_v2.py`, `cubesat/sim_v2.py`, `cubesat/wire.py`. All additions are optional and additive: v1 logs and v1 wire fixtures are byte-identical.

**Per-sat keys on `sim_state.sats[]` (only when the log carries them):**
- `roles` (list of strings, truth): every role the sat holds, in fill order (`downlink`, `imager`, `leader`), or `["spare"]` for a capable sat with nothing to do, or `[]` for a dead or incapable sat. A sat may hold several (the leader stacks on an imager; a lone survivor holds all three).
- `role` (string, display label, unchanged key): the first of `roles` in the FIXED display order `leader`, `downlink`, `imager`, then `spare`; `"none"` when `roles` is empty. A stacked leader therefore shows `leader`. Read `roles` when you need to know whether a sat images: a sat labelled `leader` may also be an imager.
- `original_role` (string): the scenario label, for display ("was imager"). A second sat labelled `downlink` in a scenario keeps `original_role: "downlink"` and shows `spare`.
- Labels the UI must now render: `"none"` (grey "no role") and `"spare"` ("spare"). v1 never sends them.

**A dead or radio-silent sat keeps its `roles` for a few ticks** (until the heartbeat declares it, 4 s with K = 3 and dt = 2 s) and then shows `[]` / `"none"`; `status` is already `failed` during that window.

**Event `ROLE_HANDOFF` (level `info`, optional `sat_id` = the old holder):** emitted only when the leader or the downlink changes holder, in the same tick as the `FAILURE_DETECTED` that caused it. Sentences: `SAT-1 leader role handed to SAT-2 because SAT-1 failed` (other reasons: `lost its radio`, `re-entered the atmosphere`, `lost its camera`, `lost its thruster`, `ran out of propellant`; an unknown reason drops the clause); `SAT-1 failed; the leader role is now vacant (no capable satellite is left)`; `SAT-4 took over the vacant leader role`. The wire's `role_handoffs` (inside `role_reassignment`) now also fires for a role gained by a sat whose display label did not change.

**Frontend files that read `sat.role` (found by the reviewer; none needs a change to keep working, each should decide whether it means "display label" or "holds imager"):** `sceneSatellites.ts:245,289,293`, `LeftPanel.tsx:66`, `SelectedSatellitePanel.tsx:19,117,169,228,251`, `SatelliteList.tsx:83`, `AllocationFan.tsx:75,212,216`, `sceneSlots.ts:144`, `roleHistoryStore.ts:147,215`, `simStore.ts:133`, `types/satellite.ts:22`, `events.ts:36,71`.

## Track C (2026-11-01, branch `comms`): later, NOT now
Backend fields arrive with plan steps C2–C6 (`docs/superpowers/plans/2026-11-01-track-c-plan.md`). Nothing exists on the wire yet; build none of this until C6 lands.
1. **Laser beams.** Draw a line per link: `links: [[i, j, state, range_m, rate_bps]]`, styled by state LOCKED / ACQUIRING / DOWN. Optional moving dots along LOCKED beams for data flow. Hover shows range, rate and "assumption" for the acquisition time.
2. **Partition view.** When `components` has more than one entry, tint each component and show a "swarm split" banner. When `split_brain` is non-empty, say which functions have two holders.
3. **Leader functions as chips.** Six chips (detection, time sync, formation reference, collision arbitration, scheduling, ground relay) sit on their holder. On `FUNCTION_HANDOFF` they fly to the new holder (same idea as the role batons). Show `consensus_rounds` as a count, not seconds.
4. **Formation picker.** Dropdown: cartwheel / PCO / GCO / helix / string (`formation.shape`). Show ghost target slots plus the one-orbit relative path, and the Δv to switch per sat against the tank, from `data/eval/formations_report.json` (C3).
5. **Side-by-side demo.** Central (star) vs decentral (mesh) on the same leader kill. The vacancy and split-brain numbers come only from `data/eval/comms_results.json` (C5).
6. **(C2 landed in the log, not yet on the wire.)** v2 laser runs carry `links: [[i, j, state, range_m, rate_bps]]` and `components` on every tick, and events `LINK_LOCKED{link}`, `LINK_LOST{link, reason: partner_down | budget | sun | replan}`, `PARTITION{components}`. A healthy sat that nobody can hear gets `FAILURE_DETECTED{cause: "isolated"}`: show it as "cut off", not "failed". Expect the sun to split the default ring twice per orbit (GATES.md C2): the UI should show that honestly.

### Track C — C3 additions (2026-11-01, branch `formations`; backend only, build later)
- `formation.shape` is a scenario field now (`cartwheel` default; `pco`, `gco`, `helix`, `string` need `engine: "v2"`, v1 returns 422). The picker (item 4 above) can write it straight into the uploaded scenario. Ready-made examples: `data/scenarios/formation_<shape>_6sat.json`.
- Per-shape numbers for the picker come only from `data/eval/formations_report.json` (`shapes.<shape>`): `cw_min_sep_m`, `cw_worst_sep_any_along_track_drift_m`, `cw_coverage`, `hold_dv_per_orbit_max_sat_mps`, `switch_from_cartwheel.per_sat[].dv_l1_mps` (bar per sat against the 20.12 m/s tank; label "planning model (CW), L1 upper bound").
- Show the drift hazard honestly: only `helix` keeps a non-zero separation under any along-track drift of a dead sat; every other shape shows 0 m there ("a drifting dead sat can reach a neighbour").
- Coverage loss badge for `helix` and `string` (lower than cartwheel in the report).
- Blocker for the picker: `frontend/src/utils/geometry.ts` (`ellipsePoint`, `fitFormation`) rebuilds ghost slots and deviation by fitting the cartwheel (z = x amplitude); a pco/gco/helix/string run would show wrong ghosts and km-scale bogus deviation (string has x = z = 0). The shape is not on the wire yet (needs a backend field, C6); until then turn the ghost/deviation layer off for non-cartwheel runs.

## Performance (2026-11-01)

Source: the read-only frontend audit in `docs/audit/2026-11-01-perf.md` section 8 (backend measurements in `data/eval/perf_baseline.json`, command in GATES.md "perf baseline (2026-11-01)"). Nobody ran a browser for this audit, so every cost below is "unmeasured" unless a backend number is quoted; step 0 is to measure (Chrome Performance, 30 s of live at speed 100, report long tasks and fps) before changing anything. These are requests to whoever owns `frontend/`; the backend session changed nothing there.

What the backend delivers, so the console can size its work: at most 30 `sim_state` frames per second (the emit cap), 1.5-5.2 KB per frame for 6-24 satellites on engine v1 and 2.7-9.3 KB on engine v2 (the larger v2 frame carries `chief`, `station`, roles and fuel keys), events never dropped. At speed 60 the real rate is 19.5 frames/s, at 1000 it is 29.2 frames/s (two_failure, measured over a socket).

1. **Throttle store writes to animation frames.** Every frame replaces `satellites` and `metrics` with new objects (`simStore.ts:140-150`), so about 15 components that select them re-render at the frame rate (`TopStatusBar.tsx:82-87`, `LeftPanel.tsx:30`, `RightPanel.tsx:52-53`, `SatelliteList.tsx:18`, `NarrationStrip.tsx:231-233`, `RoleTable.tsx:21-22`, `AllocationFan.tsx:23-26`, others). Keep the latest message in a ref, write to the store once per `requestAnimationFrame`, and keep the 3D scene on the ref. Cost: unmeasured.
2. **Parse once, not three times.** `useWebSocket.ts:65-67` hands the same parsed message to three stores and each calls `deserializeMessage` (`simStore.ts:87`, `recoveryStore.ts:213`, `roleHistoryStore.ts:121`), each rebuilding the satellite array with `map` + `filter` (`api/deserializer.ts:102-104`). Deserialize once in the hook and pass the result. Cost: unmeasured.
3. **Do not re-run the scene sync every animation frame.** In the default global orbit view `animate()` calls `fitFormation` + `syncAllObjects` (which also runs `lines.update` and `slots.update`) on every rAF, on data that changes at most 30 times a second (`swarmScene.ts:405-414`, `208-241`). Sync on new data or when the orbit phase actually moves the markers; the per-record `satellites.some` dispose check (`swarmScene.ts:223`) can be a set lookup. Cost: unmeasured (up to 60 Hz of work on 30 Hz data).
4. **Reuse Three.js geometries and materials.** Each satellite builds six geometries and six materials, identical across satellites (`sceneSatellites.ts:122-170,208-221`): 144 + 144 objects at 24 satellites. Create the circle, ring, leader ring, cross and drift geometries once and share them; clone materials only where the colour or opacity differs per satellite. Cost: unmeasured.
5. **Stop allocating in the per-frame paths.** `lines.update` allocates two 3-tuples per satellite pair through `lvlhToScene` (`sceneLines.ts:42-66`, `sceneSatellites.ts:58`): 552 small arrays per call at 24 satellites; `pushTrail` allocates a `THREE.Color` per satellite per push and recolours up to 220 vertices every 150 ms (`sceneSatellites.ts:343-378`). Write into the existing typed arrays; recolour only the new vertex and use a shader or a vertex-colour gradient fixed at creation. Cost: unmeasured.
6. **Render beams and labels only when changed.** `syncSatellite` writes `style.color`, `borderColor` and `fontWeight` of every label on every sync (`sceneSatellites.ts:315-317`), and `updateLabels` rebuilds its item array each animation frame (`swarmScene.ts:303-325`). Compare with the last written value first; run declutter only when the camera or the label set changed. Cost: unmeasured.
7. **Decimate chart history and stop DvChart re-rendering at frame rate.** Four charts read only `historyStore` (2 Hz sampling, `historyStore.ts:61,76`) and so re-render at 2 Hz; `DvChart` also selects `satellites` and rebuilds `data` (up to 900 points x all satellites) and `series` on every frame (`DvChart.tsx:24-29`), which Recharts then lays out again. Take the series keys from the history samples (or memoize on the satellite id list) and the data from a memoized slice. Decimate to at most 600 points (stride or LTTB) as the master map L3 asks, and pass a stable `data` reference to `TelemetryChart` (`TelemetryChart.tsx:76-77`). Cost: unmeasured; this is the one confirmed instance of audit A-17 by code reading.
8. **Keep `historyStore` bounded (it already is): 900 samples, 24 markers (`historyStore.ts:28-29`); `push` copies the whole array at 2 Hz (`:48-52`).** Use a ring buffer instead of `[...samples, sample].slice(-900)` if the cost shows up in the profile. Other caps hold: events 200 (`simStore.ts:13`), role history 250 per satellite (`roleHistoryStore.ts:102`), recovery phases 48 (`recoveryStore.ts:45`). Memory: unmeasured. Separate correctness item: the history only resets on events 1 -> 0 (audit A-5).
9. **Show what is decimated.** At speed 1000 the console receives one frame per about 17 ticks (30 Hz cap) and at speed 60 irregular spacing; the time axis and the "frames received" readout should come from `sim_time`, never from a frame count. Cost: none; this is a labelling request.
10. **Ask for a measured budget before the L3 pass.** Target from the master map: 60 fps at 1920x1080, no long task above 50 ms. Baseline: unmeasured. Bundle size (audit A-18, one 1.28 MB chunk) and gzip (audit B-21) are separate and also unmeasured on the wire.

7. **(C4 landed in the log, not yet on the wire.)** With `recovery.authority = "decentral"` no sat holds `leader`; per-sat `functions`, top-level `consensus_rounds` (a count), `split_brain`, `functions_vacant`, and `FUNCTION_HANDOFF{function, from: [ids], to: [ids]}` (lists: in a partition each component has its own holder). Show a vacant function as an empty chip slot, split-brain as one chip per holder with a warning.

### Track C — C6 wire (2026-11-01, branch `evidence`; backend only, build later)
Source: `cubesat/wire_comms.py` (hooks in `cubesat/wire.py`), `cubesat/geo_v2.py`. Everything is additive: v1 and non-laser v2 streams are byte-identical (wire sha256 of `data/logs/*.jsonl` and a v2 ideal-comms run unchanged).
- **`sim_state.links`** (laser runs only): `[[from, to, state, range_m, rate_bps], ...]` with display ids (`"SAT-1"`), `state` `LOCKED | ACQUIRING | DOWN`, `range_m` / `rate_bps` numbers or `null` (a non-finite value is sent as null so the frame is never dropped). `rate_bps` is 0 unless LOCKED. Acquisition time (30 s) is an assumption: label it.
- **`sim_state.components`** (laser runs only): `[["SAT-1", "SAT-2"], ["SAT-3"]]`, groups of talking sats that can hear each other over LOCKED links. More than one entry = the swarm is split. A cut-off sat that is heard again gets NO event; read the reconnect from `components`.
- **Events** (all `type: "event"`; the structured fields are optional extras):
  | source | level | message | extra |
  |---|---|---|---|
  | `LINK_LOCKED` | info | `Laser link SAT-1 to SAT-2 locked` | `link: ["SAT-1", "SAT-2"]` |
  | `LINK_LOST` reason `sun` | warning | `Laser link SAT-1 to SAT-2 lost: the sun is in a receiver's view` | `link`, `reason` |
  | `LINK_LOST` reason `partner_down` | warning | `... lost: a partner is down` | `link`, `reason` |
  | `LINK_LOST` reason `budget` | warning | `... lost: out of link budget` | `link`, `reason` |
  | `LINK_LOST` reason `replan` | info | `... dropped: the network re-routed` | `link`, `reason` |
  | `PARTITION` | warning | `Swarm split into 2 groups: SAT-1, SAT-2 \| SAT-3` | `components` |
  | `FAILURE_DETECTED{cause: "isolated"}` | warning | `SAT-3 cut off: no laser link reaches it, so the swarm cannot hear it` | `sat_id`, `cause: "isolated"` |
  Show "cut off" as its own state, not as failed. It does NOT update `metrics.detection_latency_s` (that stays the failure-detection latency).
- **`hello.formation_shape`** (`cartwheel | pco | gco | helix | string`): v2 LIVE hellos only (all v2 live runs, laser or not). v1 hellos never carry it (v1 is cartwheel-only). **Replay hellos do not carry it yet** (the key rides on the live source; replay needs a session-side hook, owned by the perf track): until then treat a missing key as unknown, and keep the ghost/deviation layer off when unknown on a v2 replay.
- Size: mean `sim_state` on a 600 s 6-sat laser run (nominal, DEAD sat 0 at 100 s) grows 2694.6 → 3055.1 bytes/frame (mesh, +13.4 %) and 2694.6 → 2995.3 (star, +11.2 %).
- C4 fields (`functions`, `consensus_rounds`, `split_brain`, `FUNCTION_HANDOFF`) are NOT on the wire yet; they come with C4.
