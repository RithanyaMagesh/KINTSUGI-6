# Track C — Laser crosslinks, leaderless recovery, selectable formations (spec)

Date 2026-11-01. Branch `comms` (from `backend` 88483d2). Origin: round-2 judge feedback.
Status: slice C1 (pure modules + tests) DONE on this branch; C2–C6 not started.

## 1. What the judges asked (verbatim intent)
1. **Show laser-based communication**: data moving CubeSat → CubeSat.
2. **Decentralise the leader**: when the leader dies, do not elect one new leader; split the leader's work across the survivors, like a UAV swarm where comms, strategy, etc. are taken over by different drones. "Goal-based recovery."
3. **Selectable formations**: let the user pick a formation and see what it looks like.
4. Back every claim with the physics.

## 2. Gap in the repo today (verified on `backend` 88483d2)
- Comms are ideal and instant. Detection = K missed heartbeats (`faults_v2.py`), with no notion of WHO hears a heartbeat or over WHICH link. `RADIO_FAIL` exists but is a sat flag, not a link.
- Leader = one stackable software role in `roles_v2.ROLE_SPECS`, re-assigned by a central Hungarian solve (`assign_roles`). PROJECT_MEMORY §5 do-not-claim: "decentralized consensus (centralized Hungarian)". Master map line 418 lists decentralised leader election as future work.
- One formation: phase-spaced slots on a 2:1 ellipse with z = x amplitude (`sim.build_slots` → `hcw.slot_initial_state(A, A, p)`). That is a cartwheel. No PCO/GCO/helix/string.

## 3. Physics (the numbers the pitch may use, each reproducible from `cubesat/isl.py`)
| Quantity | Value | Source / command |
|---|---|---|
| CLICK-B/C (MIT/NASA) crosslink | 1.5U payload, ~200 mW, 1537/1563 nm, >20 Mbps at 25–580 km, ranging < 50 cm | SPIE 12777, 127777K (2023) |
| Our margin at 580 km (default terminal) | +9.6 dB at the 20 Mbps cap | `isl.margin_db(580e3, Terminal())` |
| Our margin at 16 km (formation scale) | +40.8 dB | `isl.margin_db(16e3, Terminal())` |
| Beam 1/e half-width (2 cm aperture, 1550 nm) | 24.7 µrad | `isl.beam_halfwidth_rad(Terminal())` |
| Rate with body pointing only (1.7 mrad) | 0 bps | `isl.data_rate_bps(16e3, Terminal(), 1.7e-3)` |
| 2-terminal ring, leader dead | 1 component (5 sats) | `tests/test_comms_track.py::test_ring_survives_leader_loss_star_does_not` |
| Star (all→leader), leader dead | 5 singletons; all 6 functions split-brain | `test_star_hub_death_is_split_brain` |
| Formation min separation, 6 sats, A = 8 km | cartwheel 11.3 km · pco 16 km · gco 16 km · helix 8 km · string 8 km | `formations.min_separation` |

Assumptions (must be labelled "assumption" anywhere they are shown): apertures 2 cm, η = 0.3, 300 photons/bit, fine-steering-mirror pointing error 5 µrad, acquisition 30 s, sun exclusion 3°, 2 terminals/sat.

**Story the physics gives:** at km ranges, power is never the problem; **pointing and point-to-point topology are**. One terminal talks to one partner. A central leader therefore means a star topology. Kill the hub and the network partitions, not just the role. A ring or mesh survives, and that is exactly why the leader must be decentralised.

## 4. Design
### 4.1 `cubesat/formations.py` (DONE)
`formation_slots(shape, n_slots, A, n, phase)` with shapes `cartwheel | pco | gco | helix | string`, all drift-free (vy0 = −2n·x0), plus a closed-form `positions_over_orbit` and `min_separation`. `cartwheel` is bit-for-bit the v1 slot, so wiring it as the default keeps the golden pins. The tetrahedron (MMS) is excluded: it is regular only at one point per orbit and needs exactly 4 sats.

### 4.2 `cubesat/isl.py` (DONE)
Link budget (gain, free-space loss, Gaussian pointing loss, photon-limited rate with a modem cap), `step_link` DOWN→ACQUIRING→LOCKED, `sun_blinded`, `plan_topology` (terminal cap, keep acquired links first, shortest-range greedy, deterministic), `star_topology`, `components`.

### 4.3 `cubesat/decentral.py` (DONE)
Leader decomposed into 6 functions: failure_detection, time_sync, formation_reference, collision_arbitration, task_scheduling, ground_relay. Bids come from mission goals (connectivity, fuel, ground-pass wait); radio-dead sats do not bid. The tasks are run as a sequential auction with synchronous max-consensus over the live link graph, using a load penalty to spread work. Consensus rounds are counted (cost is part of the claim). Per-component winners are kept, and split-brain is detected. This is the CBBA family (Choi, Brunet & How 2009). Do not call it "CBBA" in the UI; call it a "consensus auction".

### 4.4 Engine integration (C2–C4, not started)
Everything is behind new optional scenario fields. Defaults are off, so every v1 and v2 golden pin is unchanged:
- `comms: {model: "ideal" | "laser", terminal: {...}, terminals_per_sat: 2}` (v2 only; `ideal` = today).
- `formation.shape: "cartwheel" | "pco" | "gco" | "helix" | "string"` (default `cartwheel`).
- `recovery.authority: "central" | "decentral"` (default `central`).

When `comms.model == "laser"`, EngineV2 each tick:
1. computes positions;
2. replans topology only on a topology event (death, link loss); otherwise keeps the set;
3. steps every link's state machine (unusable if a partner is non-radio, out of budget, or sun-blinded; sun vector from `geo_v2`);
4. heartbeats propagate only over LOCKED links, multi-hop within a component; a sat is declared by its neighbours after K missed ticks;
5. logs `links: [[i, j, state, range_m, rate_bps]]` and `components`.

When `recovery.authority == "decentral"`, the leader role is replaced by the 6 functions. The auction runs on each topology event, emitting `FUNCTION_HANDOFF` events and per-sat `functions: []`. Downlink and imager stay with `roles_v2` (physical roles).

### 4.5 Measurement (C5), pre-registered in GATES.md BEFORE any run
Matrix: comms {ideal, laser} × authority {central-star, central-mesh, decentral} × the 15 kill pairs, plus a leader-kill set. Metrics:
- function vacancy seconds;
- split-brain seconds;
- consensus rounds;
- time to first full function coverage after a death;
- link-up fraction;
- bits delivered to the downlink holder.

Write "unmeasured" for every cell until it runs. Expected but NOT claimed: central-star under laser loses on vacancy at every leader kill. If that does not happen, report it.

## 5. Non-goals
- No changes to v1 behaviour.
- No new dependencies.
- No frontend edits (see `docs/frontend-requests.md` § Track C).
- No claim of flight-realistic acquisition times, and no RF backup link (mention as future work).
