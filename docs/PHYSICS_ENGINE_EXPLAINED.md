# The physics engine, explained

Written 2026-10-31 from the source tree at HEAD `c56f13b` (branch `frontend-landing-page`). Read-only pass: no code was changed.
Every claim points to `file:line` or to a command output pasted below. Line numbers are for this HEAD; re-check them after any edit.
Plain English first, then the maths, then the reference.

---

## 1. One-page overview

**In plain English (10 lines):**
1. Six small satellites fly in formation around an imaginary "chief" point that circles Earth at 500 km.
2. Their motion relative to that point follows a linear orbit model (Hill–Clohessy–Wiltshire), solved exactly with a formula, not a numerical integrator.
3. Each satellite has a "slot" on one shared, naturally repeating ellipse. A PD controller with a thrust cap keeps it there.
4. Each satellite has a role: 1 leader, 4 imagers, 1 downlink. Only imagers count toward ground coverage.
5. At scripted times satellites fail: DEAD (silent), THRUSTER_OUT (reports itself), or EPS_DEGRADE (fades, then dies).
6. A heartbeat monitor notices silence after 3 missed ticks (4 s at 2 s steps).
7. The replanner picks a new formation for the survivors (a sweep over phase offsets), re-elects any lost critical role, and assigns survivors to seats with the Hungarian algorithm.
8. The survivors fly to their new seats under the same capped PD controller. The swarm counts as "recovered" once everyone is within 5% of the longest transfer distance.
9. Every 2 s tick logs positions, velocities, Δv used, coverage (fraction of a ground grid seen) and the closest pair distance.
10. Same scenario + seed ⇒ identical log, because there is no clock and no randomness inside the engine.

**One tick** (`cubesat/sim.py:222-644`):

```
 tick k, t = k·dt
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ 1. EPS_DEGRADE fades fire   (sat → DEGRADED, DEGRADE_START event,        │ sim.py:231-278
 │                              optional critical-seat handover)            │
 │ 2. Failures fire            (sat → DEAD / THRUSTER_OUT; THRUSTER_OUT     │ sim.py:280-314
 │                              self-reports → FAILURE_DETECTED now)        │
 │ 3. Heartbeats               (DEAD: missed+=1, everyone else: missed=0)   │ sim.py:316-320
 │ 4. Detection                (missed ≥ K → FAILURE_DETECTED event)        │ sim.py:322-340
 │ 5. Metrics                  coverage (imagers not DEAD), min_sep (all)   │ sim.py:346-359
 │ 6. Log line                 {t, state, sats[], coverage, min_sep, event?}│ sim.py:360-381
 │      (at most ONE queued event popped per line, FIFO)                    │
 │ ── stop here on the last tick ──                                         │ sim.py:382-383
 │ 7. Oracle hook (default off)                                             │ sim.py:390-416
 │ 8. State machine / replan   FD→REPLANNING→(replan)→RECONFIGURING→settled?│ sim.py:423-579
 │ 9. Evasion check            (sat within 1 km of another → away burn)     │ sim.py:596-626
 │10. Step every satellite     NOMINAL/DEGRADED: PD (or evasion burn)       │ sim.py:633-644
 │                             DEAD/THRUSTER_OUT: ballistic coast           │
 └──────────────────────────────────────────────────────────────────────────┘
 after the loop: SUMMARY line = mean coverage over the final orbit             sim.py:647-656
```

---

## 2. The orbit model (`cubesat/hcw.py`)

### 2.1 The LVLH frame

**Plain English:** don't describe positions relative to Earth's centre. Describe them relative to a reference point (the **chief**) that moves along a circular orbit. Axes rotate with the chief: x points away from Earth, y points along the direction of travel, z completes the right-handed set (out of the orbit plane).

```
                 z (cross-track, orbit normal)
                 │
                 │      y (along-track, direction of flight →)
                 │    ╱
                 │  ╱
   chief ●───────┼──────────── x (radial, away from Earth)
                 │
                 ▼
               Earth centre is far along −x (≈ 6,878 km away)
```

State vector `[x, y, z, vx, vy, vz]`, SI units (`hcw.py:3-5`; AGENTS.md invariants 3–4).

### 2.2 Hill–Clohessy–Wiltshire (HCW / CW) equations

**Plain English:** if the satellites stay close to the chief (km, not thousands of km) and the chief's orbit is a circle, gravity's pull *relative to the chief* can be approximated as linear in position. You get three coupled linear ODEs that have an exact closed-form solution. The "chief" is not a real satellite. It is the centre of the formation on a circular 500 km orbit (`ChiefOrbit.altitude_km`, `scenario.py:37-40`). The deputies are the six satellites.

**Maths** (n = mean motion of the chief, a = commanded acceleration):

```
ẍ − 2n·ẏ − 3n²·x = a_x
ÿ + 2n·ẋ         = a_y
z̈ + n²·z         = a_z
```

They are linear because the full gravity term μr/|r|³ is Taylor-expanded to first order around the chief. Everything second-order (and J2, drag) is dropped. The cost of that is measured in §8.

**Constants** (`hcw.py:19-25`):

| Constant | Value | Where |
|---|---|---|
| μ (Earth GM) | 3.986004418×10¹⁴ m³/s² | `hcw.py:19` |
| R⊕ | 6378.137×10³ m | `hcw.py:20` |
| n = √(μ/(R⊕+h)³) | at h = 500 km: **1.106783×10⁻³ rad/s** | `hcw.py:23-25`; value printed by the worked example in §9.1 |
| orbit period 2π/n | **5677.0 s** (≈ 94.6 min) | same |

Altitude is stored in km in JSON and converted once: `altitude_m = altitude_km * 1000` (`sim.py:159-160`).

### 2.3 The state-transition matrix (STM)

**Plain English:** because the equations are linear, the state at time t is a fixed 6×6 matrix times the starting state. No integrator, no step-size error. The engine evaluates `cos(nt)` and `sin(nt)` and multiplies, so propagation is exact *for the CW model* at any t.

**Maths** (`hcw.py:28-54`, c = cos nt, s = sin nt):

```
x(t)  = (4−3c)·x0                    + (s/n)·vx0      + (2(1−c)/n)·vy0
y(t)  = 6(s−nt)·x0 + y0              − (2(1−c)/n)·vx0 + ((4s−3nt)/n)·vy0
z(t)  = c·z0                                                         + (s/n)·vz0
vx(t) = 3n·s·x0                      + c·vx0          + 2s·vy0
vy(t) = 6n(c−1)·x0                   − 2s·vx0         + (4c−3)·vy0
vz(t) = −n·s·z0                                                      + c·vz0
```

What each row says physically:
- **x row:** radial motion is an oscillation at the orbital rate around an offset set by x0 and vy0.
- **y row:** along-track has two terms that **grow with t** (`−6nt·x0` and `−3nt·vy0/n`). This is secular drift: a satellite slightly lower or faster than the chief slowly runs ahead or falls behind.
- **z row:** cross-track is a pure harmonic oscillator, decoupled from x/y. Out-of-plane motion is a tilted orbit crossing the chief's plane twice per orbit.
- **velocity rows:** the time derivatives of the rows above.

`propagate(state0, t, n)` = `stm(t, n) @ state0`, scalar or vector t (`hcw.py:57-68`).

