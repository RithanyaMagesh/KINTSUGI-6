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
- `stm` is the unforced STM; thrusting dynamics (STM step + control) are G2
  scope and not verified yet.

### Reproduce

```
uv sync --locked
uv run pytest tests/test_hcw.py -s -q   # the two measured numbers above
uv run pytest -q                        # full suite, includes the slow Kepler test
```
