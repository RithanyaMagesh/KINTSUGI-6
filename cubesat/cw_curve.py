"""P3 CW-validity error curves (docs/ENDGAME_PLAN.md section 6, zero core diff).

The CW-vs-two-body cross-check of tests/test_hcw.py::test_cw_vs_kepler_error_report
(tests/test_hcw.py:103-162) is FACTORED here to emit the (t, position error)
array per state, and rendered for THREE formation scales:

  (i)   1 km radial / 500 m cross-track passive ellipse -- the G1 evidence state
        (tests/test_hcw.py:112-113); recorded max 3.101 m (GATES.md G1 row);
  (ii)  G3-era nominal slot 11 km radial / 11 km cross-track = 22 km
        along-track (GATES.md:26), re-tuned away at G4; recorded max 2984.5 m
        (README command of record, slot_initial_state(11000, 11000, pi/2, N));
  (iii) the CURRENT two_failure scale, radial_amp_km = 8 (two_failure.json:7)
        -> 16 km along-track (along-track = 2 x radial, MASTER_PROMPT.md:55);
        freshly measured at P3 -- the command of record is in the report JSON.

Provenance note (honest): the two-body reference integration necessarily lives
here a second time -- its previous home is the frozen evidence test (must not be
modified) and cubesat/hcw.py is sim core -- while the CW propagation itself is
IMPORTED (stm_propagate, cubesat/hcw.py:31), never duplicated. The new test
test_cw_vs_kepler_error_curve_matches_report_max pins the equivalence by
reproducing the recorded 3.101 m at the shared 1 km state.

Command of record (writes all three artifacts):

    uv run python -m cubesat.benchmark --mode cw-curve \
        --base data/scenarios/two_failure.json \
        --report data/eval/cw_error_report.json \
        --csv data/eval/cw_error_curve.csv --svg data/eval/cw_error_curve.svg

Determinism: fixed state order, index iteration only, no RNG, no wall clock
(AGENTS.md invariant 2); solve_ivp RK45 is deterministic for fixed inputs.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

from cubesat.hcw import slot_initial_state, stm_propagate

MU = 3.986004418e14  # Earth gravitational parameter, m^3/s^2 (as tests/test_hcw.py:28)
R_EARTH = 6378.137e3  # m
A_CHIEF = R_EARTH + 500e3  # m, 500 km altitude
N = math.sqrt(MU / A_CHIEF**3)  # rad/s, ~1.1068e-3
PERIOD = 2.0 * math.pi / N  # s, ~5677 s

T_GRID = np.linspace(0.0, 3.0 * PERIOD, 601)  # 3 orbits, 601 samples (tests/test_hcw.py:123)
RTOL = 1e-12
ATOL = 1e-9

# Column order is the committed CSV's column order (fixed tuple, invariant 2).
COL_NAMES = ("err_1km", "err_g3era_11km", "err_current_8km")

# Recorded constants (GATES.md evidence rows; the current-scale constant is the
# fresh P3 measurement, pinned after the command of record first ran).
ONEKM_RECORDED_MAX_M = 3.101  # GATES.md G1 row
G3ERA_RECORDED_MAX_M = 2984.5  # GATES.md:26, README command of record
CURRENT_8KM_RECORDED_MAX_M = 1578.543395  # fresh P3 measurement (command of record in the report)


def state_1km_passive_ellipse() -> np.ndarray:
    """The G1 evidence state, verbatim from tests/test_hcw.py:112-113."""
    x0 = 1000.0
    return np.array([x0, 0.0, 500.0, 0.0, -2.0 * N * x0, 0.0])


def state_g3era_11km() -> np.ndarray:
    """G3-era nominal slot (re-tuned away at G4): 11 km radial / 11 km
    cross-track = 22 km along-track -- exactly the README command of record's
    S(11000.0, 11000.0, math.pi/2, N) state."""
    return slot_initial_state(11000.0, 11000.0, math.pi / 2.0, N)


def state_current(radial_amp_m: float) -> np.ndarray:
    """Current two_failure slot at the same ellipse phase: cross-track amplitude
    equals radial (allocate.select_formation builds slot_initial_state(amp, amp,
    ...) -- allocate.py:158), so along-track = 2 x radial (MASTER_PROMPT.md:55)."""
    return slot_initial_state(radial_amp_m, radial_amp_m, math.pi / 2.0, N)


def _two_body(_t, state):
    """Independent two-body truth (tests/test_hcw.py:125-127)."""
    r = state[:3]
    return np.concatenate([state[3:], -MU * r / np.linalg.norm(r) ** 3])


def _propagate_two_body(state0: np.ndarray, t_grid: np.ndarray) -> np.ndarray:
    sol = solve_ivp(
        _two_body,
        (0.0, float(t_grid[-1])),
        state0,
        method="RK45",
        rtol=RTOL,
        atol=ATOL,
        t_eval=t_grid,
    )
    assert sol.success
    return sol.y


def chief_states(t_grid: np.ndarray) -> np.ndarray:
    """Two-body chief trajectory -- identical for every chaser state, computed
    once (the chief IC is the same tests/test_hcw.py:114-115 circular orbit)."""
    r_chief0 = np.array([A_CHIEF, 0.0, 0.0])
    v_chief0 = np.array([0.0, N * A_CHIEF, 0.0])
    return _propagate_two_body(np.concatenate([r_chief0, v_chief0]), t_grid)


def cw_vs_kepler_errors(
    state0: np.ndarray, *, t_grid: np.ndarray, n: float, chief_y: np.ndarray
) -> np.ndarray:
    """The factored cross-check: per-sample CW-vs-two-body position error [m].

    Same math as tests/test_hcw.py:147-159, emitting the full array instead of
    only the max. Chief and chaser start on the same circular inertial orbit,
    the chaser offset by the LVLH state; rotating-frame velocity maps to
    inertial via the transport theorem (tests/test_hcw.py:116-120)."""
    rho0 = np.asarray(state0, dtype=float)[:3]
    nu0 = np.asarray(state0, dtype=float)[3:]
    r_chief0 = np.array([A_CHIEF, 0.0, 0.0])
    v_chief0 = np.array([0.0, N * A_CHIEF, 0.0])
    omega = np.array([0.0, 0.0, n])
    r_chaser0 = r_chief0 + rho0
    v_chaser0 = v_chief0 + nu0 + np.cross(omega, rho0)
    chaser_y = _propagate_two_body(np.concatenate([r_chaser0, v_chaser0]), t_grid)
    cw = np.asarray(stm_propagate(np.concatenate([rho0, nu0]), t_grid, n))
    errors = np.empty(t_grid.size)
    for k in range(t_grid.size):  # index iteration (AGENTS.md invariant 2)
        r_c = chief_y[:3, k]
        v_c = chief_y[3:, k]
        dr = chaser_y[:3, k] - r_c  # chaser minus the chief the CW frame is anchored to
        x_hat = r_c / np.linalg.norm(r_c)
        h_hat = np.cross(r_c, v_c)
        h_hat = h_hat / np.linalg.norm(h_hat)
        y_hat = np.cross(h_hat, x_hat)
        rho_kepler = np.array([dr @ x_hat, dr @ y_hat, dr @ h_hat])
        errors[k] = np.linalg.norm(rho_kepler - cw[k, :3])
    return errors


def cw_curve_report(*, command: str, radial_amp_m: float = 8000.0) -> dict:
    """Run the cross-check for the three states; return the report dict with the
    per-state (t, error) arrays (private keys, dropped from the JSON)."""
    chief_y = chief_states(T_GRID)
    states = [
        (COL_NAMES[0], "1 km passive ellipse (G1 evidence state, tests/test_hcw.py:112-113)",
         state_1km_passive_ellipse()),
        (COL_NAMES[1], "G3-era nominal slot 11/22 km, re-tuned away at G4 (GATES.md:26)",
         state_g3era_11km()),
        (COL_NAMES[2], f"current two_failure scale {radial_amp_m / 1000.0:g} km radial / "
         f"{radial_amp_m / 500.0:g} km along-track (two_failure.json:7)",
         state_current(radial_amp_m)),
    ]
    errors: dict[str, np.ndarray] = {}
    state_meta: dict[str, dict] = {}
    for name, label, st in states:
        errors[name] = cw_vs_kepler_errors(st, t_grid=T_GRID, n=N, chief_y=chief_y)
        state_meta[name] = {
            "label": label,
            "initial_state_m_mps": [float(v) for v in st],
        }
    return {
        "command": command,
        "orbits": 3.0,
        "n_samples": int(T_GRID.size),
        "t_end_s": float(T_GRID[-1]),
        "period_s": PERIOD,
        "rtol": RTOL,
        "atol": ATOL,
        "radial_amp_current_m": radial_amp_m,
        "states": state_meta,
        "recorded_constants_m": {
            "err_1km": ONEKM_RECORDED_MAX_M,
            "err_g3era_11km": G3ERA_RECORDED_MAX_M,
            "err_current_8km": CURRENT_8KM_RECORDED_MAX_M,
        },
        "max_err_m": {name: float(errors[name].max()) for name in COL_NAMES},
        "_t": T_GRID,
        "_errors": errors,
    }


def write_report_json(report: dict, path: Path) -> Path:
    """Machine-written report JSON (invariant 1): the whitelisted keys only --
    the (t, error) arrays live in the committed CSV, not here."""
    public = {k: v for k, v in report.items() if not k.startswith("_")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(public, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def write_csv(report: dict, csv_path: Path) -> Path:
    """Machine-written cw_error_curve.csv: t [s] plus the three per-state error
    columns [m], one row per sample (AGENTS.md invariant 1)."""
    t = report["_t"]
    errors = report["_errors"]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", *COL_NAMES])
        for k in range(t.size):
            writer.writerow([f"{t[k]:.3f}", *[f"{errors[c][k]:.6f}" for c in COL_NAMES]])
    return csv_path


def write_svg(report: dict, svg_path: Path, *, width: int = 640, height: int = 500) -> Path:
    """Three CW-vs-Kepler error curves, stdlib SVG only (ENDGAME_PLAN 6, no
    matplotlib). Two stacked panels sharing the time axis in orbits: the full
    linear scale (G3-era + current curves) and a zoom for the 1 km curve."""
    t = report["_t"]
    errors = report["_errors"]
    maxes = report["max_err_m"]
    margin = 56
    panel_h = 150
    tops = (36.0, height - margin - panel_h - 44.0)
    t_hi = float(t[-1] / PERIOD)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="monospace" font-size="11">',
        f"<text x='{margin}' y='18'>CW vs two-body position error over 3 orbits "
        "(601 samples, rtol 1e-12; ENDGAME_PLAN P3)</text>",
    ]
    panels = [
        (tops[0], (("err_g3era_11km", "#d62728"), ("err_current_8km", "#2ca02c"))),
        (tops[1], (("err_1km", "#1f77b4"),)),
    ]
    for top, curves in panels:
        y_hi = max(maxes[c] for c, _ in curves) * 1.1

        def px(tv: float, top=top) -> float:
            return margin + tv / t_hi * (width - 2 * margin)

        def py(y: float, top=top, y_hi=y_hi) -> float:
            return top + panel_h - y / y_hi * panel_h

        parts.append(
            f"<rect x='{margin}' y='{top:.0f}' width='{width - 2 * margin}' "
            f"height='{panel_h}' fill='none' stroke='#999'/>"
        )
        for k in range(4):  # x ticks 0..3 orbits
            parts.append(
                f"<text x='{px(k):.1f}' y='{top + panel_h + 13:.1f}' "
                f"text-anchor='middle'>{k}</text>"
            )
        parts.append(
            f"<text x='{width / 2}' y='{top + panel_h + 26:.1f}' text-anchor='middle'>time (orbits)"
            "</text>"
        )
        y_lab = f"{y_hi:.0f}" if y_hi >= 10.0 else f"{y_hi:.1f}"
        parts.append(
            f"<text x='{width - margin + 6:.1f}' y='{top + panel_h:.1f}'>{y_lab} m</text>"
        )
        for ci, (col, color) in enumerate(curves):
            pts = " ".join(
                f"{px(t[k] / PERIOD):.1f},{py(errors[col][k]):.1f}" for k in range(t.size)
            )
            parts.append(
                f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1'>"
                f"<title>{col}: max {maxes[col]:.3f} m</title></polyline>"
            )
            parts.append(
                f"<text x='{margin + 8:.1f}' y='{top + 14 * (ci + 1):.1f}' "
                f"fill='{color}'>{report['states'][col]['label']}: max {maxes[col]:.3f} m</text>"
            )
    parts.append("</svg>")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return svg_path
