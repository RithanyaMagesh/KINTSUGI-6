# Prompt — implement Track C (paste into Claude Code at the repo root, branch `comms`)

## Setup (once)
```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
/plugin marketplace add DietrichGebert/ponytail
/plugin install ponytail@ponytail
/ponytail full
```

## Prompt
You are implementing **Track C** of KINTSUGI-6: laser crosslinks, leaderless (decentralised) recovery, and selectable formations. The backend only.

**Read first, in this order:**
1. `AGENTS.md` (invariants: determinism, SI units, LVLH frame, no number without a command, v1 byte-reproducible, new physics behind `engine: "v2"`).
2. `PROJECT_MEMORY.md` §2, §3, §5, §8.
3. `docs/superpowers/specs/2026-11-01-track-c-comms-decentral-formations.md` (the spec).
4. `docs/superpowers/plans/2026-11-01-track-c-plan.md` (the plan). C1 is done.
5. `cubesat/formations.py`, `cubesat/isl.py`, `cubesat/decentral.py`, `tests/test_comms_track.py`.

**Rules:**
- **Superpowers.** Work the plan with `superpowers:executing-plans`. Use `superpowers:test-driven-development` for every task: write a failing test, watch it fail, then implement. Use `superpowers:systematic-debugging` on any red test. Run `superpowers:verification-before-completion` before saying anything is done, and `superpowers:requesting-code-review` at each phase gate. Skip brainstorming: the spec is approved.
- **Ponytail (full).** Make the smallest complete change. Reuse `hcw`, `geo_v2`, `ground`, `transfer`, `roles_v2`, `faults_v2` rather than writing new helpers. No new dependencies. Files stay under ~300 lines. Never cut validation or determinism.
- **One phase per session.** Do C2, then STOP and report (diff stat, test tail, every new number with its command). Do not start C3 until the user says go.
- **Do NOT touch `frontend/`.** Every UI idea goes in `docs/frontend-requests.md` § "Track C".
- **Defaults are inert.** A scenario without `comms`, `formation.shape` or `recovery.authority` must produce byte-identical logs. Prove it with the existing golden tests before writing the feature.
- **Coordination.** Another session is changing `backend` (phases 5b/5d). `git fetch && git rebase origin/backend` before each phase. If `sim_v2.py`, `scenario_models.py`, `faults_v2.py` or `roles_v2.py` conflict, stop and report rather than force a merge. Never push `backend`, never touch `frontend`. Push only branch `comms`, and only when asked.
- **Honesty.** Assumptions (apertures, photons/bit, acquisition time, sun cone, terminals) are labelled "assumption" in code descriptions and reports. Results that contradict the expected story are reported, not tuned away. "CBBA" appears only in code docs; user-facing text says "consensus auction".

**Done for C2 means:**
- The `comms.model="laser"` opt-in works.
- Links, components and LINK_*/PARTITION events are in the v2 log.
- Heartbeats travel only over locked links.
- Snapshot/restore is covered.
- All golden pins are unchanged.
- `ruff` is clean and the fast and slow suites are green.
- GATES.md has a C2 entry.