**Verification (command output, §9.1):** `test_hcw_stm_vs_ode` compares against RK45 of the CW ODEs. Max relative error: position **1.358×10⁻¹²**, velocity **5.597×10⁻¹⁰** (`tests/test_hcw.py:64`). GATES.md records 1.353e-12 / 5.599e-10 from the Windows run; the last digits differ by platform floats.

### 2.4 The forcing matrix: thrust added exactly

**Plain English:** the controller picks an acceleration and holds it constant for one 2 s step ("zero-order hold"). Because the system is linear, the effect of a constant push over [0, t] also has a closed form. So a controlled step is exact too: `x(t+dt) = Φ(dt)·x(t) + G(dt)·a`.

**Maths:** `G(t) = ∫₀ᵗ Φ(s) ds · B` with `B = [0; I₃]` (`hcw.py:85-106`). For small t it reduces to the double integrator `[[t²/2·I], [t·I]]` (`hcw.py:90`). `propagate_controlled` = `stm @ x0 + forcing_matrix @ a` (`hcw.py:109-116`).

**Verification (§9.1):** `test_forced_propagator_matches_ode` gives relative error position **2.281×10⁻¹³**, velocity **2.323×10⁻¹³** (`tests/test_pd.py:99`).

### 2.5 The passive 2:1 "drift-free" ellipse, and why slots are phases on it

**Plain English:** if you start a satellite with exactly the right along-track speed for its radial offset, the growing terms in the y-row cancel. It then traces a closed ellipse around the chief once per orbit **with zero fuel**. The ellipse is twice as long along-track as it is radially (2:1). Put six satellites at six evenly spaced points (phases) on the same ellipse and they chase each other round it forever, never drifting apart. That is the formation.

**Maths.** The secular terms in y(t) are `−6nt·x0 − 3t·vy0`. They vanish iff

```
vy0 = −2·n·x0          (drift-free condition)          hcw.py:75-82, 125
```

The slot at phase p (radial amplitude A, cross-track amplitude B; `hcw.py:119-142`):

```
x = A·cos(nt+p),   y = −2A·sin(nt+p),   z = B·cos(nt+p)
```

The engine sets **B = A** because the schema has no cross-track field (`sim.py:134-146`, `allocate.py:158-159`). For `two_failure.json`, A = 8 km, so each slot traces 8 km radial × 16 km along-track × 8 km cross-track (`data/scenarios/two_failure.json` `radial_amp_km: 8.0`). Slot j sits at phase `phase_offset + 2πj/n_slots` (`sim.py:141-145`).

**If the condition is violated:** the satellite drifts along-track at `ẏ_secular = −(6n·x0 + 3·vy0)` m/s (`keepout.py:72-77`, derived from the y-row of `hcw.py:41-48`). Worked arithmetic from that formula (not a committed measurement): a 1 m/s error in vy0 gives 3 m/s drift, ≈ 3 × 5677 ≈ 17 km per orbit.

**Verification (§9.1):** `test_drift_free_ellipse_closes` (`tests/test_hcw.py:87`). `test_passive_slot_low_dv` shows holding a slot costs **1.403×10⁻¹² m/s** Δv over one orbit, with max position error 2.144×10⁻¹¹ m (`tests/test_pd.py:183`).

---

## 3. Control (`cubesat/pd.py`)

### 3.1 The PD law against a moving slot

**Plain English:** each satellite is pulled toward where its slot *is right now* (a spring, Kp) and damped toward how its slot *is moving right now* (a shock absorber, Kd). Because the slot is itself a free orbit, a satellite already on its slot needs essentially zero thrust.

**Maths** (`pd.py:3-6, 52-53, 56-65`):

```
u  = −Kp·(r − r_ref) − Kd·(v − v_ref)
Kp = ωn²,   Kd = 2ζωn
```

- **ωn** (`gains.wn`, rad/s) is the natural frequency: how stiff the spring is. In every committed scenario ωn = 0.01 rad/s, so Kp = 1×10⁻⁴ s⁻² and Kd = 0.02 s⁻¹ (`two_failure.json` `gains`).
- **ζ** (`gains.zeta`) is the damping ratio. ζ = 1 is "critically damped": fastest approach without oscillating, in the unsaturated linear case.
- **Reference is the moving slot:** `ref = propagate(formation[seat_of[i]], t, n)` every tick (`sim.py:641-642`). Using v_ref = 0 would fight the natural 2:1 motion and waste Δv (`pd.py:4-6`).

### 3.2 Thrust saturation and Δv accounting

- **Saturation:** if ‖u‖ > a_max, the vector is scaled down to length a_max, keeping its direction (`pd.py:62-64`).
- **Hold and step:** u is held constant over [t, t+dt) and propagated exactly with `propagate_controlled` (`pd.py:67-77`).
- **Δv used:** `dv_used += ‖u‖·dt` per step, per satellite (`pd.py:76`). This is the "fuel" in the log (`sim.py:371`). Mass never changes (see §8).
- **Reference time:** `bang_bang_time_lower_bound(d, a_max) = 2√(d/a_max)` (`pd.py:30-38`) is the rest-to-rest minimum time with full thrust. It is logged per replan as `transfer_lower_bound_s` (`sim.py:557-559`). The code says it is a reference, not a bound on the closed loop (`pd.py:34-37`).

**Measured** (`uv run python -m pytest tests/test_pd.py -s -q`, §9.1):
- 1 km step at a_max = 0.01: overshoot **4.99%**, settle **746 s**, max ‖u‖ = a_max, Δv **6.411 m/s** (`tests/test_pd.py:127`).
- Saturation test, d = 2236.1 m: bang-bang bound 945.7 s, settle 1966 s, Δv 20.176 m/s (`tests/test_pd.py:153`).

### 3.3 The evasion burn (`apply_accel`)

**Plain English:** if a healthy or degraded satellite comes within 1 km of any other satellite, alive or dead, it stops tracking its slot. It burns straight away from the intruder at full thrust for 25 ticks (50 s). If it's still too close when that ends, it starts another burn.

- `apply_accel` saturates the raw vector, accounts Δv and propagates exactly. There is no feedback; the caller picks the direction (`pd.py:79-90`).
- Trigger: `sim.py:596-626`. The trigger check runs only if the sat is NOMINAL/DEGRADED and has no active episode. It picks the nearest sat with `0 < range < evade_radius_m`; direction `u = a_max · (r_i − r_j)/|r_i − r_j|` (`sim.py:614`).
- While `evade_ticks_left > 0` it replaces the PD step (`sim.py:635-639`).
- Defaults: `evasion_enabled=True`, `evade_radius_m=1000`, `evade_ticks=25` (`scenario.py:157-165`). The code calls it "geometrically inert" on canonical runs (`scenario.py:152-155`). That holds for `nominal` and `two_failure` (`tests/test_collision_avoidance.py:173`). **It does fire on `eps_leader_6sat`** (§9.1 worked example: two EVASIVE_MANEUVER events at t = 2740, range 959.4 m).

### 3.4 Why a_max = 0.1 m/s² in the failure scenarios

README ("Honesty / limitations"):

