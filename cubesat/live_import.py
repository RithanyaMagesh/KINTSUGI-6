"""Live CubeSat orbital data ingestion, relative astrodynamics, and formation fitting."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from cubesat._live_network import (
    CacheManager,
    build_celestrak_url,
    download_stream,
    sanitize_url,
)
from cubesat.hcw import MU, R_EARTH, mean_motion, slot_initial_state
from cubesat.scenario import Scenario

J2, D2R = 1.08262668e-3, math.pi / 180.0
PROTECTED_DIRS = frozenset({"cubesat", "tests", ".git", "docs", ".agents", ".zcode"})
PROTECTED_FILES = frozenset({"pyproject.toml", "uv.lock", "agents.md", "readme.md", "gates.md"})
_GAINS = {"wn": 0.01, "zeta": 1.0}
_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 2.0, "grid_extent_km": 30.0}
_ALLOC = {
    "w1": 1.0, "w2": 0.5, "w3": 2.0, "min_sep_km": 2.0, "dv_budget_mps": 200.0,
    "amp_sweep": [1.0], "phase_sweep_deg": [30.0 * k for k in range(12)], "method": "hungarian",
}


def _confine_output_path(parser: argparse.ArgumentParser, label: str, path: str, rr: Path) -> Path:
    resolved = (rr / Path(path)).resolve()
    norm_repo, norm_tgt = os.path.normcase(str(rr)), os.path.normcase(str(resolved))
    try:
        if os.path.normcase(os.path.commonpath([norm_tgt, norm_repo])) != norm_repo:
            parser.error(f"refusing: {label} {str(path)!r} resolves outside repo {rr}")
    except ValueError:
        parser.error(f"refusing: {label} {str(path)!r} cross-drive path escapes {rr}")
    parts = resolved.relative_to(rr).parts
    if not parts or parts[0].lower() in PROTECTED_DIRS or resolved.name.lower() in PROTECTED_FILES:
        parser.error(f"refusing: {label} cannot target protected directory/file: {path}")
    if label in ("--out", "--meta-out") and resolved.suffix.lower() != ".json":
        parser.error(f"refusing: {label} must have .json extension, got: {resolved.suffix}")
    return resolved


def _num(x: Any) -> float:
    val = float(str(x))
    if not math.isfinite(val):
        raise ValueError(f"Non-finite orbital element numeric: {x}")
    return val


def parse_omm_records(records: list[dict]) -> list[dict]:
    parsed = []
    for rec in records:
        n = _num(rec["MEAN_MOTION"]) * 2.0 * math.pi / 86400.0
        a = (MU / (n * n)) ** (1.0 / 3.0)
        e, alt_km = _num(rec["ECCENTRICITY"]), (a - R_EARTH) / 1000.0
        if not (0.0 <= e < 1.0) or not (160.0 < alt_km < 2000.0):
            raise ValueError(f"Eccentricity {e} or altitude {alt_km:.3f} km out of bounds")
        ep = datetime.fromisoformat(str(rec["EPOCH"])).replace(tzinfo=UTC)
        parsed.append({
            "name": str(rec.get("OBJECT_NAME", "UNKNOWN")),
            "norad": int(_num(rec.get("NORAD_CAT_ID", 0))),
            "epoch_s": ep.timestamp(), "epoch_iso": ep.isoformat(),
            "n": n, "a": a, "e": e, "alt_km": alt_km,
            "i": _num(rec["INCLINATION"]) * D2R, "raan": _num(rec["RA_OF_ASC_NODE"]) * D2R,
            "argp": _num(rec["ARG_OF_PERICENTER"]) * D2R, "M": _num(rec["MEAN_ANOMALY"]) * D2R,
        })
    if len(parsed) < 1:
        raise ValueError("Empty or invalid OMM record set")
    return parsed


def advance_brouwer_j2(elements: list[dict]) -> tuple[list[dict], float]:
    med_t, adv = float(np.median([el["epoch_s"] for el in elements])), []
    for el in elements:
        dt, p = med_t - el["epoch_s"], el["a"] * (1.0 - el["e"] ** 2)
        f, ci = 1.5 * J2 * (R_EARTH / p) ** 2, math.cos(el["i"])
        d_raan, d_argp = -f * el["n"] * ci, 0.5 * f * el["n"] * (5.0 * ci * ci - 1.0)
        d_m = el["n"] * (1.0 + 0.5 * f * math.sqrt(1.0 - el["e"] ** 2) * (3.0 * ci * ci - 1.0))
        adv.append({
            **el, "raan": (el["raan"] + d_raan * dt) % (2.0 * math.pi),
            "argp": (el["argp"] + d_argp * dt) % (2.0 * math.pi),
            "M": (el["M"] + d_m * dt) % (2.0 * math.pi), "delta_epoch_s": dt,
        })
    return adv, med_t


def solve_kepler(M: float, e: float) -> float:
    if not math.isfinite(M) or not (0.0 <= e < 1.0):
        raise ValueError("Kepler solver non-finite M or invalid e")
    E = M
    for _ in range(50):
        denom = 1.0 - e * math.cos(E)
        if abs(denom) < 1e-12:
            raise ValueError("Near-singular derivative in Kepler solver")
        step = (E - e * math.sin(E) - M) / denom
        E -= step
        if abs(step) < 1e-14:
            return E
    raise ValueError("Kepler solver failed to converge within 50 iterations")


def keplerian_to_eci(el: dict) -> tuple[np.ndarray, np.ndarray]:
    E = solve_kepler(el["M"], el["e"])
    nu = 2.0 * math.atan2(
        math.sqrt(1.0 + el["e"]) * math.sin(E / 2.0),
        math.sqrt(1.0 - el["e"]) * math.cos(E / 2.0),
    )
    p = el["a"] * (1.0 - el["e"] ** 2)
    r, sq = p / (1.0 + el["e"] * math.cos(nu)), math.sqrt(MU / p)
    r_pf = np.array([r * math.cos(nu), r * math.sin(nu), 0.0])
    v_pf = np.array([-sq * math.sin(nu), sq * (el["e"] + math.cos(nu)), 0.0])
    co, so, ci, si, cw, sw = (
        math.cos(el["raan"]), math.sin(el["raan"]), math.cos(el["i"]), math.sin(el["i"]),
        math.cos(el["argp"]), math.sin(el["argp"]),
    )
    R = np.array([
        [co * cw - so * ci * sw, -co * sw - so * ci * cw, so * si],
        [so * cw + co * ci * sw, -so * sw + co * ci * cw, -co * si],
        [si * sw, si * cw, ci],
    ])
    return R @ r_pf, R @ v_pf


def fit_passive_ellipse(lvlh: np.ndarray) -> tuple[float, float]:
    if len(lvlh) == 2:
        dx, dy = (lvlh[1] - lvlh[0])[:2]
        return math.hypot(dx / 2.0, dy / 4.0), math.atan2(dy / 4.0, -dx / 2.0) % (2.0 * math.pi)
    xi, eta = lvlh[:, 0] - np.mean(lvlh[:, 0]), -(lvlh[:, 1] - np.mean(lvlh[:, 1])) / 2.0
    phases = np.arctan2(eta, xi) % (2.0 * math.pi)
    order = np.argsort(phases)
    th = np.linspace(0, 2.0 * math.pi, len(lvlh), endpoint=False)
    C = float(np.mean(xi[order] * np.cos(th) + eta[order] * np.sin(th)))
    S = float(np.mean(-xi[order] * np.sin(th) + eta[order] * np.cos(th)))
    return math.hypot(C, S), math.atan2(S, C) % (2.0 * math.pi)


def build_scenario_payload(
    chief: dict, elements: list[dict], lvlh_pos: np.ndarray,
    n_swarm: int, n_failures: int, amp_m: float, psi_0: float,
    seed: int = 42, duration: float | None = None, dt: float = 2.0,
) -> tuple[dict, dict]:
    alt_km = round(chief["alt_km"], 3)
    n0 = mean_motion(alt_km * 1000.0)
    dur = duration if duration is not None else (3.0 * 2.0 * math.pi / n0)
    psi_deg, amp_km = round(math.degrees(psi_0) % 360.0, 3), round(amp_m / 1000.0, 4)
    form = {"n_slots": n_swarm, "radial_amp_km": amp_km, "phase_offset_deg": psi_deg}
    fails = [{"t": 1200.0 + 300 * j, "sat_id": 1 + j, "mode": "DEAD"} for j in range(n_failures)]
    scen = {
        "name": f"live-swarm-{chief['name'].replace(' ', '-')}",
        "seed": seed, "duration_s": dur, "dt_s": dt,
        "chief": {"altitude_km": alt_km}, "formation": form,
        "a_max_mps2": 0.1, "gains": dict(_GAINS), "sensor": dict(_SENSOR),
        "roles": ["leader"] + ["imager"] * (n_swarm - 2) + ["downlink"],
        "failures": fails, "recovery_enabled": True, "detection": {"missed_ticks_k": 3},
        "allocation": dict(_ALLOC),
    }
    slots = [
        slot_initial_state(amp_m, amp_m, psi_0 + 2.0 * math.pi * j / n_swarm, n0)
        for j in range(n_swarm)
    ]
    cost = np.array([[
        np.linalg.norm(p - s[:3]) + 1e-9 * (i * n_swarm + j) for j, s in enumerate(slots)
    ] for i, p in enumerate(lvlh_pos)])
    r_ind, c_ind = linear_sum_assignment(cost)
    resids = [float(np.linalg.norm(lvlh_pos[r] - slots[c][:3]))
              for r, c in zip(r_ind, c_ind, strict=True)]
    members = [{
        "name": el["name"], "norad_cat_id": el["norad"], "epoch_iso": el["epoch_iso"],
        "delta_epoch_s": round(el.get("delta_epoch_s", 0.0), 3),
        "raw_lvlh_pos_m": [round(float(c), 3) for c in lvlh_pos[i]],
    } for i, el in enumerate(elements)]
    da = elements[-1]["a"] - chief["a"]
    drift = abs(-1.5 * n0 * da) * 86400.0 / 1000.0 if len(elements) > 1 else 0.0
    ct_m = abs(lvlh_pos[-1][2] - lvlh_pos[0][2]) if len(elements) > 1 else 0.0
    rms_pos = round(float(np.sqrt(np.mean(np.square(resids)))), 3)
    meta = {
        "chief": {
            "name": chief["name"], "norad_cat_id": chief["norad"], "altitude_km": alt_km,
            "eccentricity": chief["e"], "mean_motion_rad_s": n0, "epoch_iso": chief["epoch_iso"],
        },
        "cluster_members": members,
        "formation_fit": {
            "fit_mode": "fit-ellipse", "radial_amp_km": amp_km, "phase_offset_deg": psi_deg,
            "rms_pos_m": rms_pos, "rms_vel_mps": 0.0, "max_pos_residual_m": round(max(resids), 3),
            "secular_drift_km_per_day": round(drift, 4), "cross_track_mismatch_m": round(ct_m, 3),
        },
        "fidelity_and_honesty": {
            "model_type": "hypothetical-swarm-on-real-chief-orbit",
            "formation_scale": f"{amp_km} km fitted passive ellipse",
            "linearization_validity": "VALID" if amp_m <= 10000.0 else "CW_INVALID_LARGE_BASELINE",
            "notes": "Sim utilizes drift-free HCW passive ellipse on fitted chief orbit.",
        },
    }
    return scen, meta


def fetch_and_parse(
    args: argparse.Namespace, mgr: CacheManager
) -> tuple[list[dict], str, str, bool]:
    q = args.cluster or args.name or ({"CATNR": args.catnr} if args.catnr else "GRACE-FO")
    qd = {"NAME": q, "FORMAT": "JSON"} if isinstance(q, str) else {**q, "FORMAT": "JSON"}
    url = build_celestrak_url(qd)
    sanitized = sanitize_url(url)
    cache_path = mgr.get_cache_path("celestrak", sanitized)
    if not args.force_refresh and (args.offline or mgr.is_valid(cache_path)):
        if cache_path.is_file() and not cache_path.is_symlink():
            recs, ft = mgr.read(cache_path)
            return recs, sanitized, ft, True
        if args.offline:
            fix_p = mgr.cache_dir / f"{str(q).lower().replace('-', '')}_omm.json"
            if fix_p.is_file() and not fix_p.is_symlink():
                recs, ft = mgr.read(fix_p)
                return recs, sanitized, ft, True
            raise FileNotFoundError(f"Offline cache missing for: {sanitized}")
    raw = download_stream(url)
    recs = json.loads(raw.decode("utf-8"))
    recs = [recs] if isinstance(recs, dict) else recs
    ft = datetime.now(UTC).isoformat()
    mgr.write_atomic(cache_path, recs, ft)
    return recs, sanitized, ft, False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live CubeSat Swarm Ingestion Pipeline")
    for f, d, t, c in [
        ("--cluster", None, str, None), ("--name", None, str, None), ("--catnr", None, str, None),
        ("--cache-dir", "data/celestrak", str, None), ("--ttl", 86400, int, None),
        ("--fit-mode", "fit-ellipse", str, ["fit-ellipse", "safe-envelope"]),
        ("--n-sats", None, int, None), ("--n-failures", 2, int, None), ("--seed", 42, int, None),
        ("--duration", None, float, None), ("--dt", 2.0, float, None),
        ("--out", "data/scenarios/live_swarm.json", str, None), ("--meta-out", None, str, None),
    ]:
        parser.add_argument(f, default=d, type=t, **({"choices": c} if c else {}))
    for f in ("--offline", "--force-refresh"):
        parser.add_argument(f, action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    out_p = _confine_output_path(parser, "--out", args.out, root)
    tgt = args.meta_out or out_p.with_suffix(".meta.json")
    meta_p = _confine_output_path(parser, "--meta-out", tgt, root)
    cache_dir = _confine_output_path(parser, "--cache-dir", args.cache_dir, root)
    cache_mgr = CacheManager(cache_dir, ttl_s=args.ttl)
    try:
        raw_recs, url, ft, hit = fetch_and_parse(args, cache_mgr)
        elements = parse_omm_records(raw_recs)
        adv_elements, _ = advance_brouwer_j2(elements)
        rc, vc = keplerian_to_eci(adv_elements[0])
        xh, zh = rc / np.linalg.norm(rc), np.cross(rc, vc) / np.linalg.norm(np.cross(rc, vc))
        yh = np.cross(zh, xh)
        lvlh = np.array([
            [float(np.dot(r - rc, ax)) for ax in (xh, yh, zh)]
            for r, _ in (keplerian_to_eci(el) for el in adv_elements)
        ])
        amp, psi0 = (8000.0, 0.0) if args.fit_mode == "safe-envelope" else fit_passive_ellipse(lvlh)
        n_sw = args.n_sats or (6 if len(elements) < 4 else len(elements))
        scen, meta = build_scenario_payload(
            adv_elements[0], adv_elements, lvlh, n_sw, args.n_failures, amp, psi0,
            args.seed, args.duration, args.dt,
        )
        q_label = args.cluster or args.name or args.catnr or "GRACE-FO"
        meta.update({
            "provider": "celestrak", "query": q_label,
            "url": url, "fetch_time_utc": ft, "cache_hit": hit,
        })
        Scenario.model_validate(scen)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        for p, d in ((out_p, scen), (meta_p, meta)):
            p.write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Scenario successfully written: {out_p}")
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
