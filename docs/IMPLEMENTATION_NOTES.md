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
  (`cubesat/hcw.py:119`): `[A·cosφ, −2A·sinφ, B·cosφ, −A·n·sinφ, −2A·n·cosφ,
  −B·n·sinφ]`. This is the phase-shifted point of ONE common passive relative
  orbit: x = A·cos(nt+φ), y = −2A·sin(nt+φ), z = B·cos(nt+φ). Drift-free because
  vy0 = −2n·x0 (the vx0 = −A·n·sinφ term only shifts phase — the secular-y
  cancellation is independent of vx0, derived from the G1 STM rows). Do NOT use
  `hcw.drift_free_state` for phase-spaced slots: it forces vx0 = 0, which gives
  every slot a different ellipse amplitude (slots bunch instead of spreading
  along one orbit). Test-pinned: slots 0 and 3 close after one period (1e-8 rel).
- `build_slots(scenario, n)` (`cubesat/sim.py:65`): sat i on slot i, phase =
  phase_offset_deg + 360·j/n_slots. Cross-track amplitude B is not a schema
  field → B = A (planar relative orbit, z in phase with x). Consequence that
  matters for coverage: with B = 0 the slots at φ and 180°−φ would share the
  same (y, z) ground position (y = −2A·sinφ is symmetric about 90°) and their
  footprints would coincide exactly; B = A spreads the 6 ground centers around
  a ring instead.
