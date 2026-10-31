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

**`sats[].old_role` (on `sim_state`)**: the sat's role in the previous frame, present only on the tick its role changed. Absent on the first frame of a run and after a seek.
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
