# Implementation notes

Per-gate notes written so an agent that has never seen the working sessions can
understand and reproduce the code. Numbers are copied from real command output;
every number carries the exact command that produced it (AGENTS.md invariant 1).

## G1 — HCW STM + passive ellipse + Kepler cross-check (2026-09-28, PASS)

### What was built

`cubesat/hcw.py` (82 lines) — unforced Hill–Clohessy–Wiltshire linear relative
motion, SI units, LVLH frame:

- Constants (`cubesat/hcw.py:19-20`): `MU = 3.986004418e14` m^3/s^2,
  `R_EARTH = 6378.137e3` m.
- `mean_motion(altitude_m)` (`cubesat/hcw.py:23`): `sqrt(MU / (R_EARTH + altitude_m)**3)`
  → 0.0011067834463349404 rad/s for 500 km (master prompt says ≈1.1068e-3).
- `stm(t, n)` (`cubesat/hcw.py:28`): the 6×6 analytic state-transition matrix,
  terms exactly as written in docs/MASTER_PROMPT.md section 3.1
  (`c = cos(n*t)`, `s = sin(n*t)`). Identity at `t = 0`.
- `propagate(state0, t, n)` (`cubesat/hcw.py:57`): `stm(t, n) @ state0` for
  scalar `t` (returns shape `(6,)`), or one STM application per element of a 1D
  time array (returns shape `(len(t), 6)`, row k = state at `t[k]`).
- `stm_propagate = propagate` (`cubesat/hcw.py:72`): alias. The tests import the
  name `stm_propagate` (tests/test_hcw.py:26); the canonical API name is
  `propagate`. Same function, either name works.
- `drift_free_state(x0, z0=0.0, *, n)` (`cubesat/hcw.py:75`): returns
  `[x0, 0, z0, 0, -2*n*x0, 0]` — the passive (drift-free) 2:1 ellipse initial
  state. `n` is keyword-only because the requested signature
  `(x0, z0=0, n)` is not valid Python (non-default after default).

`tests/test_hcw.py` — the three tests mandated by docs/MASTER_PROMPT.md
section 3.8 (test names are locked):

- `test_hcw_stm_vs_ode` (tests/test_hcw.py:64): 3 hardcoded initial states
  (position offsets ~1 km, velocity offsets ~1 m/s, no RNG), 3 orbits, analytic
  STM vs `scipy.integrate.solve_ivp` RK45 (rtol=1e-12, atol=1e-9) on the CW ODEs
  written in the test file. Asserts max relative error in position AND velocity
  ≤ 1e-6, relative to the ODE reference state norms. Prints the measured errors
  for the gate ledger.
- `test_drift_free_ellipse_closes` (tests/test_hcw.py:87): the drift-free state
  (x0 = 1000 m, z0 = 500 m, vy0 = −2·n·x0) must return to itself after one
  period `2*pi/n` within 1e-6 relative (position and velocity), via the STM;
  plus one 2:1 shape assert: at `t = pi/(2n)` the along-track excursion is
  2*x0 (analytically exactly −2000 m here).
- `test_cw_vs_kepler_error_report` (tests/test_hcw.py:103, `@pytest.mark.slow`):
  nonlinear check. Chief and chaser start on the SAME circular inertial orbit;
  the chaser is offset by the passive-ellipse state (radial amplitude 1 km,
  drift-free vy0, z0 = 500 m). Both bodies are propagated independently with
  `solve_ivp` two-body gravity (rtol=1e-12, atol=1e-9) for 3 orbits. The
  inertial relative position (chaser minus the chief the CW frame is anchored
  to) is rotated into the chief-anchored LVLH frame (x̂ = r̂, ẑ = ĥ, ŷ = ẑ×x̂)
  and compared against the CW/STM relative motion. The test PRINTS the max
  position error over the sampled times in metres and asserts only a loose
  sanity bound (< 10 km) — the measured value is recorded, not tuned.

  Inertial initial condition detail (easy to get wrong): at t = 0 the LVLH axes
  coincide with the inertial axes, and the rotating-frame velocity maps to
  inertial via the transport theorem `drho/dt|_inertial = nu + omega × rho`
  with `omega = n ẑ`, so `v_chaser0 = v_chief0 + nu0 + np.cross(omega, rho0)`.
  Getting this sign wrong produces ~114 km of error over 3 orbits (measured
  during development with a negated-sign control), far beyond the 10 km bound,
  so the test discriminates it.