- `run_scenario(scenario)` (`cubesat/sim.py:80`): per tick k (t = k·dt, no float
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

## G4 — Failure injection, detection, two-step allocation, state machine, baseline (2026-09-28, PASS)

### What was built

`cubesat/allocate.py` (new, ~250 lines) — the two-step allocation (MASTER_PROMPT 3.3):

- `seat_roles_for(survivor_roles, original_roles)` (`cubesat/allocate.py:60`): the new
  role multiset for k seats. Critical roles (count == 1 in the original formation:
  leader, downlink) whose holder died are RE-ELECTED first, each taking a seat from
  the majority role (deterministic: first-occurrence iteration, `dict.fromkeys` — no
  sets); the multiset is then laid out with imager seats on EVEN indices so the
  coverage-bearing seats are as spread as the k evenly-spaced slots allow (k=4 →
  imagers 180° apart).
- `select_formation(...)` (`cubesat/allocate.py:158`): step 1. Candidates = k
  phase-spaced slots on ONE passive ellipse swept over `allocation.amp_sweep`
  (radial-amplitude multipliers) x `allocation.phase_sweep_deg` (phase offsets),
  both scenario grids. A candidate is feasible iff (a) pairwise separation over 72
  orbit samples stays >= `min_sep_km`, with coasting dead/THRUSTER_OUT satellites
  propagated as obstacles (they never freeze, AGENTS.md 5), and (b) a perfect
  survivor→seat matching exists whose per-transfer bang-bang Δv estimate
  2·sqrt(d·a_max) fits `dv_budget_mps` (checked with `linear_sum_assignment` on a
  0/1 matrix). Among feasible candidates: max measured coverage (union of imager
  seats' footprints over the 72 samples); exact ties keep the FIRST in sweep order.
  Raises `RuntimeError` if nothing is feasible (loud, not silent).
- `build_cost_matrix(...)` (`cubesat/allocate.py:186`): C[i,j] = w1·dist_norm +
  w2·dist_norm/fuel_i + w3·role_mismatch; the first two terms normalized to [0,1]
  across the matrix (fuel_i = remaining Δv budget); plus `_TIE_EPS = 1e-9` times the
  row-major cell index (the master prompt's "tiny index-based epsilon"). Rows =
  survivors, cols = seats, rectangular.
- `solve_assignment(cost, method)` (`cubesat/allocate.py:212`): "hungarian" →
  `linear_sum_assignment` (research patch: scipy docs are silent on ties — the
  100-run determinism test is the guard); "greedy" → survivors in row order take
  their nearest available seat (min cost, tie → lowest column). A deterministic
  SIZE cap (`_MAX_COST_CELLS = 4096`) forces the fallback on pathological inputs —
  a wall-clock timeout would break reproducibility (AGENTS.md 2). The scenario
  toggle `allocation.method` forces greedy for the demo's graceful degradation.
- `replan(...)` (`cubesat/allocate.py:240`): orchestrates step 1 + step 2, returns
  (plan, pairs, cost_total, method, max_transfer_m, cost_matrix).

`cubesat/sim.py` (rewritten, ~300 lines) — G3 sim + the G4 mission layer:

- Failure schedule: `failures` sorted by (t, sat_id), fired at the first tick with
  t >= failure.t, BEFORE that tick's heartbeat. DEAD → status DEAD (silent);
  THRUSTER_OUT → status THRUSTER_OUT (keeps reporting, cannot maneuver — optional
  mode, minimal handling: coasts, excluded from reassignment, still counted as an
  imager for coverage if it was one).
- Heartbeat/detection: every non-DEAD sat reports each tick; a DEAD sat's missed
  counter increments (the firing tick's heartbeat already counts as missed), and at
  `detection.missed_ticks_k` consecutive misses the failure is declared: event
  FAILURE_DETECTED {sat_id, mode, t_fail, t_detect}; detection latency =
  t_detect − t_fail = (K−1)·dt for a tick-aligned failure (4 s for K=3, dt=2).
- Swarm state machine, logged per tick in the `state` field: NOMINAL →
  FAILURE_DETECTED → REPLANNING → RECONFIGURING → RECOVERED; a new detection
  re-enters FAILURE_DETECTED from any state. Each transition lasts exactly one
  tick: detection at tick k logs FAILURE_DETECTED (with the FAILURE_DETECTED
  event); the between-step phase then advances to REPLANNING (event STATE
  {from, to} on the next line); the next between-step RUNS THE REPLANNER (between
  sim steps, MASTER_PROMPT 3.5) and advances to RECONFIGURING (event ASSIGNMENT on
  the next line); the RECOVERED check (all assigned sats within tolerance of their
  seats) runs each between-phase and advances to RECOVERED (event STATE). Tolerance
  = max(0.05 · max transfer distance at assignment, 1 m).
- With `recovery_enabled = false`: detection still fires (and is logged), the
  machine stops at FAILURE_DETECTED, no replanning, survivors hold their original
  slots — the no-recovery baseline.
- Dead and THRUSTER_OUT sats coast: `propagate(state, dt, n)` — never frozen, and
  ALWAYS inside the min_sep pairwise loop (AGENTS.md 5). A sat that dies
  mid-maneuver has a non-drift-free state and drifts secularly through the
  formation — a real collision hazard the demo shows (two_failure's sat 2 dies
  mid-burn; see measured numbers).
- Events are a FIFO with at most one popped per tick line: transitions queued in
  the between-phase pop on the NEXT tick (whose state is the new one — coherent);
  a second detection in the same tick as a queued transition delays that
  transition's event by one tick (the payload times remain exact). Log schema
  extension vs G3: ASSIGNMENT payload = {assignments: [{sat_id, slot_index,
  role}], method, cost_total, formation: {radial_amp_m, phase_offset_rad}} (the
  formation field is new — G5 needs it for slot ghosts); event type STATE added.

`cubesat/hcw.py` — `slot_initial_state` moved here from sim.py (identical math;
the G4 allocator builds candidate formations from it and must not import the sim
loop — circular import). sim.py imports it back; `build_slots` stays in sim.py.

`cubesat/scenario.py` — new fields, all defaulted so nominal.json (unchanged file)
still loads and the G3 golden-hash short run stays byte-identical:
`recovery_enabled: bool = True`, `detection: Detection` (missed_ticks_k = 3),
`allocation: Allocation` (w1=1.0, w2=0.5, w3=2.0, min_sep_km=2.0, dv_budget_mps=100,
amp_sweep=[1.0], phase_sweep_deg=[0,60,...,300], method="hungarian").

`data/scenarios/two_failure.json` — the primary demo: 6 sats (1 leader, 4 imagers,
1 downlink), A=11 km slots, failures kill IMAGERS sat 1 (t=1200) and sat 2
(t=1500, DEAD); duration 17028 s (3 orbits); a_max_mps2 = **0.1** (see the finding
below); allocation grids as above. Keeping leader+downlink alive and killing two
imagers is deliberate: the no-recovery baseline keeps 2 imagers (drop ~20 pts per
patch #2) while recovery re-spaces the two surviving imagers 180° apart — the
baseline comparison then shows a real gain.

### The a_max finding (why two_failure carries 0.1, and what it costs)

The task assumed G2's PD reuses directly for reconfiguration. MEASURED (scratch
`uv run python` experiments, 2026-09-28): at the patch-#2 formation scale
(A = 11 km) the G2 PD (wn=0.01, a_max=1e-2) DIVERGES on every same-ellipse
slot-to-slot transfer — even a 10° gap (2.7 km initial error) runs away to
2841 km in 3 orbits; the gain ladder wn ∈ {2e-4 … 0.01} all fail (mid/low wn sit
in the linear-unstable region of the CW PD loop; wn=0.01 saturates and its
burn-induced Coriolis radial oscillations — amplitude ~2·a·t_burn/n — exceed the
damping authority a_max/Kd = 0.5 m/s). One-imulse/two-impulse feedforward
transfers were prototyped and also rejected (arc-execution errors 27–83 km; the
exact-arc 6×6 solve needs 120–570× a_max; receding-horizon MPC converges but
costs 74–149 m/s and fragile handovers). At a_max = 0.1 the UNCHANGED G2 PD
converges every transfer in 0.2–0.31 orbits. Research patch #1 explicitly keeps
a_max a scenario parameter ("Keep it a scenario param"), so two_failure uses
0.1 m/s² — a higher-thrust variant of the assumed cold-gas class (0.1 m/s² on the
ASSUMED 8 kg ≈ 0.8 N; label as an assumption). The 1e-2 default is untouched in
pd.py and nominal.json. Recorded in the GATES.md decisions log; flag for user
ratification. The Δv bill is heavy (below) — the honest alternative is MPC
impulse maneuver machinery (~2–5× less Δv), out of G4 scope.

### Measured numbers and the commands behind them

Recorded 2026-09-28 on Windows.

1. Headline baseline (MASTER_PROMPT 3.4 / gate G4): last-orbit mean coverage on
   two_failure — WITH recovery **0.2723** vs NO recovery **0.2390** (+3.33 pts);
   the no-recovery drop from the pre-failure window is 0.4387 → 0.2390 =
   **19.97 pts** (>= 15, research patch #2).

   ```
   uv run pytest tests/test_fault.py -s -q
   test_min_separation_never_below_threshold: worst min_sep = 5262.4 m at t = 1690 s (threshold 2000 m, 8515 ticks incl. reconfiguration transfers)
   test_two_failures_reduce_coverage_visibly: no-recovery mean coverage pre-failure = 0.4387, last orbit = 0.2390, drop = 19.97 pts (target >= 15, research patch #2)
   test_recovery_beats_no_recovery: last-orbit mean coverage with recovery = 0.2723, without = 0.2390, gain = 3.33 pts
   ```

2. CLI + byte determinism: 8517 lines (INIT + 8515 ticks + SUMMARY), run twice →
   identical sha256 `fba21cec52365bffbcd7f663f62c7d025313a6f276f86ac4d3a0d31905c1bb09`.

   ```
   uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 --out data/logs/two_failure.jsonl
   wrote data\logs\two_failure.jsonl
   coverage_mean_last_orbit = 0.272276
   ```

3. Mission timeline (from the committed-command log): FAILURE_DETECTED sat 1 at
   t=1204 (latency 4 s), REPLANNING 1206, ASSIGNMENT (hungarian, k=5) 1208;
   FAILURE_DETECTED sat 2 at t=1504 (latency 4 s, MID-RECONFIGURATION), REPLANNING
   1506, ASSIGNMENT (hungarian, k=4, cost 2.2699, formation φ0=0, A=11 km — imager
   seats 180° apart at phases 0/180) 1508; RECOVERED t=3928 s. Sat 2 dies
   mid-maneuver (29.40 m/s burned) and drifts secularly through the formation
   thereafter — the dead-sat collision hazard of AGENTS.md 5, visible in the log.

4. Worst min_sep over the whole recovery run: **5262.4 m at t=1690 s** (during
   transfers) vs the 2000 m scenario threshold — the formation feasibility check
   (seat/obstacle separation) does NOT model transfer paths, but the measured
   transfers hold the threshold everywhere (command in (1)).

5. Per-satellite Δv at run end (log, last tick): sat 0 (leader, 90° reassignment)
   205.92; sat 1 (dead on slot) 0.00; sat 2 (dead mid-burn) 29.40; sat 3 (kept its
   seat) 113.19; sat 4 (120° reassignment) 280.25; sat 5 (30°) 82.26 m/s. Heavy —
   the a_max=0.1 saturated PD is ~2.4× the bang-bang Δv and reacts to failure 1
   before failure 2 lands; recorded honestly, see the finding above.

6. Full suite green, lint clean: `uv run pytest -q` → 30 passed (20 pre-existing +
   10 new); `uv run ruff check .` → All checks passed! The G3 golden-hash
   short-run test still passes — the no-failure path is byte-identical to G3.

### File map

| File | Role |
|---|---|
| `cubesat/allocate.py` | seat_roles_for, select_formation (step 1), build_cost_matrix + solve_assignment (step 2), replan |
| `cubesat/sim.py` | G3 sim + failure schedule, heartbeat detection, state machine, coasting, replan-between-steps, event FIFO |
| `cubesat/scenario.py` | + recovery_enabled, Detection, Allocation (all defaulted) |
| `cubesat/hcw.py` | + slot_initial_state (moved from sim.py for import acyclicity) |
| `data/scenarios/two_failure.json` | primary demo: two DEAD imagers, a_max 0.1, allocation grids |
| `tests/test_allocation.py` | 4 mandated 3.3 names + seat-role re-election unit test |
| `tests/test_fault.py` | 2 mandated names + detection latency, state machine, baseline headline |
| `docs/MASTER_PROMPT.md` §3.3, §3.5, §4, §5, §3.8 | behavior/contract source |

### Scope notes / caveats for G5+

- The formation sweep's coverage estimate is ~φ0-invariant over a full-orbit
  average (differences ±0.002 = sampling noise): the winner is deterministic per
  scenario but effectively chosen at noise level among equal-coverage candidates.
  Scenario authors should treat phase_sweep_deg order as part of the tuning.
- THRUSTER_OUT handling (coast, report, no reassignment) is implemented but not
  exercised by any test (optional per MASTER_PROMPT 3.5).
- The reachability gate uses the bang-bang ESTIMATE 2·sqrt(d·a_max); actual PD
  transfers cost ~2.4× that — dv_budget_mps filters estimates, the log records
  actuals.
- Detection latency for tick-aligned failures is exactly (K−1)·dt because the
  firing tick's heartbeat already counts as missed.
- G5 consumes: state field (machine timeline), FAILURE_DETECTED / STATE /
  ASSIGNMENT events, per-sat dv_used/status, coverage + min_sep per tick.

### Re-tune (2026-09-28, after user review of the a_max flag): spacing 11 → 8 km, a_max stays 0.1

User review ruled the a_max=0.1 workaround not ratifiable as-is (~800 mN breaks the
~150 mN class; per-sat Δv 280 m/s) and asked for a spacing/FOV re-tune — the research
patch #2 levers, metric untouched — to widen the recovery gap instead of wording.
Two deterministic sweeps drove the decision (scratch drivers `.pytest_tmp/g4_sweep*.py`,
gitignored; configs + outputs below are the record):

Sweep 1 — can we restore the ratified a_max = 1e-2? **No, at any spacing.**
radial_amp 4–11 km × FOV 1.0/1.5 deg, a_max = 1e-2, dv_budget 100: every config ends
RECOVERED=0 with recovery WORSE than no-recovery (rec 0.0000–0.1402 vs norec
0.1022–0.2362; worst per-sat dv ~158 m/s of saturated burning). This extends the
a_max finding above: the Coriolis barrier 2n·v_y ≤ a_max caps feasible transfers at
v_y = a_max/(2n) ≈ 4.5 m/s ⇒ d ≈ v_y²/a_max ≈ 2 km, far below the ≥60° seat moves the
survivor formation needs at patch-#2 scales. The G2 PD cannot fly this mission at
1e-2; only an impulsive/MPC planner could (future work — judge may ask).

Sweep 2 — gap-widening at the documented a_max = 0.1 (A km / FOV deg → gain pts,
drop pts, max dv m/s, RECOV):

```
11.0/1.5 (committed baseline)  +3.33  19.97  280.25  1
 6.0/1.5   +5.09  12.03(<15)   138.89  1     8.0/1.5   +4.93  15.91  193.68  1
 9.0/1.5   +4.46  17.74         197.37  1    10.0/1.5   +3.93  19.21  RECOV=0
 6.0/1.2   +3.22   9.55         150.72  1     8.0/1.2   +2.51  12.45  177.33  1
10.0/1.2   +1.59  14.82         247.71  1    12.0–14.0  RECOV=0 (diverged)
```

Selected **A = 8.0 km, FOV = 1.5°** (FOV unchanged from nominal; only spacing moves):
best gain among configs that reach RECOVERED AND keep the patch-#2 drop ≥ 15
(A=6 gains +5.09 but its drop is 12.03; A ≥ 10 diverges the state machine — the same
Coriolis mechanism as sweep 1, just at larger transfer velocities than 0.1 can
sometimes absorb).

Final numbers (evidence commands in GATES.md G4 row): rec 0.2698 vs norec 0.2205
(**+4.93 pts**, ~31% of the destroyed coverage restored), drop **15.91 pts** (pre 0.3796),
worst min_sep **3095.1 m**, detection latency 4 s, RECOVERED t=3114 s, per-sat Δv
0–**193.68 m/s**, log 8517 lines, two runs byte-identical sha256
`450d537107c36205880b4e7a63e9d804e64e6352553b97b019cf3961ed044801`.

Code fixes riding along (verified not to move the G3 golden hash — nominal never
replans, so per-tick role evaluation is identical there):

- `cubesat/sim.py`: the logged coverage now evaluates the imager set from the CURRENT
  `roles[]` each tick. The old code froze `imager_ids` from `scenario.roles` at startup
  while re-election reassigns `roles[]` — latent for any scenario where a critical role
  dies (leader-death re-election logs the wrong imagers' positions); neutral for
  two_failure (leader/downlink survive).
- `cubesat/sim.py`: ASSIGNMENT payloads now log `transfer_lower_bound_s`
  = 2·sqrt(max_transfer/a_max) (research patch #1 "log the lower bound per reconfig"):
  984.0 s and 945.3 s in the final run.
- The "each state lasts exactly one tick" claim (sim docstring + ARCHITECTURE) is
  corrected: only the DECISION states (FAILURE_DETECTED, REPLANNING) are one tick;
  RECONFIGURING spans the transfers (1208→3114 s here).
- `tests/test_fault.py`: state-machine docstring now matches the relaxed (correct)
  expectation; detection-latency test writes its scenario through pytest `tmp_path`
  (+ explicit mkdir for this setup's relative-basetemp quirk) instead of `.pytest_tmp`.

## Cluster import: hypothetical swarm on a real chief orbit (2026-09-28, cluster-import feature)

Post-G4 feature (not a gate): a CLI + library that turns one CelesTrak OMM record into
a schema-valid swarm scenario flying formation on that object's real orbit.

### Motivation

No real Indian cluster is tight enough for HCW: the Pixxel Fireflies are phased ~120 deg
apart at ~589 km, and SpaDeX is only 2 satellites. The honest product is a **hypothetical
swarm on a real chief's orbit** ("hypothetical-swarm-on-FIREFLY-1", not "recovering X"):
the chief orbit is measured, the relative motion is the sim's own.

### Design

`cubesat/cluster_import.py` (new, 199 lines; stdlib only — no sgp4, no new dependency;
no wall clock, no RNG, no order-dependent iteration, AGENTS.md 2):

- OMM parse (`cubesat/cluster_import.py:62-76`): `n = MEAN_MOTION · 2π/86400` (revs per
  solar day → rad/s, sgp4 convention), `a = (MU/n²)^(1/3)`, `altitude_km = (a −
  R_EARTH)/1000`. `MU`, `R_EARTH`, `mean_motion` come from `cubesat/hcw.py`.
- Kozai mean-motion caveat: the OMM mean motion is a Kozai mean element; deriving
  altitude as (MU/n²)^⅓ ignores the J2 secular term, which biases the derived altitude
  by ~3 km for sun-synchronous chiefs (i ≈ 97.7° here). A labeling-level bias only: the
  sim consumes just the mean motion (derived from `chief.altitude_km`), and the
  formation-scale effect is roughly two orders below the measured ~3 km CW-vs-Kepler
  linearization error (2984.5 m, G3 section). The ~3 km bias figure is a first-order
  analytical estimate (unmeasured).
- e-gate `e > 1e-3` rejects the record (`cubesat/cluster_import.py:83-88`): a labeling
  convention — the chief's eccentricity never enters the sim (the scenario `chief`
  field carries only `altitude_km`); the gate exists so the label "hypothetical swarm
  on a near-circular real orbit" stays true. Measured (exit 2, NO scenario file
  written):

  ```
  uv run python -m cubesat.cluster_import --omm data/celestrak/firefly_omm.json --index 0 --n-sats 6 --n-failures 2 --out data/scenarios/_rejected.json
  record [0] rejected: eccentricity gate failed: e=0.00169518 > 0.001 for FIREFLY ALPHA R/B (NORAD 60210); a hypothetical swarm needs a near-circular chief (see module docstring)
  ```

  An altitude gate 160–2000 km mirrors `ChiefOrbit` in the scenario schema
  (`cubesat/cluster_import.py:36,89-94`).
- The colleague's new `_slots_match_roles` model validator
  (`cubesat/scenario.py:126-135`): `formation.n_slots` must equal `len(roles)` — the
  generated scenarios satisfy it by construction; tested, not re-implemented
  (`tests/test_scenario_schema.py::test_rejects_slot_role_mismatch`).
- Survivor guard (`cubesat/cluster_import.py:107-113`): `n_sats >= 4` and
  `1 <= n_failures <= n_sats - 3` — leader + at least one imager + the downlink must
  survive the `n_failures` DEAD fires.
- Design-review decisions: **leader-death n4** (`data/scenarios/single_failure_n4.json`:
  sat 0, the leader, DEAD at t=1200 — critical-role re-election on a minimal 4-sat
  formation) and **THRUSTER_OUT on the downlink** (`data/scenarios/cascading_n8.json`:
  sat 7 at t=2400 — the mode keeps reporting heartbeats, so detection stays silent for
  it by design; it coasts as an obstacle). The gains / sensor / allocation reference
  blocks are copied verbatim from `data/scenarios/two_failure.json`
  (`cubesat/cluster_import.py:38-54`), so the generated swarm behaves like the tuned
  G4 demo.
- The generated file is self-consistent with the sim: altitude is rounded to 3 decimals
  and n is recomputed from the ROUNDED altitude via `hcw.mean_motion` — the sim derives
  n from `chief.altitude_km`, not from the OMM mean motion
  (`cubesat/cluster_import.py:114-115`).

### Tuning (the only one: cascading_n8 radial_amp_km 8.0 → 8.25)

With 8.0, `tests/test_scenario_zoo.py::test_cascading_n8_two_replan_cycles_one_recovery`
failed — worst min_sep 1909.3 m < 2000.0 m at t=13718 s. A per-tick diagnostic showed
the violating pair is sat 0 (leader, NOMINAL) vs sat 7 (THRUSTER_OUT, coasting from its
mid-transfer state at t=2400 s), drifting along-track until it grazes the formation
~2.5 orbits in. Deterministic sweep over {8.25, 8.5, 8.75, 9.25, 9.5, 9.75}
(2026-09-28; configs + outputs are the record): 8.5 fails (1889.2 m); 8.75/9.25/9.75
never reach RECOVERED — at amp 10.0 a diagnostic showed sat 0's second-transfer PD
chase saturating (dv growing at exactly a_max=0.1 m/s², r diverging to y=−26,543 km):
continuous saturated along-track thrust diverges under CW dynamics (the G4 a_max
finding); 9.5 also passes (worst 2253.0 m, rec=1) but 8.25 is closest to the
two_failure reference 8.0 with the better margin. Selected **8.25**: worst min_sep
**2744.7 m at t=3796 s** (threshold 2000 m), detections=2, assignments=2,
to_RECOVERED=1 (re-verified this session: `uv run pytest tests/test_scenario_zoo.py -s -q`
prints the same line). Metric and test assertions untouched.

### Provenance

`data/celestrak/firefly_omm.json` — fetched 2026-09-28 from
`https://celestrak.org/NORAD/elements/gp.php?NAME=FIREFLY&FORMAT=JSON`. 5 records
(altitude/e from the CLI picker output above and the snapshot itself):

| idx | OBJECT_NAME | NORAD_CAT_ID | altitude_km | eccentricity |
|---|---|---|---|---|
| 0 | FIREFLY ALPHA R/B | 60210 | 342.380 | 0.00169518 |
| 1 | FIREFLY-1 | 62701 | 589.309 | 0.00037208 |
| 2 | FIREFLY-2 | 62704 | 589.450 | 0.00081895 |
| 3 | FIREFLY-3 | 62710 | 589.358 | 0.00033692 |
| 4 | FIREFLY ALPHA R/B | 68128 | 346.608 | 0.00090641 |

### Generated scenario (the flagship)

```
uv run python -m cubesat.cluster_import --omm data/celestrak/firefly_omm.json --index 1 --n-sats 6 --n-failures 2 --out data/scenarios/firefly_swarm.json
chief FIREFLY-1 (NORAD 62701): altitude 589.309 km, e 3.7208e-04, n 0.001086 rad/s
wrote data\scenarios\firefly_swarm.json
```

Chief: FIREFLY-1, NORAD 62701, altitude **589.309 km**, e **3.7208e-04**, n
**0.001086 rad/s**; 6 sats (1 leader / 4 imagers / 1 downlink), A = 8.0 km, a_max 0.1,
2 DEAD imagers (t=1200/1500, the two_failure pattern), duration = 3 orbits =
17363.71514024976 s. Regeneration is byte-identical to the committed file (verified
2026-09-28: same command to a scratch path, `cmp` exit 0).

### Demo logs (data/logs is gitignored — commit the hash, not the log; invariant 1)

All six logs produced with
`uv run python -m cubesat.run --scenario data/scenarios/<name>.json --seed 42 --out data/logs/<name>.jsonl`
(run twice per scenario, second copy `_run2`; line counts + sha256 re-verified
2026-09-28 with `wc -l` + `sha256sum`, each pair byte-identical, `cmp` exit 0):

| scenario | lines | sha256 (both runs identical) | coverage_mean_last_orbit |
|---|---|---|---|
| firefly_swarm.jsonl | 8685 | `692f066f6f3edb07c5f72ee9b294959f6346b2641650c917f83de79629782742` | 0.362410 |
| single_failure_n4.jsonl | 8517 | `528f014088d1eb42057c5514df7f80bb45cba17f2d7bafafe3ad3ea65b6bc708` | 0.140240 |
| cascading_n8.jsonl | 8517 | `5dba765e2e671626a49956c94837a53e72a1ff24806bc4f8543747fc56249a0d` | 0.408800 |

(coverage from each log's SUMMARY line, last-line read; the run command prints the
same value.)

### Reproduce

```
uv sync --locked
uv run python -m cubesat.cluster_import --omm data/celestrak/firefly_omm.json --index 1 --n-sats 6 --n-failures 2 --out data/scenarios/firefly_swarm.json
uv run python -m cubesat.run --scenario data/scenarios/firefly_swarm.json --seed 42 --out data/logs/firefly_swarm.jsonl
uv run pytest -q    # 42 passed: incl. test_cluster_import (8), test_scenario_zoo (3), test_scenario_schema (6)
```

## Endgame re-plan — measurement first, AI target pinned (2026-09-29, docs only)

No code changed in this commit. Suite verified green at HEAD `67189ab` this session:
full `uv run pytest -q` passed; the golden pin held (`uv run pytest tests/test_cli.py::test_run_is_byte_deterministic -q`
→ 1 passed); `uv run pytest --collect-only -q` → 43 tests collected.

A researched workflow (codebase recon + ML recipe + risk mapping + independent
adversarial review; every file:line verified against the tree) produced two plan docs
the same day:

- `docs/AI_LAYER_PLAN.md` — the morning's predictor-first plan. **Superseded in
  priority order** (banner on its status line); kept as the predictor-design detail
  reference.
- `docs/ENDGAME_PLAN.md` — **ACTIVE**, measurement-first P0–P4 after the user's
  prior-art review. That doc is the plan of record; this section records the decisions.

**Decisions (full detail + 14-item risk register in ENDGAME_PLAN):**

1. Judge-facing deliverable is MEASUREMENT: P0 = all C(6,2)=15 two-failure pairs × 5
   policies (do-nothing, even-split [the RL-retasking literature's naive rule], greedy
   nearest-seat, Hungarian, Hungarian+keep-out), reporting mean AND worst-case coverage
   retained / total Δv / min survivor-to-dead separation; P1 = fuel-vs-coverage Pareto
   (w2 × dv_budget grid); P2 = dead-satellite drift keep-out report; P3 = CW-validity
   plot (extends tests/test_hcw.py::test_cw_vs_kepler_error_report — reuse, not rebuild).
   P0–P3 need ZERO sim-core diffs (benchmark-side override of the `cubesat.sim.replan`
   seam with try/finally restore + `test_benchmark_replanning_rebinding_restored`).
2. AI target PINNED: per-satellite failure-risk prediction feeding ROLE PLACEMENT —
   critical roles (leader, downlink) go to the lowest-risk eligible survivors via a
   deterministic post-Hungarian swap (margin list {0.0, 0.1, 0.2}; equal risk breaks to
   the lowest sat id). The model NEVER predicts assignments (Hungarian is already
   optimal; 15 cases make an ML-assignment claim indefensible). Early-warning
   suspect alerts are secondary; the reactive heartbeat+Hungarian path stays
   authoritative; sudden death is unpredictable by construction (recall ≈ 0, stated
   openly). The LLM copilot is cut unconditionally.
3. Claims policy: never claim novelty — cite the Princeton 2025 thesis (CW + convex +
   fault-aware reassignment), failure-triggered Hungarian retargeting, the RL
   retasking paper (whose even-split rule we reimplement as a baseline), passive-safety
   design (GRACE/TanDEM-X/PRISMA), and Starling accurately (ROMEO flew maneuver
   planning; failure recovery was NOT flight-demonstrated). Stats phrasing: "failures
   are common"; the repo's 2-of-6 is a scenario choice, not a statistic.
4. Teammate coordination (landed BEFORE any predictor code): BACKEND_SPEC v1.1
   Appendix B — wire deltas all [optional]/additive, no new WS message types, G5 must
   NOT parse the predictor scenario block, old logs replay unchanged; FRONTEND_SPEC
   v2.1 Appendix D — optional `risk` field + SUSPECT text label under §13 law. Also
   corrected the stale "no Dockerfile" claims in BACKEND_SPEC §3/§8.2 (a Dockerfile
   exists in the tree; G5 amends it and verifies its COPY list).

**Top open items (ENDGAME_PLAN §12; decide at the 12:00 gate on 2026-09-30):**
lightgbm approval (else the dependency-free EWMA/CUSUM baseline ships); P4 in-loop
hook approval (the plan's only contemplated core diff); the second-delta scope ack
(measured on predictor-family scenarios — on the existing scenarios it is zero/negative
by construction); before the demo: Dockerfile content fix + `docker run` healthcheck
(risk #8) and the canonical-log whitelist commit so replay-from-fresh-clone works
(risk #10, `git ls-files data/logs` lists only `.gitkeep` today).

## Endgame P4 — predictor bundle integration (2026-10-03, Gate 0)

User-supplied bundle (files/INTEGRATION_PROMPT.md, phase-gated: oracle sweep is the
kill switch BEFORE any in-loop hook). Sources live at **files/**; the ORIGINAL bundle
seal (src sha256 48fb27d7…, also recorded in GATES.md) was replaced by a
user-approved I/O-edge-only hardening applied 2026-10-03/04 — path-confinement guard
(--out must be a single directory name resolved under the repo root; confined chdir;
all sinks absolute or literal relative names; zero generator/feature/training/eval
logic touched) — and the pipeline was RE-SEALED through its own manifest mechanism
(current seal src sha256 deefeae1…, self-enforced by out2/test_manifest.json). The
model artifact seal is untouched by the hardening. Artifacts: **models/**
(predictor.txt + predictor_manifest.json, model sha256-pinned) and **out2/**
(reference results.json + sealed manifest, committed so the repro rerun diffs
against git).

- Seals: tests/test_predictor_seal.py — pipeline sha256 == out2/test_manifest.json
  src_sha256 (deefeae1… hardened; original bundle seal 48fb27d7… on record in
  GATES.md); model sha256 == models/predictor_manifest.json model_sha256
  (37900918…). CI verifies hashes, never retrains.
- Hardening inertness proof: the repro rerun must still reproduce the bundle's
  reference out2/results.json byte-identically — any drift: REPORT, do not fix.
  MEASURED 2026-10-04 (exit 0): every semantic number identical (tau_lgb exact to
  17 digits, all counts/recalls/p-values identical, "LGB ships" verdict
  reproduced, median lead gain 260.0 s); two benign divergences reported: one
  1-ulp scipy CI digit and model BYTES (lightgbm 4.7.0 build drift vs the
  bundle's unrecorded build) — the shipped artifact stays the record, reference
  outputs restored, fresh artifacts discarded.
- Repro of record: `uv run python files/predictor_pipeline.py run --out out2` —
  out2/ must stay byte-identical afterward (results.json unchanged, fresh
  out2/predictor.txt sha == manifest). If it differs: REPORT, do not fix
  (prompt rule — likely a lightgbm version drift; 4.7.0 installed 2026-10-03).
- Gate-2 pre-registration (GATES.md decisions log, written before any sweep
  number): GO iff any scenario ≥ 0.5 pp critical-seat health gain at L=300 s;
  else CUT + reactive-only + curve, README says the predictor was not shipped.
- Offline results of record (bundle out2/results.json, sealed pipeline): LGB
  label variant L3600 selected on CAL; test FA ≤ 1.2 × 0.5 budget; ~260 s
  median lead gain vs best baseline on trained families; comms-holdout 0/15
  (no generalization to unseen families); sudden death ≈ 0 recall by design.

## 2026-10-04 — console redesign (frontend, g5-local working tree, UNCOMMITTED)

Frontend redesign landed via parallel workflow (7 builders + integrator +
fresh design reviewer; dynamic-workflow run dwfrun-75399998 completed with
all gates green). Same locked stack, same §13 tokens; what changed is the
explanation layer, density and the 3D staging. By surface:

- 3D scene (`components/three/`): procedural Earth globe + atmosphere rim +
  graticule ("Earth — stylized, not to scale"), seeded starfield, constant
  screen-size satellite markers (zoom no longer turns them into blobs),
  label declutter with priority, gentle formation auto-fit (disengages on
  user drag), ghost slots / trails / failure lines toned down, LVLH axes
  hint. New: sceneEarth.ts, sceneLabels.ts, sceneCamera.ts, sceneLines.ts.
- Onboarding (`components/onboarding/`): MissionBrief.tsx first-load overlay
  — what the swarm is (hypothetical, FIREFLY-1 orbit kept verbatim), live vs
  replay, the detect→replan→reconfigure→recover story, glossary; "?" reopens.
  Copy lives in helpContent.ts.
- Narration (`components/narration/` + `stores/recoveryStore.ts`):
  NarrationStrip renders the plain-language sentence of NOW (mover names
  from live role_reassignment events, unchanged rows filtered, per-failure
  coverage drop/restore). The §13.5 spine carries real event ticks with mono
  stamps and is seekable in replay.
- Satellite detail (`satellites/` + `stores/roleHistoryStore.ts`): role +
  role semantics in plain words, LVLH r/v with axis labels, target slot,
  Δv, suspect (rule-based slot-drift detector `utils/suspect.ts`, Appendix D
  display), and the role/task history timeline ("took over slot_0 after
  SAT-2 failed" → "failed as imager holding slot_0 (DEAD)" → "formation
  recovered").
- Telemetry (`dashboard/`): readout rows with explainer tooltips + tabbed
  charts (Coverage / Deviation / Separation / Δv / Health), event markers,
  measured reference line on min-sep, health-score derivation in tooltip.
  The spec's 3-curve coverage comparison is NOT built (the wire carries no
  reference runs); the chart says so instead of inventing curves.
- Controls: full replay transport (play/pause/restart/speed/scrub with
  fetched duration, file picker, Replay badge) visible in console AND
  presentation layouts; failure injection with mode descriptions;
  CustomScenarioModal → POST /scenarios/upload (cubesat/api.py additive
  route: sanitized name, 409 on collision, server-side validation;
  tests/test_scenario_upload.py).
- Verified live (first hand, 1920×1080): mission brief → live firefly_swarm
  run (Earth, markers, labels, narration, measured telemetry: detection
  latency 4.00 s, Δv sum 441.14 m/s, health 47/100 caution band) → satellite
  detail with role history → replay two_failure.jsonl (transport, seek,
  duration, spine) → formation view close-up (markers constant-size) →
  presentation mode (transport visible, narration present) → custom-scenario
  modal (client-side JSON validation inline).
- Gates: `cd frontend && npm run build` ok (tsc + vite, 4.98 s);
  `uv run pytest -q` full suite exit 0 (workflow gate, includes the
  concurrent P4 session's tree); hex gate + avoid-ai-design scanner clean.
- Known cosmetics, not fixed: right-panel tab row overflows at 1920 px
  (horizontal scrollbar); readout tooltips may clip inside scrolling panels
  (inferred from CSS, not observed).
- Playwright note (automation only, not a user bug): buttons inside the
  streaming panels defeat actionability waits under the 30 Hz re-render
  cadence; scripted clicks must dispatch inside the page.
- The tree also carries the concurrent P4 predictor session's work (see the
  section above). The Suspect display renders wire `risk` when present
  (Appendix D) and falls back to the rule-based detector otherwise. Commit
  the two workstreams separately.
