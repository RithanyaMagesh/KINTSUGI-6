"""Predictor runtime module (Phase 1).

Offline scoring of a CubeSat scenario against the trained LightGBM predictor.
Zero sim diff: this file synthesises telemetry from the *sim's* failure schedule
and scores it with the frozen model.  The sim itself is never touched.

Interfaces:
    telemetry_from_schedule(scenario, seed) -> np.ndarray  shape (N_SATS, T_TICKS, 6)
    score_run(telemetry)                    -> list of ScoredRow (dataclass)
    suspect_alerts(scored_rows)             -> list of Alert (dataclass)

Constants (must match predictor_pipeline.py):
    DT=2 s, STRIDE=10, WARM=300, K_ALARM=3, 6 channels, profile A parameters.

Honest caveats (INTEGRATION_PROMPT Phase 4 / AGENTS.md invariant 1):
  - two_failure runs 8515 ticks (pipeline trains on T_TICKS=5400).  Scoring
    past tick 5400 is structurally out-of-distribution; we report it but mark
    rows beyond T_TICKS explicitly.
  - Failures in two_failure fire at t=1200/1500 s (ticks 600/750).  With
    warmup=300 ticks the *first scored tick* is 300 and the first failure is
    at tick 600, leaving only 30 scored rows (600 s) of precursor window.
    Profile-A ramps are [1800, 3600] s = [900, 1800] ticks, so both failures
    sit well inside their own ramps; the model sees a partial ramp at most.
    We report degenerate / zero lead and say so.
  - Sudden-death families have ~0 recall by construction; this module only
    overlays EPS-fade / comms ramps on scheduled failures.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv

from cubesat.scenario import Scenario

# -- constants that MUST match predictor_pipeline.py --------------------------
DT: float = 2.0          # s per tick
T_TICKS: int = 5400      # pipeline training length (2 orbits)
ORBIT_S: float = 5400.0
STRIDE: int = 10         # score every 20 s
WARM: int = 300          # first scored tick
K_ALARM: int = 3         # consecutive scored rows >= tau -> PREDICTOR_ALERT
BASE_N: int = 150        # startup ticks for frozen robust baseline
WINS = [15, 60, 300]     # feature window sizes (ticks)
NC: int = 6              # channels: volt, soc, duty, lat, jit, temp
CH = ["volt", "soc", "duty", "lat", "jit", "temp"]

# Nominal channel means and eclipse corrections (copied from pipeline)
NOM = np.array([7.4, 90.0, 0.02, 40.0, 5.0, 25.0], dtype=np.float64)
ECL_NOM = np.array([-0.35, -8.0, 0.0, 0.0, 0.0, -3.0], dtype=np.float64)

# Profile A ramp parameters (train/val family; copied from pipeline PROFILES["A"])
_PROFILE_A = dict(
    R=(1800, 3600),
    rate=(0.03, 0.05),
    dtemp=(3, 6),
    lat_end=(100, 120),
    jit_end=(30, 40),
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_PATH = _REPO_ROOT / "models" / "predictor_manifest.json"
_MODEL_PATH = _REPO_ROOT / "models" / "predictor.txt"


# -- public dataclasses -------------------------------------------------------

@dataclass
class ScoredRow:
    sat_id: int
    tick: int           # sim tick index
    t_s: float          # sim time in seconds
    score: float        # raw LGB probability
    ood: bool           # True if tick >= T_TICKS (out of pipeline training range)


@dataclass
class Alert:
    """PREDICTOR_ALERT: sat_id fired K_ALARM consecutive rows >= tau."""
    sat_id: int
    tick: int           # first tick in the K_ALARM run
    t_s: float          # seconds
    score: float        # score at the alert tick


# -- helpers (private) --------------------------------------------------------

def _box(x: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same")


def _detrend(x: np.ndarray, ecl: np.ndarray) -> np.ndarray:
    """Remove known eclipse response; x shape (T, C)."""
    return x - ecl[:, None] * ECL_NOM


def _robust_base(r: np.ndarray):
    """Median / 1.4826*MAD from first BASE_N rows."""
    med = np.median(r[:BASE_N], axis=0)
    mad = np.median(np.abs(r[:BASE_N] - med), axis=0) * 1.4826
    return med, np.maximum(mad, 1e-3)


def _eclipse_box(rng: np.random.Generator, T: int) -> np.ndarray:
    """Smoothed eclipse flag, same logic as gen_run."""
    t = np.arange(T) * DT
    raw = (((t + rng.uniform(0, ORBIT_S)) % ORBIT_S) > 0.65 * ORBIT_S).astype(float)
    return _box(raw, 30)


def _features_T(x: np.ndarray, ecl: np.ndarray, T: int):
    """
    Compute features for one satellite over T ticks (past-only).

    x   : (T, NC) raw telemetry
    ecl : (T,)    eclipse box

    Returns (F, idx, names):
      F     : (n_scored, n_features) float32
      idx   : (n_scored,) tick indices
      names : list[str]
    """
    r = _detrend(x, ecl)
    med, sd = _robust_base(r)
    idx = np.arange(WARM, T, STRIDE)
    feats, names = [], []
    for c in range(NC):
        xc = r[:, c]
        means: dict[int, np.ndarray] = {}
        for w in WINS:
            seg = swv(xc, w)[idx - w + 1]
            tt = np.arange(w) - (w - 1) / 2
            m = seg.mean(1)
            means[w] = m
            feats += [m, seg.std(1), seg.min(1), seg.max(1),
                      (seg @ tt) / (tt @ tt), (m - med[c]) / sd[c]]
            names += [f"{CH[c]}_w{w}_{k}" for k in ("mean", "std", "min", "max", "slope", "z")]
        feats += [xc[idx], (xc[idx] - med[c]) / sd[c],
                  means[15] - means[300], means[60] - means[300]]
        names += [f"{CH[c]}_last", f"{CH[c]}_zlast",
                  f"{CH[c]}_c15_300", f"{CH[c]}_c60_300"]
    return np.stack(feats, 1).astype(np.float32), idx, names


# -- public API ---------------------------------------------------------------

def telemetry_from_schedule(scenario: Scenario, seed: int) -> np.ndarray:
    """Synthesise 6-channel telemetry for the *sim's* failure schedule.

    Logic is copied from predictor_pipeline.gen_run (profile A, N_SATS satellites,
    T_TICKS ticks) with one key change: the failure schedule comes from
    ``scenario.failures`` instead of gen_run's internal RNG draw.  Each scheduled
    failure is overlaid with an EPS-fade ramp (profile A parameters); sudden-mode
    failures (mode != DEAD or no ramp time) get no precursor overlay.

    The run length is capped at T_TICKS for the telemetry array even if the
    scenario is longer; score_run handles a longer scenario by scoring over
    min(T, T_TICKS)-ish ticks and marking out-of-range rows.

    RNG: seeded exactly as gen_run uses:
        np.random.default_rng(np.random.SeedSequence(seed).spawn(1)[0])
    so for a gen_run(seed) call the channel baseline noise matches (the failure
    overlay differs because gen_run draws its own schedule).

    Returns X: np.ndarray shape (N_SATS, T, NC) float32
      where T = min(scenario tick count, T_TICKS).
    """
    n_sats = scenario.n_sats
    T = min(int(round(scenario.duration_s / DT)) + 1, T_TICKS)

    rng = np.random.default_rng(np.random.SeedSequence(seed).spawn(1)[0])

    ecl = _eclipse_box(rng, T)

    # Build failure map: sat_id -> (t_f in ticks, family hint)
    # We treat every scheduled DEAD failure as an EPS-fade with a ramp
    # anchored as far back as profile-A allows (R uniform in [1800,3600] s).
    # The ramp is deterministically seeded per sat so parity tests are stable.
    fmap: dict[int, dict] = {}
    for f in scenario.failures:
        tf_tick = int(round(f.t / DT))
        fmap[f.sat_id] = {"tf": tf_tick, "mode": str(f.mode.value)}

    X = np.zeros((n_sats, T, NC), np.float32)

    for s in range(n_sats):
        x = np.tile(NOM, (T, 1)) + ecl[:, None] * ECL_NOM
        # Per-sat biases and noise (match gen_run order exactly)
        x[:, 0] += rng.normal(0, 0.05)        # per-sat bias volt
        x[:, 5] += rng.normal(0, 1.0)         # per-sat bias temp
        x[:, 0] += rng.normal(0, 0.02, T)     # volt noise
        x[:, 1] += rng.normal(0, 0.3, T)      # soc noise
        x[:, 3] += rng.normal(0, 3, T)        # lat noise
        x[:, 4] += np.abs(rng.normal(0, 1, T))  # jit noise (abs)
        x[:, 5] += rng.normal(0, 0.3, T)      # temp noise
        # Burn pulses
        duty = np.zeros(T)
        for _ in range(rng.integers(2, 8)):
            a = rng.integers(0, T - 30)
            duty[a : a + rng.integers(5, 20)] = rng.uniform(0.3, 0.8)
        x[:, 2] += duty + rng.normal(0, 0.01, T)
        x[:, 5] += 2.0 * _box(duty, 40)
        # Benign self-recovering distractors
        for _ in range(rng.integers(0, 4)):
            a, n_d = rng.integers(0, T - 120), rng.integers(30, 100)
            x[a : a + n_d, 0] -= rng.uniform(0.2, 0.5) * np.hanning(n_d)[: len(x[a : a + n_d])]
            a2, n2 = rng.integers(0, T - 40), rng.integers(10, 30)
            x[a2 : a2 + n2, 3] += rng.uniform(10, 25)
            x[a2 : a2 + n2, 4] += rng.uniform(5, 15)

        # Overlay failure precursors from the *sim's* schedule (not gen_run's RNG)
        if s in fmap:
            info = fmap[s]
            tf = info["tf"]
            # Profile-A ramp: R drawn per-sat with a sub-seed for reproducibility
            sub_rng = np.random.default_rng(
                np.random.SeedSequence(seed * 1000 + s).spawn(1)[0]
            )
            R_ticks = int(sub_rng.uniform(*_PROFILE_A["R"]) / DT)
            on = max(tf - R_ticks, 0)
            i_arr = np.arange(T)
            ramp = np.clip((i_arr - on) / max(tf - on, 1), 0.0, 1.0)
            # EPS-fade overlay (profile A)
            rate = sub_rng.uniform(*_PROFILE_A["rate"]) / 60.0  # V/s
            drop = np.where(i_arr > on, rate * (i_arr - on) * DT, 0.0)
            x[:, 0] = np.maximum(x[:, 0] - drop, 3.0)
            x[:, 1] -= sub_rng.uniform(10, 25) * ramp
            x[:, 5] += sub_rng.uniform(*_PROFILE_A["dtemp"]) * ramp

        X[s] = x.astype(np.float32)

    return X


def score_run(telemetry: np.ndarray) -> list[ScoredRow]:
    """Score one run's telemetry with the frozen LGB model.

    telemetry : (N_SATS, T, NC) float32

    Returns a flat list of ScoredRow in ascending (sat_id, tick) order.
    Past-only: the score at tick t uses only samples <= t (enforced by the
    feature windows in _features_T).

    If T > T_TICKS the rows beyond T_TICKS are marked ood=True (out of the
    pipeline's training range) so callers can exclude / flag them.

    The eclipse vector is synthesised at canonical phase (offset 0) to match
    the detrending used by the pipeline's baseline.  Exact eclipse shape differs
    from the pipeline's random-offset eclipse, but the model removes the eclipse
    via _detrend so any residual mismatch is attenuated.
    """
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    feat_names: list[str] = manifest["feature_names"]

    import lightgbm as lgb  # lazy import; not in the sim path
    booster = lgb.Booster(model_file=str(_MODEL_PATH))

    n_sats, T, _ = telemetry.shape

    # Canonical eclipse: zero phase offset, same box width as gen_run
    t_arr = np.arange(T) * DT
    ecl_raw = ((t_arr % ORBIT_S) > 0.65 * ORBIT_S).astype(float)
    ecl = np.convolve(ecl_raw, np.ones(30) / 30, mode="same")

    rows: list[ScoredRow] = []
    for s in range(n_sats):
        F, idx, names = _features_T(telemetry[s], ecl, T)
        # Reorder columns to match the model's feature_names order
        name_to_col = {name: i for i, name in enumerate(names)}
        col_order = [name_to_col[fn] for fn in feat_names]
        F_ordered = F[:, col_order]
        scores = booster.predict(F_ordered, num_iteration=booster.best_iteration)
        for tick, score in zip(idx, scores, strict=False):
            rows.append(ScoredRow(
                sat_id=s,
                tick=int(tick),
                t_s=float(tick * DT),
                score=float(score),
                ood=bool(tick >= T_TICKS),
            ))
    rows.sort(key=lambda r: (r.sat_id, r.tick))
    return rows


def load_tau() -> float:
    """Return tau_lgb from the committed manifest."""
    return float(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))["tau_lgb"])


def suspect_alerts(
    scored_rows: Sequence[ScoredRow], tau: float | None = None
) -> list[Alert]:
    """Apply the SUSPECT rule: K_ALARM consecutive scored rows >= tau -> Alert.

    The alert fires once at the START of the first K_ALARM-length run.
    After an alert fires for a sat it can fire again only once the run breaks
    and K_ALARM new consecutive rows accumulate (mimics the pipeline's active_flags).

    tau: if None, loaded from models/predictor_manifest.json.
    """
    if tau is None:
        tau = load_tau()

    # Group by sat_id preserving ascending tick order
    sat_rows: dict[int, list[ScoredRow]] = {}
    for row in scored_rows:
        sat_rows.setdefault(row.sat_id, []).append(row)

    alerts: list[Alert] = []
    for sat_id, sat_r in sorted(sat_rows.items()):
        scores_arr = np.array([r.score for r in sat_r])
        above = (scores_arr >= tau).astype(int)
        # Sliding sum (K_ALARM window) using convolution, same as pipeline active_flags
        c = np.convolve(above, np.ones(K_ALARM, dtype=int), mode="full")[: len(above)]
        active = c >= K_ALARM
        # Rising edges of active (False -> True transitions)
        edges = active & ~np.concatenate(([False], active[:-1]))
        for idx in np.flatnonzero(edges):
            # The alert tick is the FIRST tick of the K_ALARM run.
            start_idx = max(idx - K_ALARM + 1, 0)
            row = sat_r[start_idx]
            alerts.append(Alert(
                sat_id=sat_id,
                tick=row.tick,
                t_s=row.t_s,
                score=row.score,
            ))
    alerts.sort(key=lambda a: (a.sat_id, a.tick))
    return alerts
