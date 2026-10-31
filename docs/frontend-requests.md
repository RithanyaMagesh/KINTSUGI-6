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