`pyproject.toml` — one addition: `[tool.ruff.lint.isort] known-first-party = ["cubesat"]`.
Reason: ruff classifies imports by resolving them; when the tests landed
(tests-first) `cubesat.hcw` did not exist yet, so ruff treated it as third-party
and wanted a different import order than for resolvable modules like
`cubesat.api`. Pinning first-party keeps import order stable before and after
the module exists.

### File map

| File | Role |
|---|---|
| `cubesat/hcw.py` | CW dynamics module: constants, mean_motion, stm, propagate (+ alias stm_propagate), drift_free_state |
| `tests/test_hcw.py` | The three G1 tests (names from MASTER_PROMPT 3.8); also defines the import contract for cubesat/hcw.py in its module docstring |
| `docs/MASTER_PROMPT.md` section 3.1 | Formula source (STM rows, drift-free condition, ODEs) and the "must verify" list |
| `docs/MASTER_PROMPT.md` section 3.8 | Mandated test names |
| `GATES.md` | G1 ledger row (evidence, key numbers), open risks, README-allowed numbers |

### Units policy

SI internally everywhere (AGENTS.md invariant 3): position m, velocity m/s,
time s, mean motion rad/s, mu m^3/s^2. State ordering is `[x, y, z, vx, vy, vz]`
in the chief LVLH frame: x radial, y along-track, z cross-track (AGENTS.md
invariant 4). No wall-clock, no RNG (invariant 2) — the tests hardcode their
initial states. Unit conversion happens only at the UI edge in later gates.

### Formula source

All formulas are the analytic CW solution written in docs/MASTER_PROMPT.md
section 3.1. It was verified numerically here, per the master prompt's "verify,
do not trust": STM vs ODE integration, closure, 2:1 shape, and the nonlinear
two-body cross-check (numbers below).

### Measured numbers and the commands behind them

Recorded 2026-09-28 on Windows, repo at the `gate-1-pass` tag
(commit `gate-G1: HCW STM, passive ellipse, Kepler cross-check (max CW-vs-Kepler error measured)`).

1. STM-vs-ODE max relative error: position **1.353e-12**, velocity **5.599e-10**
   (asserted bound 1e-6), over 3 orbits for the 3 hardcoded states.

   ```
   uv run pytest tests/test_hcw.py -s -q
   ...
   test_hcw_stm_vs_ode: max position relative error = 1.353e-12, max velocity relative error = 5.599e-10
   ..
   ```

2. CW-vs-Kepler max position error: **3.101 m** over 3 orbits (loose sanity
   bound 10 km; measured value recorded, not tuned).

   ```
   uv run pytest tests/test_hcw.py -s -q
   ..test_cw_vs_kepler_error_report: max position error over 3 orbits = 3.101 m
   .
   ```

3. Full suite green:

   ```
   uv run pytest -q
   ............    [100%]
   ```

   (12 passed: 9 pre-existing from G0 + 3 new; counts line from the same code
   state via `uv run pytest` → `12 passed in 1.62s`.)

### Scope notes / caveats

- The 3.101 m figure is measured only for the 1 km radial / 500 m cross-track
  passive ellipse over 3 orbits. CW linearization error grows with separation
  (MASTER_PROMPT 3.1 pitfall) — re-measure with formation-scale states before
  citing validity for larger reconfigurations.
- Physics verifier (independent) returned "none" — it agreed with the
  implementation. The only test-file change after verification was adding the
  measured-error print to `test_hcw_stm_vs_ode` (no assertion changes) so the
  gate ledger can cite the number with its command.
- `stm` is the unforced STM; thrusting dynamics (STM step + control) were G2
  scope — implemented and verified in G2, see below.

### Reproduce

```
uv sync --locked
uv run pytest tests/test_hcw.py -s -q   # the two measured numbers above
uv run pytest -q                        # full suite, includes the slow Kepler test
```

