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
