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