> **The failure demo needs more thrust than that assumption.** `two_failure.json` carries `a_max = 0.1 m/s^2` (~800 mN at 8 kg): at 1e-2 the G2 PD diverges on formation-scale transfers at every spacing swept (4–11 km, measured 2026-09-28 — burn-induced Coriolis radial oscillations exceed the saturated controller's authority), so the demo flies 0.1 m/s^2 with 8 km slots and per-sat Δv up to 193.68 m/s — above a realistic cold-gas budget. The proper fix is an impulsive/MPC transfer planner (future work).

What it implies physically:
- The default `A_MAX_DEFAULT = 1e-2` assumes an ~8 kg CubeSat with a ~150 mN cold-gas thruster (`pd.py:24-27`).
- The demo needs about 5× that thrust (0.8 N).
- Per-satellite Δv reaches ~194 m/s (§9.1). HANDOFF.md §3 Phase C puts this at "~22× the module's entire budget" for a VACCO CuSP MiPS cold-gas unit (8.8 m/s at 8 kg).
- The benchmark measures a control algorithm. It is not a flight claim.

---

## 4. Failures and detection (`cubesat/sim.py`)

### 4.1 The three failure modes

Schema: `FailureMode` (`scenario.py:27-34`), `Failure{t, sat_id, mode, degrade_s}` (`scenario.py:81-90`). Failures are sorted by `(t, sat_id)` (`sim.py:184`) and fire when `failure.t <= t + 1e-9`, i.e. on the first tick at or after t (`sim.py:280`).

| Mode | Motion | Heartbeat | Detection | Role / seat | Coverage |
|---|---|---|---|---|---|
| **DEAD** | ballistic coast from the failure tick (`sim.py:643-644`) | silent (`sim.py:317-318`) | after K missed ticks (`sim.py:322-340`) | excluded from replan; its role is re-elected among survivors | not counted (`sim.py:350`) |
| **THRUSTER_OUT** | ballistic coast, cannot thrust or evade (`sim.py:599, 643-644`) | keeps reporting (`sim.py:319-320`) | **self-report on the firing tick**, `self_report: true`, latency 0 (`sim.py:292-314`) | excluded from replan (status ≠ NOMINAL, `sim.py:437`); keeps its `roles[i]` label (see Q3) | **still counted if it is an imager** (only DEAD is excluded, `sim.py:350`) |
| **EPS_DEGRADE**, `degrade_s > 0` | PD-holds its seat during the fade (`sim.py:634`), then coasts like DEAD | reports while DEGRADED; silent after death | DEGRADE_START at fade onset; FAILURE_DETECTED via heartbeat after death (`sim.py:231-248`) | excluded from replan while DEGRADED; keeps its seat across replans (`sim.py:500-505`) | counted while DEGRADED; not after death |
| **EPS_DEGRADE**, `degrade_s = 0` | identical to DEAD | same as DEAD | same as DEAD; only the mode label differs (`sim.py:51-55`) | same as DEAD | same as DEAD |

The fade starts at `max(t_fail − degrade_s, 0)` (`sim.py:190-197, 233`). Only a sat that is still NOMINAL can enter the fade (`sim.py:237`). At `t_fail` the normal failure block sets it DEAD, because its mode isn't THRUSTER_OUT (`sim.py:285-289`). Tests: `tests/test_failure_modes.py:93` (window semantics), `:149` (zero window equals DEAD), `:175` and `:211` (self-report triggers replan, latency 0).

### 4.2 The heartbeat detector, and why detection takes 4 s

Every tick each non-DEAD sat resets its miss counter and each DEAD sat increments it (`sim.py:316-320`). When `missed ≥ missed_ticks_k` (default 3, `scenario.py:97-99`) the sat is declared once (`sim.py:322-340`).

**Why 4 s, not 6 s:** the failure fires *before* that tick's heartbeat (`sim.py:279-280`), so the failure tick itself is miss #1. Misses land at t_fail, t_fail+2 and t_fail+4. Latency is `(K−1)·dt = 2 × 2 s = 4 s`. Worked example (§9.1): sat 1 fails at t = 1200.0 and is detected at t = 1204.0.

### 4.3 Degrade-trigger role handover (`reassign_on_degrade`)

**Plain English:** if the leader or downlink starts fading, it immediately swaps seat and role with the lowest-numbered healthy non-critical satellite. The critical role is never vacant when it dies.

- Flag: `reassign_on_degrade: bool = False` (`scenario.py:188-199`).
- Condition: flag on, `recovery_enabled`, the fading sat holds `leader` or `downlink` (`_CRITICAL_ROLES`, `sim.py:95`), and the mission is NOMINAL or RECOVERED (`sim.py:258-263`).
- The swap is `_swap_critical_seat` (`sim.py:98-131`). The target is `min()` of assignable sats that are not failing later and not critical (`sim.py:117-124`). Seats and roles are exchanged (`sim.py:125-127`). It emits `ORACLE_SWAP` with `mode: "degrade_trigger"` (`sim.py:128-131`).
- Worked example (§9.1, `eps_leader_6sat`): DEGRADE_START at t = 600, ORACLE_SWAP leader 0→1 logged at t = 602. The event is one tick late because the FIFO pops one event per line (`sim.py:378-379`). Sat 0 dies at 2400 holding an imager role, and sat 1 is leader at the end.

### 4.4 How dead satellites move, and why they stay in collision checks

Non-NOMINAL, non-DEGRADED sats are propagated with the unforced STM every tick: `states[i] = propagate(states[i], dt, n)` (`sim.py:643-644`). They are never frozen (AGENTS.md invariant 5). A real dead satellite keeps orbiting, so it is still a collision hazard:
- `min_sep` loops over **all** pairs, dead included (`sim.py:354-359`).
- The replanner's separation check treats every non-NOMINAL sat as a coasting obstacle (`sim.py:438`, `allocate.py:91-92`).
- Evasion considers intruders of any status (`sim.py:606-612`).

Caveat: a dead sat stays on a bounded ellipse only in linear, unperturbed CW. J2 and drag would make it drift (README "Dead-sat caveat"; `keepout.py:44-48`).

---

## 5. Recovery (`cubesat/allocate.py` + the state machine)

### 5.1 The state machine

States are defined at `sim.py:78-84`; transitions at `sim.py:322-340, 302, 423-579`.

| From → To | Exact condition | Where |
|---|---|---|
| any → **FAILURE_DETECTED** | heartbeat declaration (DEAD after K misses) **or** THRUSTER_OUT self-report | `sim.py:329`, `sim.py:302` |
| FAILURE_DETECTED → **REPLANNING** | `recovery_enabled` and at least one NOMINAL sat; emits STATE event; sets `replan_due` | `sim.py:423-435` |
| REPLANNING → **RECONFIGURING** | next tick: `replan(...)` runs, seats/roles updated, ASSIGNMENT event | `sim.py:436-562` |
| RECONFIGURING → **RECOVERED** | every NOMINAL/DEGRADED sat within `recover_tol` (position only) of its seat | `sim.py:563-579` |
| NOMINAL/RECOVERED → REPLANNING | oracle only (default off) | `sim.py:390-416` |

- FAILURE_DETECTED and REPLANNING each last exactly one tick (`sim.py:385-388, 418-422`).
- With `recovery_enabled = false` the machine stays in FAILURE_DETECTED. This is the do-nothing baseline (`scenario.py:184-187`); the worked example shows only `NOMINAL` / `FAILURE_DETECTED` states in that run.
- A second failure during RECONFIGURING re-enters FAILURE_DETECTED and replans from the current states (worked example: second detection at 1504).

### 5.2 Step 1: formation selection (`select_formation`, `allocate.py:135-180`)

**Plain English:** try every candidate survivor formation (k evenly spaced seats on the same ellipse, at different amplitudes and phase offsets). Throw out any that would bring two satellites (dead ones included) closer than 2 km, or that someone can't reach within the Δv budget. Keep the one with the best average coverage.

- **What is swept:** `amp_sweep × phase_sweep_deg` (`allocate.py:154-161`). For `two_failure.json`: `amp_sweep = [1.0]` and `phase_sweep_deg = [0, 30, …, 330]`, so **1 × 12 = 12 candidate formations per replan**. "72" in the code is `_SWEEP_SAMPLES` (`allocate.py:44`), the number of time samples per orbit inside each check, not the candidate count.
- **Separation check** `_min_separation_ok` (`allocate.py:82-97`): over 72 samples of one orbit from `t_replan`, every pair among {seats, coasting obstacles} must be ≥ `min_sep_km·1000` (2 km default, `scenario.py:109-112`). It checks the **destination** formation, not the transfer paths.
- **Reachability check** `_reachability_ok` (`allocate.py:100-117`): estimated Δv per (survivor, seat) is `2√(d·a_max)`, the rest-to-rest bang-bang cost. A perfect matching with every transfer ≤ `dv_budget_mps` must exist (`two_failure.json`: 200 m/s). It is tested with `linear_sum_assignment` on a 0/1 "over budget" matrix.
- **Objective** `_coverage_estimate` (`allocate.py:120-132`): mean coverage of the **imager seats** over 72 samples of one orbit. The highest wins; exact ties keep the first in sweep order (strict `>`, `allocate.py:176`).
- **Do-no-harm hold** (`allocate.py:267-276`): when the sim passes `current_slots` and the best candidate's coverage is below the coverage of survivors simply staying where they are, replan returns method `do_no_harm_hold`. Nobody moves; only roles are re-laid (`sim.py:477-482`). Seen in the worked example `thruster_leader_6sat`. ARCHITECTURE.md does not document this path (see Q1).
- No feasible candidate raises `RuntimeError("no feasible survivor formation in the sweep grid")` (`allocate.py:178-179`).

### 5.3 Role re-election (`seat_roles_for`, `allocate.py:60-79`)

**Plain English:** a role that existed exactly once in the original formation is critical (leader, downlink). If its holder died, one survivor from the most common role (an imager) is promoted to it. Then the seat layout puts imagers on even seat indices so the imaging satellites are spread around the ellipse.

- Critical = `original_roles.count(role) == 1` (`allocate.py:67`). Majority role by count, ties by first occurrence (`allocate.py:68-70`). No sets, for determinism (`allocate.py:66`).
- Interleave: even seat j gets an imager while imagers remain; odd seats get others (`allocate.py:71-78`).
- Consequence (worked example, first replan): survivor roles `[leader, imager, imager, imager, downlink]` become seats `[imager, leader, imager, downlink, imager]`. The leader moves from slot 0 to seat 1 (`ASSIGNMENT` sat 0 → slot 1). Sat 0 (the leader) ends with the largest Δv, **193.68 m/s**.

### 5.4 Step 2: the cost matrix and the assignment (`allocate.py:183-231`)

**Maths:**

```
C[i,j] = w1·d̂[i,j] + w2·(d̂[i,j]/fuel_i)^ + w3·mismatch[i,j] + ε·(i·m + j)
```

- `d̂` = survivor-to-seat distance normalised by its maximum. The fuel term is also normalised to [0, 1] (`allocate.py:192-198`).
- `fuel_i = max(dv_budget − dv_used_i, 1e-9)` (`sim.py:444-447`), floored at 1e-12 (`allocate.py:195`). Low-fuel sats find long transfers expensive.
- `mismatch = 0` if the survivor's current role equals the seat's role, else 1 (`allocate.py:199-201`).
- `ε = _TIE_EPS = 1e-9` times the row-major index, a deterministic tie-break (`allocate.py:42, 203`; AGENTS.md invariant 6).
- Defaults: w1 = 1.0, w2 = 0.5, w3 = 2.0 (`scenario.py:106-108`).
- **Hungarian:** `scipy.optimize.linear_sum_assignment`, rows = survivors, columns = seats (`allocate.py:217-219`). In the shipped path k survivors meet k seats, so the matrix is square (`seat_roles_for` returns one seat per survivor).
- **Greedy:** survivors in row order take the cheapest free seat, ties to the lowest column (`allocate.py:220-229`). It runs when `method: "greedy"` is set, or when the matrix has more than `_MAX_COST_CELLS = 4096` cells. That is a size cap, deliberately not a timeout (`allocate.py:43, 213-214`).

### 5.5 How "recovered" is decided

`recover_tol = max(0.05 × max_transfer, 1.0 m)` (`sim.py:91, 533`). RECOVERED fires when every NOMINAL/DEGRADED sat's **position** is within `recover_tol` of its seat's current position (`sim.py:564-571`). Velocity is not checked.

Worked arithmetic for two_failure's second replan: `transfer_lower_bound_s = 945.27 s = 2√(d/0.1)` ⇒ d ≈ 22.3 km ⇒ tolerance ≈ 1.1 km. So "RECOVERED" at t = 3114 s means each survivor was within about 1.1 km of its seat (see Q5).

---

## 6. Coverage and safety metrics

### 6.1 Coverage (`cubesat/coverage.py`)

**Plain English:** lay a square grid of ground target points under the formation. Each working imager sees a circle of ground. Coverage is the fraction of target points inside at least one circle.

- Footprint radius `r_f = h·tan(FOV/2)` (`coverage.py:24-27`). The JSON stores the **half** angle (`scenario.py:61`). For h = 500 km and 1.5°: r_f = **13,093 m** (`python3 -c "import math;print(500e3*math.tan(math.radians(1.5)))"` → 13092.96).
- Grid: `(2·extent/step + 1)²` points in the (y, z) plane (`coverage.py:30-35`). For extent 30 km and step 2 km: 31 × 31 = **961 points**. The size is capped at 10,000 (`scenario.py:19, 65-78`).
- Coverage per tick: boolean union over the (y, z) of every sat with role `imager` and status ≠ DEAD (`sim.py:346-353`, `coverage.py:38-49`). Removing an imager can only reduce it (`tests/test_coverage.py:50`).
- Simplifications: flat ground plane, nadir pointing, the radial offset x ignored, and the chief's altitude used for every imager (`coverage.py:3-9`).
- **Summary metric:** `coverage_mean_last_orbit` = mean over ticks with `t ≥ duration − 2π/n` (`sim.py:647-656`).
- **The metric is fixed by fiat.** Tune spacing or FOV, never the metric (research patch #2, `coverage.py:7-9`).

### 6.2 min_sep and the two thresholds

- `min_sep` = smallest distance among **all** pairs, dead included, every tick (`sim.py:354-359`).
- **2 km** (`allocation.min_sep_km`) is a **planning constraint**. It is checked only on candidate destination formations at replan time (`allocate.py:82-97`). It is **not enforced during transfers.**
- **1 km** (`safety.evade_radius_m`) is the **reactive trigger** for the evasion burn (`sim.py:596-626`).
- Between 1 and 2 km nothing acts. Measured: Hungarian's worst survivor-to-dead clearance across the 15-pair benchmark is **1322.6 m** (`data/eval/benchmark_results.json` `policies_summary.hungarian.worst_min_sep_survivor_dead_m`), below the 2 km planning floor. `eps_leader_6sat` dips to 959.4 m and triggers evasion (§9.1).
- On two_failure itself the worst `min_sep` is **3095.1 m at t = 1620 s** (`tests/test_fault.py:145`; §9.1).

---

## 7. Determinism

**Why the same scenario + seed gives the same log:**
- No wall clock inside the engine (`sim.py:3-6`). The only time is `t = k·dt` (`sim.py:225`).
- No RNG anywhere in the core. The `seed` is written into the INIT header and never read (`sim.py:211-220`; `monte_carlo.py:3-6`).
- Exact analytic propagation; no adaptive integrator (`hcw.py`, `pd.py:11-13`).
- Fixed iteration orders:
  - failures sorted by `(t, sat_id)` (`sim.py:184, 190-197`)
  - index loops everywhere
  - `dict.fromkeys` instead of sets in re-election (`allocate.py:66`)
  - `min()` for swap targets (`sim.py:124`)
- Tie-breaks: cost epsilon (`allocate.py:203`), first-wins formation ties (`allocate.py:176`), greedy ties to the lowest column (`allocate.py:227`).
- Fallback by size cap, not timeout (`allocate.py:43, 213`).
- One event popped per line, FIFO (`sim.py:200, 378-379`). Output uses `sort_keys` and LF newlines (`run.py`).
- The optional `cancel_event` is a pure read and is never set on CLI paths (`sim.py:149-158, 223-224`).

**Where randomness is allowed:** only outside the core, in the analysis layer. `monte_carlo.py` draws parameter jitter from one `numpy.random.Generator(PCG64(SeedSequence(seed)))` (`monte_carlo.py:52-55`) in a fixed `DRAW_ORDER` (`monte_carlo.py:45-49`):
- failure times ±10%
- phase offset ±30°
- radial amplitude ×[0.9, 1.1]

It then calls the pure core. The ensemble is still reproducible from its command.

**Caveat, measured this session:** "identical" means identical **on the same platform**. This machine (macOS) produces sha256 `cb7e2c2a…` for two_failure. The pin in `tests/test_failure_modes.py:229` is `450d5371…`, recorded on Windows. Events and printed numbers match; float last bits differ.

---

## 8. What is NOT modelled (blunt list)

| Missing | Effect it would have | How big (where known) |
|---|---|---|
| **Second-order gravity (nonlinear two-body)** | CW positions diverge from true Keplerian relative motion as the formation grows | CW-vs-Kepler max position error over 3 orbits: **3.101 m** at 1 km ellipse; **1578.5 m** at today's 8 km scale; 2984.5 m at the old 11 km scale (`cw_curve.py:61-63`; `data/eval/cw_error_report.json`; README) |
| **J2 (Earth oblateness)** | differential nodal/apsidal drift; formations and dead sats drift apart secularly | unmeasured in this repo |
| **Atmospheric drag** | differential decay at 500 km; dead sats (different area/mass) drift along-track | unmeasured |
| **Eccentric chief** | CW assumes circular; e > 0 adds once-per-orbit errors | unmeasured; the importer gates on near-circularity (`cluster_import.py` docstring) |
| **Attitude dynamics / pointing** | thrust direction is instantaneous and perfect; imagers always nadir | unmeasured |
| **Sensor noise / navigation error** | controller sees true state; coverage geometry exact | unmeasured; Monte Carlo jitters scenario parameters only (`monte_carlo.py:7-12`) |
| **Comms delays / packet loss** | heartbeat and self-report are instantaneous and lossless; replanner is centralised with perfect knowledge | unmeasured; README "Ideal comms and sensing; centralized replanner" |
| **Fuel mass change** | a_max constant, mass never decreases; Δv is ∫‖u‖dt, not a rocket-equation budget | n/a |
| **Real thruster limits** | continuous throttle, any direction, no minimum impulse bit, no duty cycle | a_max = 0.1 m/s² ≈ 0.8 N at 8 kg vs ~150 mN cold-gas assumption (`pd.py:24-27`; README) |
| **Collision during transfers** | 2 km is checked only on destination formations at replan; transfers are only guarded by the 1 km reactive evasion | Hungarian worst survivor-dead clearance **1322.6 m** across 15 pairs (`benchmark_results.json`); eps_leader 959.4 m (§9.1) |
| **Earth curvature / ground geometry** | flat ground plane, footprint from chief altitude | `coverage.py:3-9` |
| **Partial failures** | modes are total (dead / no thrust / fade-then-dead); no partial thrust, imager-only loss, or comms-only loss | — |
| **Controller optimality** | PD is far from fuel-optimal | 193.68 m/s sat spent 155.09 m/s in one episode vs a 47.81 m/s two-impulse reference (3.24×; mean 2.58×, worst 5.64×) — HANDOFF.md §3 Phase C, `data/eval/dv_lower_bounds.json`; see Q9 on "lower bound" |

---

## 9. Numbers, with sources

### 9.1 Worked examples (run this session)

**(a) Physics tests** — `uv run python -m pytest tests/test_hcw.py tests/test_pd.py -s -q`:

```
test_hcw_stm_vs_ode: max position relative error = 1.358e-12, max velocity relative error = 5.597e-10
test_cw_vs_kepler_error_report: max position error over 3 orbits = 3.101 m
test_forced_propagator_matches_ode: position relative error = 2.281e-13, velocity relative error = 2.323e-13
test_pd_step_response: overshoot = 4.99% (limit 5%), t_settle = 746 s (target 1265 s = 2x bang-bang bound 632 s), max |u| = 0.0100 m/s^2 (a_max = 0.01), dv_used = 6.411 m/s
test_saturation_respected: max |u| = 0.010000 m/s^2 (a_max = 0.01), bang-bang lower bound for d = 2236.1 m: t >= 945.7 s, t_settle = 1966 s, dv_used = 20.176 m/s
test_passive_slot_low_dv: max position error over one orbit = 2.144e-11 m, dv_used = 1.403e-12 m/s, max |u| = 1.410e-15 m/s^2
```

**(b) two_failure run** — `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out /tmp/tf.jsonl` printed `coverage_mean_last_orbit = 0.269797`. The log has 8517 lines (INIT + 8515 ticks + SUMMARY). Events, extracted with a short read-only Python script over the log:

```
t= 1204.0 FAILURE_DETECTED  FAILURE_DETECTED  sat 1, DEAD, t_fail 1200.0, t_detect 1204.0
t= 1206.0 REPLANNING        STATE             FAILURE_DETECTED -> REPLANNING
t= 1208.0 RECONFIGURING     ASSIGNMENT        hungarian, phase 0.0 rad, amp 8000 m, cost 3.7727, lower bound 983.98 s
                            assignments (sat, slot, role): (0,1,leader) (2,0,imager) (3,2,imager) (4,4,imager) (5,3,downlink)
t= 1504.0 FAILURE_DETECTED  FAILURE_DETECTED  sat 2, DEAD, t_fail 1500.0, t_detect 1504.0
t= 1506.0 REPLANNING        STATE             FAILURE_DETECTED -> REPLANNING
t= 1508.0 RECONFIGURING     ASSIGNMENT        hungarian, phase 0.5236 rad (30°), amp 8000 m, cost 3.1041, lower bound 945.27 s
                            assignments: (0,1,leader) (3,2,imager) (4,0,imager) (5,3,downlink)
t= 3114.0 RECOVERED         STATE             RECONFIGURING -> RECOVERED
SUMMARY coverage_mean_last_orbit = 0.26979718716450923
worst min_sep = 3095.1 m at t = 1620
final tick coverage 0.2674; final dv_used per sat [193.68, 0.0, 29.4, 123.46, 168.52, 109.66] m/s
final roles: 0 leader NOMINAL | 1 imager DEAD | 2 imager DEAD | 3 imager NOMINAL | 4 imager NOMINAL | 5 downlink NOMINAL
mean coverage t < 1200 (pre-failure) = 0.3796;  n = 1.106783e-03 rad/s, period 5677.0 s
sha256(/tmp/tf.jsonl) = cb7e2c2af27659d96397ac6224a92f544328b5f0640284386dce26d51d9f1989
```

Same scenario with `recovery_enabled=False` (in-memory `model_copy`, no file written): `coverage_mean_last_orbit = 0.2204572919411834`; states seen: `NOMINAL`, `FAILURE_DETECTED` only.

**(c) Degrade handover and thruster failure** (in-memory `run_scenario` on committed scenarios):

```
eps_leader_6sat (reassign_on_degrade: true, sat 0 EPS_DEGRADE t=2400, degrade_s=1800):
  t=600  DEGRADE_START sat 0      t=602  ORACLE_SWAP leader 0 -> 1 (mode degrade_trigger)
  t=2404 FAILURE_DETECTED sat 0   t=2408 ASSIGNMENT hungarian
  t=2742/2744 EVASIVE_MANEUVER sats 4<->5, range 959.4 m (t=2740)
  t=3664 RECOVERED               SUMMARY 0.349
thruster_leader_6sat (sat 0 THRUSTER_OUT t=2400):
  t=2400 FAILURE_DETECTED self_report   t=2404 ASSIGNMENT method do_no_harm_hold
  t=2406 RECOVERED                      SUMMARY 0.3669
  final roles: 0 leader THRUSTER_OUT | 2 leader NOMINAL | 4 downlink | 5 imager   (see Q3)
```

### 9.2 Key numbers table

| Number | Value | Source file | Command |
|---|---|---|---|
| Detection latency (DEAD, K=3, dt=2) | **4 s** | `tests/test_fault.py:58`; §9.1(b) | `uv run python -m pytest tests/test_fault.py -s -q` |
| Detection latency THRUSTER_OUT | **0 s** | `tests/test_failure_modes.py:211` | `uv run python -m pytest tests/test_failure_modes.py -q` |
| Pre-failure coverage (two_failure) | **0.3796 (38.0%)** | `tests/test_fault.py:160`; §9.1(b) | `uv run python -m pytest tests/test_fault.py -s -q` |
| No-recovery last-orbit coverage | **0.2205 (22.1%)** | §9.1(b); README; GATES G4 | same |
| With-recovery last-orbit coverage | **0.2698 (27.0%)** | §9.1(b); README | `uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl` |
| Recovery gain on two_failure | **+4.93 pts** (≈31% of lost coverage) | README; `tests/test_fault.py:182` | `uv run python -m pytest tests/test_fault.py -s -q` |
| Worst min_sep, two_failure | **3095.1 m @ 1620 s** | `tests/test_fault.py:145`; §9.1(b) | same |
| Worst survivor–dead clearance, 15-pair Hungarian | **1322.6 m** | `data/eval/benchmark_results.json` | `uv run python -m cubesat.benchmark --base data/scenarios/two_failure.json --out data/eval/benchmark --report data/eval/benchmark_results.json --policies do_nothing,even_split,greedy,hungarian` |
| Hungarian mean gain vs do-nothing, 15 pairs | **−2.13 pts** (worst-case retained 0.2698 vs 0.2205) | `data/eval/benchmark_results.json` | same |
| even_split worst survivor–dead | **3.4×10⁻⁹ m** (seat on a dead sat) | same | same |
| Monte Carlo (20 jittered runs) | hungarian mean **0.26915** vs do_nothing **0.22028**, mean gain **+4.886 pts** | `data/eval/monte_carlo_results.json`; GATES.md | `uv run python -m cubesat.benchmark --base data/scenarios/two_failure.json --mode monte-carlo --report data/eval/monte_carlo_results.json` |
| Max per-sat Δv, two_failure | **193.68 m/s** (sat 0, the leader) | §9.1(b); README | run command above |
| Δv vs two-impulse reference | 155.09 vs 47.81 m/s (**3.24×**) | `data/eval/dv_lower_bounds.json`; HANDOFF §3 | `uv run python -m cubesat.dv_bound --base data/scenarios/two_failure.json --p0-dir data/eval/benchmark --report data/eval/dv_lower_bounds.json --csv data/eval/dv_lower_bounds.csv` |
| CW-vs-Kepler error, 3 orbits | **3.101 m** (1 km) / **1578.5 m** (8 km) / 2984.5 m (11 km) | `cw_curve.py:61-63`; `data/eval/cw_error_report.json` | `uv run python -m cubesat.benchmark --mode cw-curve --base data/scenarios/two_failure.json --report data/eval/cw_error_report.json --csv data/eval/cw_error_curve.csv --svg data/eval/cw_error_curve.svg` |
| STM vs ODE | 1.358e-12 pos / 5.597e-10 vel (rel) | §9.1(a) | `uv run python -m pytest tests/test_hcw.py -s -q` |
| PD 1 km step | overshoot 4.99%, settle 746 s, 6.411 m/s | §9.1(a) | `uv run python -m pytest tests/test_pd.py -s -q` |
| Slot holding cost | 1.403e-12 m/s per orbit | §9.1(a) | same |
| Candidate formations per replan (two_failure) | **12** (1 amp × 12 phases) | `two_failure.json`; `allocate.py:154-161` | read the file |
| Footprint radius | 13,093 m | `coverage.py:24-27` | python one-liner in §6.1 |
| Predictor critical-seat gain | **+0.0235 pp** vs 0.5 pp threshold ⇒ CUT | GATES.md; HANDOFF §6 | see `files/ORACLE_SWEEP.md` |

---

## 10. Where to extend (explanation only)

### 10a. A nonlinear "truth model" while the planner keeps CW

**Idea:** the *world* moves with two-body + J2 + drag; the *planner and controller* still think in CW. This is honest "plan with a simple model, fly in a harder one".

- **Step site:** all motion happens in one place, the per-sat loop at `sim.py:633-644`:
  - PD branch → `controllers[i].step(...)` → `propagate_controlled` (`pd.py:77`, `hcw.py:109-116`)
  - evasion branch → `apply_accel` (`pd.py:90`)
  - coast branch → `propagate(states[i], dt, n)` (`sim.py:644`)

  A truth model replaces these three calls with "integrate the inertial deputy and chief over dt under (gravity + J2 + drag + a_LVLH), then convert back to LVLH". The *command* u can still come from `PDController.command` (`pd.py:56-65`), so PD needs no change beyond splitting "command" from "step".
- **What already exists:** `cw_curve.py` has a two-body `_two_body` RHS, `_propagate_two_body` (RK45, rtol 1e-12; `cw_curve.py:86-103`) and the LVLH↔inertial projection inside `cw_vs_kepler_errors` (`cw_curve.py:114-145`). Those are the pieces to factor into a truth-propagator module. Add J2 (μJ2R²/r⁴ terms) and drag (½ρv²·Cd·A/m) to the RHS. `live_import.py:26` already defines `J2 = 1.08262668e-3`.
- **Also affected:**
  - the chief itself must be propagated (it is no longer a fixed circle)
  - the replanner's internal `propagate` calls (`allocate.py:91-92, 112, 130, 278`) stay CW by design; that is the model mismatch you want to measure
  - the settle check (`sim.py:566`) compares true state with a CW-predicted seat
  - `keepout.py` and `dv_bound.py` assume CW logs
- **Determinism:** a fixed-step integrator is deterministic; an adaptive one (`solve_ivp`) is deterministic for fixed inputs but slow at 8515 ticks × 6 sats. A fixed-step RK4 at dt = 2 s is the obvious choice.
- **What breaks:** every golden hash (`tests/test_cli.py`, `tests/test_failure_modes.py:229`, `tests/test_oracle_sweep_v3.py`, `tests/test_policy_selection.py`, wire golden fixtures), every committed log in `data/logs/` and `data/eval/`, and every README number. This is a **locked decision** (MASTER_PROMPT §2: HCW, no poliastro). It needs approval and evidence.
- **Keep the old mode:** add a defaulted scenario field, e.g. `dynamics: Literal["cw", "two_body_j2_drag"] = "cw"`, in `scenario.py`. Branch only at `sim.py:633-644`. With the default, every canonical log stays byte-identical, the same pattern as `reassign_on_degrade` (`scenario.py:188-199`).

### 10b. New failure modes (payload/imager loss, partial thrust, comms loss)

Every new mode touches the same chain:

1. **`scenario.py:27-34` `FailureMode`:** add the enum value. Add a parameter field to `Failure` (`scenario.py:81-90`) if needed (e.g. `thrust_frac` for partial thrust).
2. **`sim.py` failure firing (`280-314`):** pick the new status. Decide whether it self-reports (like THRUSTER_OUT, `292-314`) or is only caught by heartbeat.
3. **`sim.py` status constants (`85-88`)** plus every status test:
   - heartbeat `316-320` (comms loss = silent but alive and thrusting)
   - detection `322-340`
   - coverage `346-353` (payload loss = not an imager for coverage but still flies)
   - `assignable` / `obstacles` `437-438`
   - settle `570`
   - evasion eligibility `599`
   - stepping `633-644` (partial thrust = PD with reduced a_max for that sat, e.g. a per-sat `controllers[i].a_max`)
4. **`allocate.py`:** today `seat_roles_for` (`60-79`) and the cost matrix (`183-204`) treat every assignable sat as fully capable. Capability-aware allocation (an imager-dead sat may take leader/downlink but not an imager seat) needs a capability mask in `build_cost_matrix` (e.g. infinite cost for incapable cells) and `seat_roles_for` must know who can hold what. A sat that flies but can't image should be assignable to non-imaging seats; `assignable` at `sim.py:437` would change from "status == NOMINAL" to "can thrust".
5. **`wire.py:77-82` `_STATUS_TO_WIRE`:** map the new status (else it passes through raw, `wire.py:148`). `failure_type` is preserved (`wire.py:153-154`).
6. **Frontend:** files that already handle THRUSTER_OUT/EPS_DEGRADE/degraded (found with grep):
   - `types/satellite.ts`, `utils/colors.ts`, `components/three/sceneColors.ts` (status colour)
   - `components/controls/FailureInjectionPanel.tsx`, `components/live/scenarioDraft.ts`, `components/live/FailureRow.tsx` (injection)
   - `stores/recoveryStore.ts`, `components/narration/NarrationStrip.tsx`, `components/dashboard/EventMarkers.tsx`, `utils/suspect.ts`, `components/replay/ReplayPage.tsx`, `components/pages/FaqPage.tsx` (narration, events, docs)
7. **Session live injection:** `session.py` `LiveSource.with_failure` builds the injected `Failure`. Every new parameter must be passed through, and the API request model must accept it.
8. **Tests:** pin default-inertness. Canonical sha unchanged, plus a semantics test per mode like `tests/test_failure_modes.py:93-211`.

### 10c. "Failure packs" and benchmarking across them

- **Today:** the benchmark takes **one** `--base` scenario (`benchmark.py:399`) and replaces its failures with every C(n,2) pair of **DEAD** failures at the base's times (`benchmark.py:46-59`). Policies are switched by scenario knobs (`do_nothing` = `recovery_enabled: false`, `greedy` = method toggle, `benchmark.py:62-71`) or by rebinding `cubesat.sim.replan` with try/finally restore (`benchmark.py:74-93`). That is the seam pattern; there is no core diff.
- **A failure pack** = a directory of scenario JSONs (e.g. the existing `eps_*_6sat`, `thruster_leader_6sat`, `proximity_stress`, `cascading_n8`, `leader_failure_6sat`) run **as-is**, without pair-substitution, under each policy. `run_one(scenario, policy)` (`benchmark.py:82-93`) and `metrics_from_log` (`benchmark.py:103`) already do the per-run work. What's missing is a mode that iterates files instead of pairs, writes one log per (scenario, policy) with sha256, and reports a per-pack summary.
- **Pitfall:** `scenario_for_pair` hard-codes `FailureMode.DEAD` (`benchmark.py:56-57`), so the existing 15-pair sweep never exercises THRUSTER_OUT or EPS_DEGRADE. A pack is the honest way to cover them.
- Monte Carlo can wrap any pack member as its `--base` (`monte_carlo.py:113-...`).

---

## 11. Glossary

| Term | Meaning |
|---|---|
| **LVLH** | Local-Vertical Local-Horizontal frame centred on the chief: x radial (up), y along-track (direction of flight), z cross-track (orbit normal). Rotates once per orbit. |
| **Chief / deputy** | Chief = the reference point on a circular orbit (here imaginary, the formation centre). Deputies = the actual satellites, described relative to the chief. |
| **Mean motion n** | Angular rate of a circular orbit, √(μ/a³) rad/s. 1.1068×10⁻³ rad/s at 500 km. |
| **Period** | 2π/n: one orbit, 5677 s here. |
| **HCW / CW equations** | Hill–Clohessy–Wiltshire: linearised relative-motion equations for a deputy near a chief on a circular orbit. |
| **STM (state-transition matrix)** | 6×6 matrix Φ(t) with x(t) = Φ(t)·x(0) for a linear system; exact here. |
| **Forcing matrix G** | Maps a constant acceleration held over [0, t] to the state change it causes. |
| **Zero-order hold** | Command held constant over each time step. |
| **Passive / drift-free ellipse (2:1)** | Closed relative orbit needing no thrust; along-track size is 2× radial. Condition vy0 = −2n·x0. |
| **Secular drift** | Error that grows steadily with time (not oscillating), e.g. along-track drift when the drift-free condition is violated. |
| **Slot / seat** | A target point (phase) on the formation ellipse that a satellite holds. "Seat" is used for the replanned formation. |
| **Phase offset** | Common rotation of all slots around the ellipse. |
| **PD controller** | Proportional-Derivative feedback: push proportional to position error and velocity error. |
| **ωn, ζ** | Natural frequency (stiffness) and damping ratio of the PD loop. |
| **Saturation (a_max)** | Hard cap on commanded acceleration magnitude. |
| **Δv (delta-v)** | Total velocity change produced by thrust, ∫‖a‖dt (m/s). The standard proxy for fuel spent. |
| **Bang-bang** | Full thrust one way, then full thrust the other: the minimum-time rest-to-rest manoeuvre, t = 2√(d/a_max), Δv = 2√(d·a_max). |
| **Two-impulse transfer** | Two instantaneous burns (depart, arrive) for a fixed transfer time; used as a Δv reference in `dv_bound.py`. |
| **Heartbeat** | A per-tick "I'm alive" message; missing K in a row ⇒ declared failed. |
| **Self-report** | The satellite announces its own failure (THRUSTER_OUT). |
| **Ballistic coast** | Moving under gravity alone, no thrust. |
| **Critical role** | A role held by exactly one satellite originally (leader, downlink). |
| **Re-election** | Promoting a survivor to a lost critical role. |
| **Hungarian algorithm** | Optimal one-to-one assignment minimising total cost (`scipy.optimize.linear_sum_assignment`). |
| **Greedy assignment** | Each survivor in turn takes its cheapest free seat; fast, not optimal. |
| **Cost matrix** | Table of "how bad is it to send survivor i to seat j". |
| **Formation sweep** | Trying a fixed grid of candidate formations and keeping the best feasible one. |
| **Footprint** | The ground circle an imager sees, radius h·tan(FOV/2). |
| **FOV** | Field of view; the scenario stores the half angle. |
| **Coverage** | Fraction of ground target points inside the union of imager footprints. |
| **min_sep** | Smallest distance between any two satellites at a tick. |
| **Keep-out** | A forbidden radius around another (dead) satellite. |
| **Evasion burn** | Short full-thrust push away from a too-close satellite. |
| **J2** | Earth's oblateness term; the dominant perturbation in LEO after central gravity. |
| **Drag** | Atmospheric braking; non-negligible at 500 km over days. |
| **Golden hash** | A pinned sha256 of a log; any byte change to the output fails a test. |
| **Seam** | Swapping a function at runtime by rebinding a module global (`cubesat.sim.replan`) instead of editing the core. |
| **Oracle** | A hypothetical perfect early warning (knows failure times); default off. Used to measure the *value* of prediction. |

---

## Questions / suspected issues

Listed rather than guessed. None were changed.

1. **The do-no-harm hold shuffles roles without moving anyone.** `allocate.py:267-276` returns `seats` (the re-elected, interleaved role layout) with identity pairs. `sim.py:477-482` then assigns `roles[sat] = seats[idx]` by index, so roles move between satellites that didn't move. Observed in `thruster_leader_6sat` (§9.1c): downlink moved from sat 5 to sat 4 and sat 5 became an imager, with no seat change. The hold's coverage is also estimated with the **old** `survivor_roles` (`allocate.py:268-270`) but applied with the **new** ones. The path is not documented in ARCHITECTURE.md.
2. **`except TypeError` around `replan`** (`sim.py:440-476`). This exists so seam replanners without the `current_slots` parameter (`benchmark_policies.py:42-55, 131-144`) still work. But it would also swallow a genuine TypeError raised *inside* `replan` and silently re-run without the do-no-harm check.
3. **THRUSTER_OUT keeps its role.** In `thruster_leader_6sat` the final roles have **two leaders**: sat 0 (THRUSTER_OUT) and sat 2 (§9.1c). Re-election ignores non-NOMINAL holders, but `roles[0]` is never cleared. A THRUSTER_OUT **imager** also keeps counting toward coverage while it drifts off its seat (`sim.py:350` excludes only DEAD). Arguably physical (its camera works), but it is not stated anywhere.
4. **The leader moves because of the imager interleave.** `seat_roles_for` puts imagers on even seats (`allocate.py:71-78`), which pushes the surviving leader to seat 1 (§9.1b, assignment `(0,1,leader)`). The leader then spends the most Δv (193.68 m/s). Whether a surviving critical-role holder should be allowed to keep its slot is a design question.
5. **"RECOVERED" is a loose criterion.** The tolerance is 5% of the longest transfer, position only (`sim.py:91, 533, 564-571`). For two_failure that is about 1.1 km (§5.5 arithmetic), and velocity error is ignored. A satellite could be "recovered" while still moving fast relative to its seat.
6. **The 2 km separation floor is not enforced during transfers.** It is checked only on destination formations (`allocate.py:82-97`). Evasion starts at 1 km (`scenario.py:160-162`). Measured below 2 km: 1322.6 m (benchmark), 959.4 m (eps_leader). `tests/test_fault.py:145` asserts the floor only on two_failure.
7. **Evasion is not inert on all committed scenarios.** `scenario.py:152-155` says the default radius "never fires on any canonical run". It fires on `eps_leader_6sat` (§9.1c). The claim seems to mean the G4/P0 canonical set (nominal, two_failure), which is what `tests/test_collision_avoidance.py:173` checks.
8. **The obstacle model during replan treats DEGRADED sats as coasting** (`sim.py:438` uses `status != NOMINAL`), but DEGRADED sats actually PD-hold their seat (`sim.py:634`). The separation check may then be against the wrong trajectory for a fading sat.
9. **The "lower bound" in `dv_bound.py` is a fixed-time two-impulse solution**, not a proven minimum-fuel bound. A different transfer time, or more impulses, can sometimes cost less. The ratio is a fair efficiency indicator, but calling it a "physics lower bound" (`dv_bound.py:21-23`) overstates it.
10. **The reachability Δv estimate `2√(d·a_max)`** (`allocate.py:114`) is a rest-to-rest double-integrator figure. It ignores the survivor's current relative velocity and the CW coupling, so it can disagree with the PD's real cost (193.68 m/s actual vs a 200 m/s budget, which passes; the sim does not enforce the budget during flight).
11. **Event timestamps lag.** Only one event pops per line (`sim.py:378-379`), so simultaneous events appear on later ticks (ORACLE_SWAP at 602 for t = 600; EVASIVE_MANEUVER at 2742/2744 for t = 2740). The payload `t` is correct; the line `t` is not. Consumers keyed on line time will be off.
12. **`ORACLE_ALERT` and `ORACLE_SWAP` are missing from the `sim.py:24-40` docstring event list**, though both are emitted (`sim.py:405-415`, `131`).
13. **Cross-track amplitude is hard-wired equal to radial** (`sim.py:134-146`, `allocate.py:158-159`); there is no schema field. Fine, but it is a fixed design choice worth knowing before any formation-geometry work.
14. **Platform floats.** STM error prints 1.358e-12 here vs 1.353e-12 in GATES.md, and the two_failure log sha differs from the Windows pin (§7). Semantic numbers are identical; byte pins are platform-specific.