## G2 — PD controller with saturation + per-satellite delta-v (2026-09-28, PASS)

### What was built

`cubesat/hcw.py` additions (dynamics, ~48 lines):

- `forcing_matrix(t, n)` (`cubesat/hcw.py:85`): `G(t) = ∫₀ᵗ Φ(s) ds · B` (B = [0; I]),
  the analytic integrals of the MASTER_PROMPT 3.1 rows. Maps a constant LVLH
  acceleration held over `[0, t]` to the state it produces. Double-integrator limit
  at small t: `G ≈ [[t²/2·I₃], [t·I₃]]`.
- `propagate_controlled(state0, accel, t, n)` (`cubesat/hcw.py:109`):
  `Φ(t)·x₀ + G(t)·a` — the exact zero-order-hold step for constant thrust over the
  step. Verified against RK45 of the forced CW ODEs (below), same
  verify-don't-trust discipline as G1.

`cubesat/pd.py` (new, 77 lines):

- `A_MAX_DEFAULT = 1e-2` m/s² (research patch #1, overrides the master prompt's
  1e-4; cold-gas class, **ASSUMED** ~8 kg CubeSat / ~150 mN thruster — the mass and
  thrust figures are an unverified assumption, labelled as such). Scenario
  parameter; `data/scenarios/nominal.json` already carries 0.01.
- `bang_bang_time_lower_bound(d_m, a_max)` = `2·sqrt(d/a_max)`: the rest-to-rest
  reconfiguration lower bound, logged per reconfiguration distance (research
  patch #1). Informational, not asserted against the closed loop: CW natural
  dynamics can assist or oppose, so a PD trajectory is not bound by it in general.
- `PDController(wn, zeta=1.0, a_max=A_MAX_DEFAULT)` — one instance per satellite:
  - `command(r, v, r_ref, v_ref)`: `u = -Kp(r - r_ref) - Kd(v - v_ref)`,
    `Kp = wn²`, `Kd = 2ζwn`. Saturation clamps the **vector magnitude**
    (`‖u‖ ≤ a_max`) — a per-axis clamp would allow √3·a_max, which no single
    thruster delivers. `v_ref` is the moving slot's own ellipse velocity (the
    static-target form fights the 2:1 motion — see test_passive_slot_low_dv).
  - `step(state, r_ref, v_ref, dt, n) -> (state_next, u)`: command from the error
    at the current instant, hold over `[t, t+dt)`, advance with
    `propagate_controlled`. Accumulates `dv_used += ‖u‖·dt` (m/s) — per-satellite
    delta-v, feeds the MASTER_PROMPT section 5 log field `dv_used` from G4 on.
  - No wall clock, no RNG: fixed dt, pure float ops on hardcoded states
    (AGENTS.md invariant 2).

`tests/test_pd.py` — the three names mandated by MASTER_PROMPT 3.8 plus one extra:

