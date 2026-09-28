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
