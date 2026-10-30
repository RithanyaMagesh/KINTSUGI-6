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

## 2026-10-26 — Round 4 frontend redesign (control seat, replay inspector, REST consolidation, claims audit)

Addressed every open item in `docs/FRONTEND_REDESIGN_PROMPT.md` §3.2–§8 without modifying the simulation core or backend:

- **Unified `#/live` Control Seat (`LivePage.tsx`, `ScenarioBuilder.tsx`, `SwarmSection.tsx`, `LivePage.module.css`)**:
  - Replaced the 3-tab sidebar split (`Builder | Satellites | Recovery`) with a single-flow control column so the operator never hunts across tabs mid-run (§3.2 #1, #2, #3).
  - Added committed scenario presets (`two_failure.json`, `firefly_swarm.json`, `cascading_n8.json`, `leader_failure_6sat.json`, `single_failure_n4.json`, `nominal.json`) that populate the builder form with exact committed values and run directly when unmodified or upload a custom variant when edited.
  - Added collapsible setup (`<details className={styles.setupAccordion}>`) that folds automatically on run start while keeping the Mission readout, Run lifecycle controls, Live Failure Injection (`FailureInjectionPanel`), AI Early Warning (`RiskPanel`), Recovery Story (`RecoveryLog`), and Fleet List (`SatelliteList`) visible in one scroll column.
  - Added larger-swarm seat options (`2–8` standard + `12, 16, 24, 32, 50` roadmap swarms, §4) with a collapsible seat-role editor when `nSats > 8`.
- **Per-Option 422 Fallback & Policy Readout Sync (`ScenarioBuilder.tsx`, `simStore.ts`, `RecoveryLog.tsx`)**:
  - Fixed the combined 422 fallback (§3.2 #4): when `/simulation/start` returns 422, `startWithFallback` probes `policy` and `predictor` individually so only the unsupported option is dropped and reported in a dedicated inline status note.
  - Fixed the `"unmeasured"` policy readout on Hungarian runs (§3.2 #5): `ScenarioBuilder` reads the resolved `policy` from the `/simulation/start` response via `simStore.setSessionMeta`, `simStore` preserves `state.policy` across the `INIT` empty frame when `wire.py` omits the default `"hungarian"` field, and `RecoveryLog` reads `simStore.policy` instead of hardcoding `RECOVERY_MODE`.
- **REST Client Consolidation (`api/backend.ts`, `api/scenarios.ts`, `components/live/runApi.ts`)**:
  - Consolidated `fetch`, `formatErrorDetail`, `uploadScenario`, `simulationSpeed`, and unified `startSimulation` into `api/backend.ts` with clean re-exports in `scenarios.ts` and `runApi.ts` (§3.2 #6, #7).
- **Read-Only Telemetry & Satellite Inspector on `#/replay` (`ReplayPage.tsx`, `ReplayPage.module.css`)**:
  - Mounted `RightPanel` (readout rows, 5 underline-tabbed charts, Role reassignment table, and `SelectedSatellitePanel`) and `SatelliteList` on `#/replay` so clicking any satellite in Replay displays its role semantics, LVLH state, and role/task history while keeping `#/replay` strictly playback-only with one transport and zero live controls.
- **Role History Preservation (`stores/roleHistoryStore.ts`, `SelectedSatellitePanel.tsx`)**:
  - Skipped no-op survivor rows at ingest in `roleHistoryStore.ts` (recording only rows where `role` or `targetSlot` changed) and raised `MAX_HISTORY_PER_SAT` from 50 to 250 with a truncation caption when reached (§3.2 #8).
- **RightPanel Tab Fit, Tooltip Containment & Coverage Benchmark Note (`RightPanel.module.css`, `ReadoutRow.module.css`, `GroundCoverageChart.tsx`)**:
  - Sized `.tabs` / `.tab` in `RightPanel.module.css` so all 5 chart tabs fit inside the 336px column at 1920×1080 without horizontal overflow (§3.2 #9).
  - Constrained `.tip` in `ReadoutRow.module.css` (`left: 0; right: 0; max-width: 100%`) and flipped the last row's tooltip above so tooltips never clip inside scroll containers (§3.2 #9).
  - Updated `GroundCoverageChart.tsx` caption with the measured P0 benchmark comparison (`+4.93` coverage pts on `two_failure` seed 42; `+4.93` pts worst-case floor and `-2.13` pts mean across all $C(6,2)=15$ two-failure pairs) and explained why the wire carries a single active run (§3.2 #10).
- **Claims Audit & Housekeeping (`LandingPage.tsx`, `RiskPanel.tsx`, `TutorialPage.tsx`, `uiStore.ts`)**:
  - Fixed `LandingPage.tsx` Pillar 3 (`"AI early warning (display-only)"`) to state honestly that the sealed LightGBM model is a display-only precursor score (`sats[].risk`) cut from the control loop by the pre-registered oracle sweep (`+0.0235` pp vs `0.5` pp threshold), and that reactive 4 s heartbeat detection drives recovery (`audit_out/AUDIT.md`, §1.6, §6).
  - Removed dormant `missionBriefOpen` and `sessionStorage` startup code from `uiStore.ts` (§3.2 #11).

## Failure-semantics round (2026-10-26)

Build notes for the post-deadline failure-semantics round; spec deltas in
BACKEND_SPEC.md Addendum v1.2, decisions in GATES.md (2026-10-26 entries).
All six items below have landed; numbers are quoted from the committed
machine-written reports, each with its producing command.

### EPS_DEGRADE

Landed: `FailureMode.EPS_DEGRADE` + `Failure.degrade_s` (cubesat/scenario.py),
fade schedule + `DEGRADED` status + `DEGRADE_START` event (cubesat/sim.py),
wire row `DEGRADED → "degraded"` (cubesat/wire.py), FRONTEND_SPEC §15.1 note.
`degrade_s = 0` is sudden: byte-identical to the same failure declared DEAD
except the `FAILURE_DETECTED` mode label (pinned by
`test_eps_degrade_zero_window_equals_dead`). Tests:
tests/test_failure_modes.py.

Commands + measured: the pre-change baseline probe (run_scenario on
data/scenarios/two_failure.json, per-line sha256 of
`json.dumps(line, sort_keys=True) + "\n"`) = `450d5371…` — matched BEFORE any
diff (8517 lines), and the same pin is green after the core diffs
(`uv run python -m pytest tests/test_failure_modes.py tests/test_wire.py
tests/test_scenario_zoo.py tests/test_policy_selection.py tests/test_fault.py
tests/test_cli.py -q` → 36 passed; fast loop `uv run python -m pytest -q
-m 'not slow'` → 129 passed, 3 deselected; `uv run ruff check .` clean;
tests-first red phase: 9 new/updated tests failed as expected — pydantic
ValidationError on the unknown mode, cascading assert 2 == 3, wire mapping
asserts — while the canonical sha pin already passed). eps_leader_6sat smoke
(sat 0, degrade_s = 1800, t_f = 2400): DEGRADE_START at 600.0 s, sat 0
DEGRADED on every tick in [600, 2400) with mission NOMINAL, DEAD at 2400,
heartbeat-detected 2404, leader re-elected, RECOVERED at 4236.0 s, worst
min_sep 3267.0 m (threshold 2000 m). Caveats: the zero-window pin asserts the
honest `EPS_DEGRADE` mode label plus every other byte equal — a
label-included byte-match would require falsifying the log's mode field, not
done; DEGRADED sats stay in the replan obstacle list (the existing
non-NOMINAL rule) — unreachable in committed scenarios, where no replan fires
while a sat is DEGRADED; the sweep's ballistic preview of a seat-holding
DEGRADED sat would be approximate for the same reason.

### Self-report

Landed: a THRUSTER_OUT sat announces its own failure (`self_report: true` on
`FAILURE_DETECTED`, fired on the firing tick — no heartbeat misses) and drives
the standard REPLANNING → RECONFIGURING → RECOVERED arc with role re-election
(cubesat/sim.py). Consequence, ON PURPOSE (GATES.md 2026-10-26):
data/scenarios/cascading_n8.json (sat-7 THRUSTER_OUT at t = 2400) gains a third
detection + replan; `test_cascading_n8_two_replan_cycles_one_recovery` now
expects 3 detections / 3 assignments. Tests: `test_self_report_*`.

Measured: detection latency 0 by construction — cascading_n8 t_fail ==
t_detect == 2400.0. cascading_n8 post-change: 3 FAILURE_DETECTED (1204/1504
heartbeat DEAD + 2400 self-report), 3 ASSIGNMENTS (1208/1508/2404 — the third
excludes sat 7 and re-elects the downlink role onto a healthy sat), RECOVERED
once at 4280.0 s (pre-change 3672.0 s, so the extra cycle delays full recovery
by ~608 s), worst min_sep 3410.6 m at t = 1586 s. Caveats: "loses its role" is
asserted at the assignment level (the thruster-out sat appears in no
ASSIGNMENT; the stale `role` label on its log lines is pre-existing behavior
shared with DEAD sats — clearing it would move the canonical sha pin); the
`/failure/inject` response echo stays exactly `{sat_id, mode}` (pinned by
tests/test_api.py:241) — `degrade_s` is accepted and validated (ge=0 → 422 on
negative) but not echoed; test_policy_selection.py needed no changes (its
THRUSTER inject test only asserts `even_split` among ASSIGNMENT methods).

### Evasion

Landed: defaulted `Safety {evasion_enabled: true, evade_radius_m: 1000.0,
evade_ticks: 25}` (cubesat/scenario.py) + bounded away-from-intruder burn and
`EVASIVE_MANEUVER` event (cubesat/sim.py) — discrete maneuver, NOT potential
fields; `min_sep` still logged every step. Default-inertness is geometric
(1000 m < every measured clearance), so canonical runs never emit the event.
Tests: tests/test_collision_avoidance.py.

Measured (data/scenarios/proximity_stress.json, seed 7,
`uv run python -m cubesat.run --scenario data/scenarios/proximity_stress.json
--seed 7 --out $TEMP/proximity_smoke.jsonl` → 35 EVASIVE_MANEUVER lines,
LF-only JSONL): the first episode starts at t = 0 at range 848.5281374 m
(log payload `range_m: 848.5281374238571`, sat 0 vs sat 1; analytic 2·A·√2 for
A = 300 m, two slots at phases 0/π) — inside the 1000 m radius; worst min_sep
848.5 m at t = 0; after the t = 600 DEAD failure the surviving sat 0 evades
the coasting corpse 29 more times (detection t = 604, 1-survivor ASSIGNMENT
t = 608, the full recovery arc intact). Episode Δv cost = a_max · evade_ticks
· dt = 0.01 · 25 · 2.0 = 0.500000 m/s per evading sat per episode
(test-pinned, approx rel 1e-6, measured exact). Tests red-first:
`uv run python -m pytest tests/test_collision_avoidance.py -q` → ImportError
(cannot import name `Safety`), then 7 passed; byte-inertness is geometric —
zero EVASIVE_MANEUVER events on the nominal and two_failure runs and all
three golden SHA pins green
(`uv run python -m pytest tests/test_collision_avoidance.py
tests/test_failure_modes.py tests/test_cli.py -q` → 16 passed). Caveats:
`PDController.apply_accel(state, u, dt, n)` is state-first —
`propagate_controlled` needs the state, so the ask's `(u, dt, n)` signature
summary was not functional as written; an rng == 0 guard was added (zero range
has no away-direction and would produce NaN — inert in practice); the
committed stress scenario's first firing is a symmetric NOMINAL–NOMINAL close
pair on a tight 2-slot passive ellipse, not a dead-sat secular-drift crossing
(that variant needs a mid-transfer death and was not tuned — live-vs-dead
evasion is still exercised after t = 600); the wire renders the range in whole
metres ("range 849 m"); the test FIFO pop-time assertion is pop ≥ detection +
dt (one event pops per tick, per the ask's own "FIFO, one event pops per tick
- fine").

### Oracle sweep v2

Pre-registration (GATES.md 2026-10-26, recorded before any number): proceed
only if the max critical-seat health gain at L = 300 s on the new failure
families is ≥ 0.5 pp. Measured (`uv run python files/oracle_sweep_v2.py`, report
data/eval/oracle_sweep_v2.json; per-point scenarios + logs under
data/eval/oracle_sweep_v2/, gitignored, per-row commands in the report):
eps_leader_6sat +1.7968 pp and eps_downlink_6sat +1.7968 pp at L = 300 s
(max +10.6048 pp at L = 1800 s); control eps_imager_6sat +0.0000 pp
(structurally flat, as predicted); thruster_leader_6sat +0.0235 pp — the
oracle's residual gain over the self-report path is negligible (detection
latency is already 0 there). Verdict: CLEAR — above the 0.5 pp threshold on
the leader/downlink EPS families; per the pre-registration, nothing integrates
into the control loop without a further user decision.

Report integrity + numbers: `uv run python -m pytest tests/test_oracle_sweep_v2.py -v`
→ 3 passed — test_v2_report_schema_and_verdict RAN (did not skip) and verified
every on-disk log sha256 against the report; the sweep re-run reproduces all
20 log sha256s byte-identically, report sha256
`58bec3099ced52aba68d747f063da090440f5becaba4633e70c80d87dba49fb9` before and
after (`cmp` exit 0). Δv trend from the report rows: oracle-on costs more than
the reactive baseline at every L > 0 in every family and is non-monotone in L
— eps_leader totals 401.84 / 537.16 / 397.95 / 3210.31 / 710.64 m/s at
L = 0/30/60/300/1800 s (L = 300 is ~8× baseline: the early replan re-phases
the formation and a second replan still fires at the actual death;
eps_downlink L300 is 409.52 m/s ≈ baseline — moving the downlink seat is
geometrically cheaper than the leader seat); every Δv inherits the standing
a_max = 0.1 over-thrust caveat (GATES.md open risks). Cap rule: t_settle =
0.0 s (tick 0 of data/logs/nominal.jsonl is already inside the ±10 % band), so
no grid point was capped (`capped: false` on all 20 rows). The reactive
baseline (L = 0) has `oracle_enabled: false` — semantically identical, since
the sim hook requires lead_s > 0, and that point IS the required reactive
comparison. Caveats: all deliverables (4 scenarios, files/oracle_sweep_v2.py,
tests, report + 20 point logs) pre-existed on disk from the building session
(all untracked); that session verified each artifact against the spec, ran the
named tests, re-ran the sweep fresh, and proved byte-identical regeneration —
the tests-first red step was therefore not observable (with the report absent,
test_v2_report_schema_and_verdict skips by design). eps_leader and
eps_downlink report identical critical-seat fractions to 16 digits — genuine,
not copy-paste: the seat-outage windows are arithmetically identical (fade
600 s → death 2400 s + 2-tick detection on the same tick grid); their Δv
totals and log shas all differ. The pre-registration entry is dated 2026-10-26
(GATES.md decisions) and predates the sweep, as a pre-registration must.

### Monte Carlo

Robustness ensemble, zero core diff — the sim consumes no RNG, so the ensemble
jitters scenario parameters deterministically outside the core (failure times
±10 %, formation phase offset ±30°, radial amplitude ×[0.9, 1.1]; one PCG64
stream, fixed draw order). Measured:
`uv run python -m cubesat.benchmark --base data/scenarios/two_failure.json
--mode monte-carlo --report data/eval/monte_carlo_results.json` (base
two_failure, 20 runs × {do_nothing, hungarian}, seed 42): hungarian mean
last-orbit coverage 0.26915 vs do_nothing 0.22028 → +4.886 pts mean paired gain
(min paired +4.545 pts); ensemble-wide survivor–dead min separation 1787.7 m
(hungarian) / 10199.0 m (do_nothing). Per-run logs under data/eval/monte_carlo/
(gitignored); per-log sha256 + full jitter spec pinned in
data/eval/monte_carlo_manifest.json so the ensemble regenerates exactly.

Full-ensemble numbers (report): worst-vs-worst +5.201 pts
(`worst_case_coverage_gain_pts` 5.201337546489931); every one of the 20
matched pairs positive, per-run gains in [+4.545, +5.201] pts — the committed
P0 +4.93 headline sits inside the measured band; recovery is also less
jitter-sensitive (hungarian std 0.0025 < do_nothing 0.0045). Cost side:
hungarian total Δv mean 801.2 / max 2255.3 m/s; ensemble min survivor–dead
separation 1787.7 m (do_nothing: Δv ~2.6e-10 m/s, min sep 10199.0 m) —
clearance traded for coverage, consistent with the P0 pair sweep (worst
survivor-dead 1322.6 m). Byte-reproducibility: a second invocation of the
command of record, then `cmp` on report + manifest and `sha256sum -c` over
all 40 JSONL logs → ALL BYTE-IDENTICAL. Tests red-first
(`uv run python -m pytest tests/test_benchmark.py -q -k mc` → 3 FAILED,
ModuleNotFoundError: cubesat.monte_carlo), then 10 passed; final fast loop
`uv run python -m pytest -q -m 'not slow'` → 142 passed, 3 deselected;
`uv run ruff check .` clean. Caveats: benchmark.py grew 415 → 473 lines
(already above the ~300 style line before this round) — the mode body lives
in the new 230-line cubesat/monte_carlo.py and benchmark.py gained only the
dispatch + `--runs` (default 20) / `--seed` (default 42), the established
pareto/cw-curve pattern; a mid-ask bug (paired_gain_pts first emitted as a raw
fraction) was fixed and the command of record re-run to regenerate the
artifacts, then the whole ensemble re-run and byte-compared; the JSON
report/manifest are CRLF on this Windows host (same as the already-committed
data/eval/benchmark_results.json) while the JSONL logs force LF
(newline="\n") per the invariant; the 40 per-run logs under
data/eval/monte_carlo/ may not be committable (data/eval gitignores JSONL) —
report + manifest alone regenerate them byte-exactly via the recorded
command.

### Docker multi-stage

Landed in the Dockerfile: stage 1 `node:22-slim` (`npm ci` + `npm run build`
from manifests-first layers), stage 2 the pinned uv runtime with
`COPY --from=build /build/dist ./frontend/dist` (api.py's static mount) and
`CUBESAT_LOG_DIR=/app/data/logs`. Image build and `/health` check: not run in
this round — build size and health evidence unmeasured.

Why unmeasured (honest status, not faked): `docker version` → exit 1, daemon
down ("failed to connect to the docker API at
npipe:////./pipe/dockerDesktopLinuxEngine — The system cannot find the file
specified"), so `docker build` was NOT RUN and the node:22-slim pull + npm ci
network access are likewise unexercised. Also landed: `.dockerignore` gains
`frontend/node_modules` and `frontend/dist` so stage 1's `COPY frontend/`
cannot ship the host's node_modules (GBs, Windows binaries) or a stale
host-built dist into the build context — without it the manifest-cached
`npm ci` layer is defeated. Only files touched: Dockerfile, .dockerignore;
no sim-core files.

## Oracle sweep v3 + reassign_on_degrade (2026-10-29)

Build notes for the degrade-trigger round. Pre-registration + decision rule in
GATES.md (2026-10-29 entries, recorded before any v3 number existed); report
data/eval/oracle_sweep_v3.json (committed, machine-written), tool
files/oracle_sweep_v3.py. Numbers are quoted from that report with their
commands, never re-derived. Outcome per the pre-registered rule:
**RECOMMENDED as an opt-in scenario field** (`recommend: true`); defaults
never change canonical logs.

### Implementation shape

- Field: `reassign_on_degrade: bool = False` (cubesat/scenario.py:188-199) —
  a defaulted-off Scenario field. No committed scenario sets it; the
  default-False assert plus the stronger direction (the flag-ON two_failure
  run, which has no EPS_DEGRADE and hence no DEGRADED transition, still
  reproduces canonical sha `450d5371…`) are pinned by
  tests/test_oracle_sweep_v3.py::test_reassign_on_degrade_defaults_false.
- Hook: inside the EPS_DEGRADE fade-firing block (cubesat/sim.py:249-278).
  When a satellite holding a critical role (`_CRITICAL_ROLES` = leader,
  downlink — cubesat/sim.py:95) transitions NOMINAL → DEGRADED and the mission
  is NOMINAL or RECOVERED and recovery_enabled, the sim fires the oracle
  path's proactive critical-seat swap via
  `_swap_critical_seat(..., "degrade_trigger")` (cubesat/sim.py:98-131 —
  factored out of the oracle block at cubesat/sim.py:493 so there is no
  duplicated logic; the oracle call passes mode_label=None and keeps its exact
  committed payload shape). Event label: `ORACLE_SWAP` — same type as the
  oracle path — with one additive payload key `mode: "degrade_trigger"`.
  Test-pinned transient (eps_leader_6sat, fade t = 600.0, t_fail = 2400.0):
  the event pops at t = 602.0 (FIFO, one event per tick line) with payload
  `{role: "leader", from_sat: 0, to_sat: 1, t: 600.0, mode: "degrade_trigger"}`
  (target = lowest-index healthy non-critical sat); the transition tick's line
  already shows the moved seat (fading sat DEGRADED in a non-critical slot,
  leader seat on a NOMINAL holder), positions byte-equal through the
  transition tick and diverging at the first step after.
- Semantics: the EPS_DEGRADE fade window IS the warning, so the trigger's
  timing equals the oracle L = 1800 point on the eps families (degrade_s =
  1800 there; the swap fires at max(t_fail − degrade_s, 0)) with NO oracle and
  NO predictor — `oracle_enabled: false` on every degrade_trigger report row.
  The fading satellite ends in a non-critical slot but stays NON-assignable
  (status != NOMINAL — existing replan rules untouched), and the swap is
  once-per-transition, event-driven, fully deterministic
  (test_degrade_trigger_run_byte_deterministic).
- Tests: tests/test_oracle_sweep_v3.py — 5 tests (swap transient, default-off
  byte-inertness, imager-fade no-op, THRUSTER_OUT no-op, run-level byte
  determinism).

### Trigger vs oracle (eps families, report numbers)

Sweep command (the report's own `command` field): `uv run python files/oracle_sweep_v3.py`;
L grid {0, 30, 60, 300, 600, 900, 1200, 1800} s, t_settle = 0.0 s,
`capped: false` on all 36 rows.

- **eps_leader_6sat — the RECOMMENDED family** (best eps family on the pinned
  metric; ties keep the first family in the fixed SCENARIOS order,
  files/oracle_sweep_v3.py:322-327). Trigger (policy `degrade_trigger`):
  pinned gain **10.616559013505578 pp**, functional **0.04697592483852153 pp**,
  coverage **+0.15070424170359198 pp**, Δv **562.8040133364024 m/s** vs
  reactive baseline **401.8444631108469 m/s** (log sha256 `1db789e9…`).
  Oracle: needs L = 1800 s to match it on the pinned metric
  (**10.604815032295944 pp**, Δv 710.639299795296 m/s) and at the
  pre-registered L = 300 s checkpoint gains **1.7968291250733959 pp** for
  **3210.3089538855684 m/s** — CW transfer-time scaling (the
  maneuver must complete inside L; see the GATES.md 2026-10-29 evidence
  block). The trigger reaches oracle-L=1800 timing with no oracle, no
  predictor, and less Δv than the oracle point.
- **eps_downlink_6sat — NOT recommended** (fails the pre-registered no-harm
  arm): pinned gain ties at **10.616559013505578 pp** but coverage gain is
  **-0.09142218879213404 pp**; Δv 707.7992440054265 vs baseline
  387.82168138883605 m/s. The opt-in is family-scoped, not blanket.
- **Controls**: eps_imager_6sat is structurally flat on both SEAT metrics —
  pinned gain and functional gain are exactly **0.0 pp** at every oracle L —
  but its mean-coverage column is small and NONZERO at every oracle L
  (**+0.005511483377262927 pp** at L=30, +0.020640566350743628 at L=60,
  +0.09672592224165277 at L=300, +0.0667121679743754 at L=600,
  **+0.12154592831528088** at L=900, +0.01016752587555958 at L=1200,
  +0.10216408211499162 at L=1800): the oracle's replan re-phases the
  survivor formation (select_formation), which moves mission-level mean
  coverage a little even where no critical seat is at stake. Its
  degrade_trigger row IS byte-identical to the reactive row (same log sha256
  `170cfec2…` — an imager fade is not a critical-role transition).
  thruster_leader_6sat: its trigger row is likewise byte-identical to
  reactive (sha256 `6e742851…` — THRUSTER_OUT has no DEGRADED transition; the
  self-report path already reacts on the firing tick), but the 0.0 quantifier
  does NOT extend to its oracle rows: those gain **+0.023487962419255215 pp**
  pinned, and the same functionally, at every L > 0 — the 2-tick
  self-report/detection window, matching the v2 note above.

### Caveats

- **Pinned-metric honesty (carried per the pre-registration):** the pinned
  metric counts the still-functional 1800 s fade window as critical-seat
  outage — reactive baseline 0.8938344098649442 pinned vs 0.9995302407516148
  functional (the gap IS the fade window). Mission-level truth: functional
  gain 0.04697592483852153 pp and coverage gain +0.15070424170359198 pp
  (leader trigger).
- **Δv cost is real:** the trigger spends more than the reactive baseline in
  both eps families (leader 562.8040133364024 vs 401.8444631108469 m/s;
  downlink 707.7992440054265 vs 387.82168138883605 m/s); every Δv inherits
  the standing a_max = 0.1 over-thrust caveat (GATES.md open risks).
- **Timing equivalence is degrade_s-dependent:** the trigger fires at
  max(t_fail − degrade_s, 0); the "equals oracle L = 1800" statement holds for
  the committed degrade_s = 1800 scenarios. A shorter window is an earlier,
  more expensive transfer (same CW scaling as the oracle curve).
- **Predictor boundary:** for gradual EPS deaths the 1800 s telemetry fade
  dominates the sealed LightGBM predictor's measured 260 s paired median lead
  (out2/results.json; GATES.md 2026-10-04) — the predictor stays
  beside-heartbeat (display-only), cut from the control loop; the trigger
  needs no prediction.
- **Not covered by this round:** Docker build still unverified (daemon down,
  `docker version` exit 1, re-verified first-hand 2026-10-29); browser render
  pass pending; README/pitch wording left to the user (audit_out/AUDIT.md
  MUST-NOT-claim list applies — no AI-in-the-loop claim: the trigger is a
  deterministic rule).

### Regenerate

```
uv sync --locked
uv run python files/oracle_sweep_v3.py
#   -> data/eval/oracle_sweep_v3.json (committed report) + the 36 per-point
#      scenario variants and JSONL logs under data/eval/oracle_sweep_v3/
#      (gitignored; each report row carries its own regeneration command, e.g.
#      uv run python -m cubesat.run --scenario data/eval/oracle_sweep_v3/eps_leader_6sat__degrade_trigger.json --seed 42 --out data/eval/oracle_sweep_v3/eps_leader_6sat__degrade_trigger.jsonl)
uv run python -m pytest tests/test_oracle_sweep_v3.py -v   # 5 passed
```

Write-time re-verification (2026-10-29, ledger session, first-hand): the sweep
re-run reproduced the report byte-identically (sha256
`cdd5a069c006c355a6655cc33093b0585332ef825df26b15c0f8ba2340f94b02` before and
after, `cmp` exit 0); `uv run python -m pytest tests/test_oracle_sweep_v3.py
-v` → 5 passed; golden pins (`uv run python -m pytest tests/test_failure_modes.py
tests/test_cli.py -q`) → 9 passed, exit 0; fast loop `uv run python -m pytest
-m "not slow"` → 168 passed, 3 deselected; `uv run ruff check .` → All checks
passed.

## Security round (2026-10-29)

Build notes for the security round; decisions in GATES.md (2026-10-29 entries),
evidence in GATES.md (Security round evidence, 2026-10-29). Three workstreams:
the frontend dependency bump, the CLI output-path confinement, and a security
audit followed by a same-round remediation pass ("security-fix pass"). Every
number below carries its command or its code citation; remediation statuses are
as measured in the working tree at ledger-write time (2026-10-29), first-hand.

### Frontend dependency bump (vite 5.4 → 7.x) — what changed and why

`frontend/package.json` devDependency `vite` bumped `^5.4.14` → `^7.3.7`
(one line, frontend/package.json:24; lockfile regenerated) — the round's only
frontend delta, authorized by the user's "fix them all" instruction on the 9
open Dependabot alerts. Why: `npm audit` (before) reported 2 vulnerabilities —
esbuild <= 0.24.2 (GHSA-67mh-4wv8-2f99, the moderate) reached through vite
5.4.21, and the vite <= 6.4.3 advisory chain (the high; 8 GHSAs, enumerated in
the GATES.md evidence row). After: vite 7.3.7 pulls esbuild 0.28.2 (patched
>= 0.25) and `npm audit` reports found 0 vulnerabilities (re-run first-hand at
write time). `@vitejs/plugin-react` stays on its `^4.3.4` pin — it resolves to
4.7.0, whose peerDependencies (`npm view @vitejs/plugin-react@4.7.0
peerDependencies` → `{ vite: '^4.2.0 || ^5.0.0 || ^6.0.0 || ^7.0.0' }`) already
accept vite 7, so no plugin bump was needed. launch-editor disappeared from the
lockfile (vite 7 dropped that dependency chain). `npm audit fix --force` was
deliberately NOT run — npm's suggested fix was vite 8.3.5, an unrequested major
jump. Node compatibility: vite 7.3.7 engines `^20.19.0 || >=22.12.0`; the dev
machine (node v24.21.0) and the Docker build stage (`FROM node:22-slim`,
Dockerfile:4) both satisfy it. `npm run build` exit 0 on the bumped tree
(tsc + vite v7.3.7; only the pre-existing >500 kB chunk-size warning).
FRONTEND_SPEC §13.7 gates: hex grep clean —
`grep -rnE '#[0-9a-fA-F]{3,8}' src | grep -v 'tokens\.css'` exit 1 (all 44 hex
literals live in src/styles/tokens.css, re-run first-hand); avoid-ai-design
scanner exit 0 (run from a /tmp clone per the spec's own §13.7 two-line recipe
— detect.mjs is not a repo file; 3 advisory P2 findings pre-exist in
frontend/src files this diff does not touch, and frontend/src is off-limits to
this round by workspace rule). react/typescript/zustand/recharts pins and
vite.config.ts unchanged.

### CLI output-path confinement — what changed and why

Every CLI-provided OUTPUT path must resolve inside the repository root before
anything is read or written; refusal is a clean argparse error (usage +
`refusing: <label> <path> resolves outside the repository <root>` on stderr,
exit 2), nothing written; differing Windows drives count as outside
(os.path.commonpath ValueError). The rule mirrors the user-approved
predictor-bundle hardening (files/predictor_pipeline.py:264-279, decisions
2026-10-03) and closes the audit's "command-line parameter → path traversal"
finding across all three CLIs:

- `cubesat/benchmark.py` — `_confine_output_path()` (benchmark.py:366-385) +
  a validation loop immediately after `parser.parse_args` (benchmark.py:458-466)
  covering `--out`, `--report`, `--manifest`, `--csv`, `--svg`, before every
  dispatch and before the `--base` read. Derived defaults stay confined by
  construction (the monte-carlo `--out` default is the repo-relative literal
  `data/eval/monte_carlo`; the pareto/cw-curve `--csv`/`--svg` defaults share
  `--report`'s parent via `Path.with_name`).
- `cubesat/dv_bound.py` — the same guard (dv_bound.py:55), applied to
  `--report`/`--csv` (dv_bound.py:456-457) in the security-fix pass.
- `cubesat/cluster_import.py` — the same guard (cluster_import.py:41), applied
  to `--out` (cluster_import.py:219) in the security-fix pass.

Tests first (the benchmark reject test was watched red pre-fix — the CLI
sailed past an escaping `--out`): tests/test_benchmark.py:408
`test_cli_rejects_path_escaping_repo_root` and :453
`test_cli_accepts_documented_paths` (the no-over-rejection guard: the five
documented GATES shapes all write under data/eval/ and pass unchanged);
tests/test_dv_bound.py:142 and tests/test_cluster_import.py:149 rejection
tests for the fix-pass guards. Subprocess evidence: `--out
../cubesat_subproc_probe_out` → exit 2, probe dir never created; positive
control with the documented shape proceeds to the (deliberately missing) base
read — zero over-rejection. Write-time probe re-run first-hand
(`--report ../outside_probe_ledger_check.json` → exit 2, no file). Scope
caveats: input paths `--base`/`--p0-dir`/`--p0-manifest` remain unvalidated
reads (the ask scoped confinement to output paths; a hostile `--p0-dir` can
only source bytes copied INTO the confined out dir and hashed into the
report); relative documented shapes resolve against CWD — documented commands
run from the repo root, same trust model as before.

### Security audit — checked surfaces and remediation status

The audit probed the surfaces below against the pre-fix tree (probe evidence
in the GATES.md evidence row); the same-round security-fix pass remediated
them; every status was re-verified first-hand in the working tree at write
time. Severity framing: medium = wedging the localhost single-user demo
process; lows are hardening.

| # | Surface (audit citation) | Finding | Status (first-hand) |
|---|---|---|---|
| 1 | cubesat/session.py:278 | MEDIUM — scenario resources unbounded (20,000,000-char upload accepted, 20,000,404 bytes written; `duration_s=1e9` passed the schema's bare gt=0; the coverage grid materializes (2·extent/step+1)² points) AND the 60 s run timeout abandoned the still-running compute thread (asyncio.wait_for cancels only the await; same pattern in inject_failure) | FIXED, both halves — schema caps (cubesat/scenario.py:11-24: MAX_GRID_POINTS 10 000 via the Sensor `_grid_fits_budget` validator scenario.py:65-78, sweeps max_length 64 scenario.py:117-128, MAX_SATS 32 on n_slots and roles scenario.py:45,180-182, MAX_FAILURES 64 scenario.py:183, MAX_DURATION_S 86 400 scenario.py:171-173, dt_s le 10 scenario.py:174; each ~5x above every committed value, canonical logs byte-identical) + cooperative cancellation (`run_scenario(scenario, cancel_event=None)` cubesat/sim.py:149-150, checked between ticks sim.py:223-224 raising RunCancelled; start_live sets it on timeout session.py:286-294, inject_failure ditto session.py:406-417); unset-hook byte-inertness pinned by `test_run_scenario_cancel_event_unset_is_byte_identical`; cap rejections pinned by tests/test_scenario_schema.py:58-118 |
| 2 | cubesat/dv_bound.py:434 + cubesat/cluster_import.py:214-217 | LOW — the CLI confinement fix existed only in benchmark.py (probed: dv_bound wrote %TEMP%\outside_dv_report.json + .csv exit 0; cluster_import wrote outside the repo exit 0; benchmark refused exit 2) | FIXED — guards at dv_bound.py:55/:456-457 and cluster_import.py:41/:219 (see the confinement section above) |
| 3 | cubesat/api.py:324 | LOW — a malformed WS frame raised json.JSONDecodeError out of read_loop (re-raised at api.py:340 pre-fix) as an unhandled server exception per bad frame instead of a graceful close | FIXED — read_loop catches it and closes with code 1003 unsupported-data (api.py:421-431); the finally block still unsubscribes |
| 4 | cubesat/api.py:177 | LOW — attacker-controlled Scenario.name/roles[] echoed verbatim into /health, WS hello and sim_state (stored injection; inert while React escapes — grep for dangerouslySetInnerHTML/innerHTML/document.write/new Function in frontend/src = 0 matches; XSS the moment a non-escaping consumer renders these fields) | FIXED at the write edge — `_LABEL_UNSAFE` strips `<`, `>`, `&`, quotes and control characters from name and roles[] BEFORE validation and write (api.py:195-209, applied at api.py:263), so what is validated/stored/echoed is the inert payload; legitimate labels byte-untouched |
| 5 | cubesat/api.py:181 | LOW — no request-size cap or file-count limit on POST /scenarios/upload (20 MB filler accepted and written; overwrites were already 409 with committed scenarios protected; the name sanitizer already stripped separators — only volume was open) | FIXED — MAX_UPLOAD_BYTES 262 144 (api.py:49) enforced as a Content-Length middleware returning 413 (api.py:99-119) AND as a serialized-size cap on the exact bytes written (api.py:264-269); MAX_SCENARIO_FILES 64 → 429 (api.py:247-259) |
| 6 | Dockerfile:53 | LOW — no Host-header validation and no authentication anywhere; the container CMD binds 0.0.0.0 (Dockerfile:56); DNS rebinding defeats browser origin checks against a Host-agnostic app; local uvicorn serve binds 127.0.0.1 (the mitigating reality) | PARTIALLY FIXED — TrustedHostMiddleware allowlist, default localhost,127.0.0.1,testserver with a CUBESAT_ALLOWED_HOSTS override (api.py:82-96; Dockerfile:45-47 documents the publish-beyond-localhost caveat); authentication itself remains absent BY DESIGN — the localhost bind stays the demo's real boundary |
| 7 | cubesat/api.py:201 | LOW — GET /replay/file/{filename} served ANY file in the log dir regardless of extension while /replay/files lists only .jsonl (traversal itself was solid: 6 encoded payloads + '..' all 404, positive control 200) | FIXED — a suffix filter mirrors list_logs (api.py:287-302): serve surface now equals listing surface |
| 8 | pyproject.toml:18 | LOW — unused dev dependency httpx2 >= 2.13.1 (nothing imported it; a Pydantic-stewarded httpx fork, not malicious — pure supply-chain surface, dev-only, excluded from the image by uv sync --no-dev) | FIXED — removed from the dev group; docs/BACKEND_SPEC.md:72 and :409 mark it DONE (2026-10-29 security-fix pass, removed with user approval); no httpx2 references remain in pyproject.toml, uv.lock or any .py file (grep, first-hand) |

### Unverified / not done in this round

- **Dependabot alert clearing is EXPECTED-AFTER-PUSH, not observed.** The 9
  alerts were still open at write time (read-only `gh api
  repos/dptel22/Cubesat/dependabot/alerts?state=open` → 9); they close on
  Dependabot's next scan of the pushed default branch, and the user commits
  and pushes (agents never do). Local `npm audit` 0 against the same advisory
  data is the verifiable proxy, and every one of the 9
  vulnerable_version_ranges lies outside vite 7.3.7 / esbuild 0.28.2.
- **The avoid-ai-design scanner was not re-run at ledger-write time** (it
  needs the /tmp clone per the FRONTEND_SPEC §13.7 recipe); the round's
  builder evidence (exit 0, 119 files scanned, 3 advisory P2 in untouched
  files) stands, and the hex drift gate was re-run first-hand (clean).
- **No Docker build was run against the regenerated lockfile this round** —
  the node:22-slim compatibility is a static engines check, not a build
  measurement; image size/health evidence remains as recorded in the
  2026-10-26 section (unverified there, daemon down).
- **The API is still unauthenticated by design** — the TrustedHost allowlist
  is not auth; the localhost single-user bind remains the security boundary
  for the demo, and publishing the container port beyond the operator's
  machine remains the audit's medium-if-published caveat.
- **Fast-suite count moved under the round's feet**: the backend-hardening
  builder measured 144/147 collected; at write time the same command collects
  168/171 (3 slow-deselected) because the concurrent sweep-v3 round
  (files/oracle_sweep_v3.py + tests/test_oracle_sweep_v3.py + the
  `reassign_on_degrade` scenario field, pre-registered in GATES.md
  2026-10-29) and this round's security-fix tests landed in the same working
  tree. Both runs exited 0; neither count is padded.