- `test_pd_step_response`: chaser at the chief at rest, slot = passive ellipse with
  radial amplitude = step d = 1000 m (moving reference via `hcw.propagate`).
  Settle criterion: first time after which the error norm never leaves the 5% band.
  Overshoot criterion for a rotating reference: worst error after first entering
  the 5% band, relative to the initial error (classic %-overshoot along a fixed
  direction is ill-posed here; a ringing response exits the band and fails this
  check — the monotone critically-damped approach reads ≈ the band-entry value,
  4.99%, which is the definition's floor, not a fly-by distance). Settle target is
  computed, not tuned: `2 × bang-bang bound = 4·sqrt(d/a_max)` = 1265 s.
- `test_saturation_respected`: asserts `‖u‖ ≤ a_max` every step AND that
  saturation actually engaged (`max ‖u‖ ≥ 0.999·a_max`, so the test is not
  vacuous), plus the research-patch default `A_MAX_DEFAULT == 1e-2`. Geometry:
  chaser and slot on the SAME 1 km passive ellipse a quarter period apart in phase
  (both endpoints drift-free — the slot-to-slot reassignment case G4 faces);
  initial command ≈ 27× a_max.
- `test_passive_slot_low_dv`: chaser starts exactly on its slot; over one full
  ellipse period the error stays ~float noise and delta-v is ~0. This
  discriminates the moving-reference form: a static-target controller would burn
  ~a_max every step (≈ tens of m/s per orbit) and drift off the slot.
- `test_forced_propagator_matches_ode` (extra, beyond the mandated three): RK45
  cross-check of `propagate_controlled` — the G2 analogue of G1's STM-vs-ODE.

### Design constraint discovered (matters for G4)

A rest-at-origin chase of a LARGE-amplitude slot diverges under a_max = 1e-2: the
slot's along-track speed is 2·n·A (≈ 11 m/s for A = 5 km) and a saturated PD can
never match it — measured during development: position error grew to ~5×10⁵ m over
8000 s (`uv run pytest tests/test_pd.py -s -q` with the pre-fix 5 km geometry).
G4's role reassignment must therefore reassign slots **on the same ellipse**
(phase repositioning — catchable, measured below); forming a different-sized
ellipse from rest needs a phased/multi-rev transfer or more thrust.

### Measured numbers and the commands behind them

Recorded 2026-09-28 on Windows.

1. Step response (d = 1000 m, wn = 0.01, ζ = 1, a_max = 1e-2, dt = 2 s):
   overshoot **4.99%** (limit 5%), t_settle **746 s** (target 1265 s), max |u| =
   **0.0100 m/s²** (= a_max), dv_used **6.411 m/s** — within 1.5% of the
   bang-bang-optimal Δv 2·√(d·a_max) = 6.32 m/s.

   ```
   uv run pytest tests/test_pd.py -s -q
   test_pd_step_response: overshoot = 4.99% (limit 5%), t_settle = 746 s (target 1265 s = 2x bang-bang bound 632 s), max |u| = 0.0100 m/s^2 (a_max = 0.01), dv_used = 6.411 m/s
   ```

2. Saturation (quarter-phase same-ellipse transfer, d = 2236.1 m): max |u| =
   **0.010000 m/s²** (≤ a_max, and saturation engaged), bang-bang lower bound
   **945.7 s**, t_settle **1966 s**, dv_used **20.176 m/s**.

   ```
   test_saturation_respected: max |u| = 0.010000 m/s^2 (a_max = 0.01), bang-bang lower bound for d = 2236.1 m: t >= 945.7 s, t_settle = 1966 s, dv_used = 20.176 m/s
   ```

3. Occupied passive slot (1 km radial + 500 m cross-track, one orbit): max
   position error **2.198e-11 m**, dv_used **1.410e-12 m/s**, max |u|
   **1.4e-15 m/s²**.

   ```
   test_passive_slot_low_dv: max position error over one orbit = 2.198e-11 m, dv_used = 1.410e-12 m/s, max |u| = 1.411e-15 m/s^2
   ```

4. Forced propagator vs RK45 (constant accel, 300 s): position rel err
   **2.283e-13**, velocity rel err **2.323e-13** (asserted ≤ 1e-8).

   ```
   test_forced_propagator_matches_ode: position relative error = 2.283e-13, velocity relative error = 2.323e-13
   ```

5. Full suite green, lint clean:

   ```
   uv run pytest  →  16 passed in 1.97s          (12 pre-existing + 4 new)
   uv run ruff check .  →  All checks passed!
   ```

6. Dockerfile build re-verified first-hand (stale "unverified" risk row retired):
   `docker build -t cubesat-g2-verify .` → exit 0, image
   `sha256:391d099d53ea092fa5b5c04d57e4b54c51441a315988068c46fb3fec090b948e`,
   816 MB, `uv sync --locked --no-dev` inside. Container RUN + healthcheck not yet
   exercised — that stays with G6.

### File map

| File | Role |
|---|---|
| `cubesat/hcw.py` | + forcing_matrix, propagate_controlled (exact constant-thrust CW step) |
| `cubesat/pd.py` | A_MAX_DEFAULT, bang_bang_time_lower_bound, PDController (command / step / dv_used) |
| `tests/test_pd.py` | 3 mandated G2 tests + forced-propagator ODE cross-check |
| `docs/MASTER_PROMPT.md` section 3.2 | Control law, saturation, bang-bang bound, must-verify list |
| `docs/MASTER_PROMPT.md` research patch #1 | a_max 1e-2 override + per-reconfig bound logging |
| `GATES.md` | G2 ledger row, Docker risk row retired, README-allowed numbers |

### Units policy

Unchanged from G1: SI everywhere, state `[x, y, z, vx, vy, vz]` in chief LVLH;
`dv_used` is m/s (Δv = ∫‖u‖dt); `a_max` and commands are m/s². No conversion
anywhere in this code path.

### Reproduce

```
uv sync --locked
uv run pytest tests/test_pd.py -s -q   # all four measured number sets above
uv run pytest -q                       # full suite: 16 passed
uv run ruff check .                    # All checks passed!
```

## G3 — Coverage metric + 6-sat nominal run + deterministic JSONL logger (2026-09-28, PASS)

### What was built

`cubesat/coverage.py` (new, 58 lines) — the coverage metric, fixed exactly as
docs/MASTER_PROMPT.md section 3.4 defines it (never retuned; research patch #2:
tune slot spacing / FOV instead):

- `footprint_radius(altitude_m, fov_half_angle_rad)` (`cubesat/coverage.py:24`):
  `r_f = h·tan(FOV/2)`. The scenario stores FOV/2 directly
  (`Sensor.fov_half_angle_deg`), so the argument is the half angle. Test-pinned
  against whole-angle bugs with hardcoded literals (tan(1°)·500 km =
  8727.532464108792 m, tan(2°)·500 km = 17460.384745873864 m).
- `target_grid(step_m, extent_m)` (`cubesat/coverage.py:30`): square (y, z) grid,
  −extent..+extent both axes, fixed construction order. Nominal: 2 km step,
  30 km half-extent → 31×31 = 961 points.
- `coverage_fraction(centers_yz, grid, radius_m)` (`cubesat/coverage.py:40`):
  fraction of grid points within `r_f` of ANY center = union of footprint discs,
  computed as a boolean OR of per-center masks. Removing a center can only shrink
  the covered set → `test_coverage_monotonic_in_sats` holds EXACTLY (no epsilon).
- Model approximations (stated, deliberate): nadir-pointing imager onto a flat
  ground plane h below the chief; footprint center = satellite (y, z); |x| ≤
  formation amplitude (11 km) << h (500 km), so `r_f` uses the chief altitude per
  the master prompt formula.

`cubesat/sim.py` (new, 187 lines) — pure sim core + the versioned log-line model:

- `slot_initial_state(radial_amp_m, cross_amp_m, phase_rad, n)`
  (`cubesat/sim.py:41`): `[A·cosφ, −2A·sinφ, B·cosφ, −A·n·sinφ, −2A·n·cosφ,
  −B·n·sinφ]`. This is the phase-shifted point of ONE common passive relative
  orbit: x = A·cos(nt+φ), y = −2A·sin(nt+φ), z = B·cos(nt+φ). Drift-free because
  vy0 = −2n·x0 (the vx0 = −A·n·sinφ term only shifts phase — the secular-y
  cancellation is independent of vx0, derived from the G1 STM rows). Do NOT use
  `hcw.drift_free_state` for phase-spaced slots: it forces vx0 = 0, which gives
  every slot a different ellipse amplitude (slots bunch instead of spreading
  along one orbit). Test-pinned: slots 0 and 3 close after one period (1e-8 rel).
- `build_slots(scenario, n)` (`cubesat/sim.py:63`): sat i on slot i, phase =
  phase_offset_deg + 360·j/n_slots. Cross-track amplitude B is not a schema
  field → B = A (planar relative orbit, z in phase with x). Consequence that
  matters for coverage: with B = 0 the slots at φ and 180°−φ would share the
  same (y, z) ground position (y = −2A·sinφ is symmetric about 90°) and their
  footprints would coincide exactly; B = A spreads the 6 ground centers around
  a ring instead.
- `run_scenario(scenario)` (`cubesat/sim.py:79`): per tick k (t = k·dt, no float
  accumulation), records the tick line, then steps each satellite with
  `PDController.step` against its own slot's current state (`hcw.propagate`).
  Guards `n_sats == n_slots` (G3 mapping; G4 relaxes). Guards nothing else —
  no failures until G4.

`cubesat/run.py` (rewritten, 59 lines) — I/O edge only: parse args, load
scenario, `run_scenario`, write JSONL with `sort_keys=True` and `newline="\n"`
(keeps log bytes platform-stable). Prints `coverage_mean_last_orbit` to stdout.
The G0 INIT header line is kept (tests/test_cli.py pins it; replay metadata).

### Log schema (MASTER_PROMPT section 5, v = 1)

One line per tick: `{v, t, state, sats: [{id, role, status, r, v, dv_used}],
coverage, min_sep}`; `event` key is present only when there is an event.
Event contract designed NOW, emitted by G4 (docstring in `cubesat/sim.py`):

- `FAILURE_DETECTED`: payload `{sat_id, mode, t_fail, t_detect}`
- `ASSIGNMENT`: payload `{assignments: [{sat_id, slot_index, role}], method, cost_total}`

Two non-tick lines bracket the run: the INIT header (v, t=0, state INIT,
scenario, seed, n_sats — G0 metadata) and one SUMMARY line
(`coverage_mean_last_orbit` = time-averaged coverage over the last orbit,
window [t_end − 2π/n, t_end], MASTER_PROMPT 3.4). G3 ticks carry state NOMINAL
and status NOMINAL; the state machine arrives in G4.

### Determinism (AGENTS.md invariant 2)

No wall clock, no RNG anywhere on the log path (the seed is logged, unused by
the G3 sim). Satellites iterate in id order, grid in fixed construction order,
pairs i<j; `json.dumps(..., sort_keys=True)`; numpy float64 only, `.tolist()`
converts before JSON (np.float64 would raise TypeError in json — loud, not
silent). `t = k·dt` (multiplication, not accumulation). Evidence: the full
nominal run twice → identical sha256; short run pinned to a golden hash.

### Tuning the metric to be meaningful (research patch #2)

The pre-G3 nominal.json (radial_amp_km 1.0, FOV 1.2°) would have been
meaningless: slot ground spacing ≤ 2 km vs r_f = 10.5 km → footprints fully
overlap, coverage ~independent of imager count. Sweep (60 samples over one
orbit, production functions, scratch run — not committed; mean coverage with 4
imagers / worst-pair 2-imager no-recovery drop):

| A km | FOV° | r_f km | cov4 | drop_min | drop_max |
|---|---|---|---|---|---|
| 8 | 1.2 | 10.47 | 0.272 | 0.095 | 0.120 |
| 9 | 1.5 | 13.09 | 0.398 | 0.125 | 0.170 |
| 10 | 1.5 | 13.09 | 0.425 | 0.148 | 0.188 |
| 10 | 1.6 | 13.97 | 0.456 | 0.150 | 0.197 |
| 11 | 1.5 | 13.09 | 0.438 | 0.166 | 0.199 |
| 11 | 2.0 | 17.46 | 0.613 | 0.164 | 0.248 |

Chosen: **radial_amp_km 11.0, fov_half_angle_deg 1.5** (r_f 13.09 km, in the
patch-#2 band) — smallest-formation candidate whose worst-pair drop clears 15
points with margin (A = 10/1.5 misses at 0.148; A = 10/1.6 sits exactly on
0.150). Grid stays 30 km half-extent / 2 km step: a larger extent dilutes the
drop below 15 points (the metric couples grid extent to formation size — the
target box is where the formation images; footprints spill ~5 km past it in y).

### Measured numbers and the commands behind them

Recorded 2026-09-28 on Windows.

1. Coverage (nominal, no failures): mean over one orbit **0.4387**, tick range
   0.4266–0.4547; min_sep 15.56–17.39 km; per-sat dv_used ≤ 1.6e-11 m/s.

   ```
   uv run python -m cubesat.run --scenario data/scenarios/nominal.json --seed 42 --out data/logs/nominal.jsonl
   wrote data\logs\nominal.jsonl
   coverage_mean_last_orbit = 0.438700
   ```

   (2841 lines = INIT + 2839 ticks + SUMMARY; log gitignored, NOT committed.)

2. Metric-level no-recovery drop (research patch #2 design target): killing 2 of
   the 4 imagers drops time-averaged coverage by **16.65 points** (worst imager
   pair) to **19.99 points** (best) — ≥ 15 required. Monotonicity exact under
   every single removal at 12 times across the orbit; union of 4 imagers (0.439)
   strictly exceeds the best single imager (0.137) → footprints do not fully
   overlap.

   ```
   uv run pytest tests/test_coverage.py -s -q
   test_coverage_monotonic_in_sats: mean coverage over one orbit (4 imagers) = 0.4390; 2-imagery-death no-recovery drop min = 0.1665, max = 0.1999 (target >= 0.15, research patch #2)
   ```

3. Byte determinism: the command in (1) run twice → identical sha256
   `6169c266d31191f7065a890f107e98c976a4e4122e2c6ebe656db7d08025a242`. The
   short-run regression (nominal.json trimmed to 600 s, generated inside the
   test) is pinned to golden sha256
   `c95f31b872b9134db57c43763d3bc67bb1e42c056beb7378c5177172758696f6`
   (tests/test_cli.py). Any change to the sim, log schema, or nominal.json
   changes the golden and must be acknowledged consciously.

   ```
   uv run pytest tests/test_cli.py::test_run_is_byte_deterministic -q   # passed
   ```

4. CW-vs-Kepler nonlinear error at the NEW formation scale (radial 11 km /
   cross-track 11 km, slot at phase π/2 → 22 km along-track from the chief),
   3 orbits, G1's method (chief + chaser integrated with two-body solve_ivp
   rtol 1e-12, relative state rotated into chief LVLH, vs analytic CW):
   **2984.5 m** (vs 3.101 m at the G1 1 km ellipse). Recorded in the GATES.md
   open-risks row. Measured via a scratch `uv run python` heredoc on 2026-09-28
   reproducing tests/test_hcw.py::test_cw_vs_kepler_error_report with the slot
   state above — the honest cost of the patch-#2 formation scale; carry it into
   G4 Δv/reconfig claims and the G7 README honesty section.

5. Full suite green, lint clean:

   ```
   uv run pytest -q  →  ....................  [100%]   (20 passed: 16 pre-existing + 4 new)
   uv run ruff check .  →  All checks passed!
   ```

### File map

| File | Role |
|---|---|
| `cubesat/coverage.py` | footprint_radius, target_grid, coverage_fraction (union of discs) |
| `cubesat/sim.py` | slot_initial_state, build_slots, run_scenario + log-line/event contract |
| `cubesat/run.py` | CLI I/O edge: scenario → JSONL lines, INIT header + SUMMARY |
| `tests/test_coverage.py` | test_coverage_monotonic_in_sats (+ footprint/grid contract pins) |
| `tests/test_cli.py` | test_run_is_byte_deterministic (golden sha256) + short-scenario helper |
| `data/scenarios/nominal.json` | radial_amp_km 11.0, FOV 1.5° (tuned per patch #2); 1 leader / 4 imagers / 1 downlink |
| `docs/MASTER_PROMPT.md` §3.4, §3.5, §5, §3.8 + patch #2 | formula/behavior source for everything above |

### Scope notes / caveats for G4+

- G3 has no failure injection: status/state are NOMINAL everywhere, `event` is
  never emitted, seed is unused by the sim. G4 fills the designed event contract.
- The no-recovery drop in (2) is METRIC-level (remaining imagers keep their
  slots, positions from the CW slots) — the true no-recovery baseline curve with
  failure detection and coasting dead sats is G4's `two_failure` scenario; its
  numbers may differ slightly.
- test_two_failures_reduce_coverage_visibly (research patch #2) is deliberately
  NOT written here: it needs G4's failure injection and the two_failure scenario.
- CW linearization error at formation scale is 2984.5 m over 3 orbits (see (4));
  positions in the log are CW-consistent, not Kepler-true.

### Reproduce

```
uv sync --locked
uv run pytest tests/test_coverage.py -s -q    # monotonicity + patch-#2 drop evidence
uv run pytest -q                              # full suite: 20 passed
uv run ruff check .                           # All checks passed!
uv run python -m cubesat.run --scenario data/scenarios/nominal.json --seed 42 --out data/logs/nominal.jsonl
```
