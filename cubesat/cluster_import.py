"""OMM JSON -> hypothetical-swarm scenario (CelesTrak import).

No SGP4: a hypothetical swarm flying formation on the chief's orbit needs only
the chief's mean motion (-> altitude) and a near-circularity gate, not
propagation -- the relative-motion core (cubesat.hcw) takes only the mean
motion n, and the chief's eccentricity never enters the sim. The eccentricity
gate exists so the honest label 'hypothetical swarm on <chief> real orbit'
stays true: a scenario generated from an eccentric chief would silently claim
a circular orbit it does not fly.

Snapshot provenance: data/celestrak/firefly_omm.json was fetched from
https://celestrak.org/NORAD/elements/gp.php?NAME=FIREFLY&FORMAT=JSON on
2026-09-28 (5 records: FIREFLY ALPHA R/B x2, FIREFLY-1/2/3).

CLI (writes a schema-valid scenario JSON for cubesat.run):

    uv run python -m cubesat.cluster_import --omm data/celestrak/firefly_omm.json \
        --index 1 --n-sats 6 --n-failures 2 --out data/scenarios/firefly_swarm.json

No wall clock, no RNG, no order-dependent iteration (AGENTS.md invariant 2);
stdlib only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from copy import deepcopy
from pathlib import Path

from cubesat.hcw import MU, R_EARTH, mean_motion

_ECC_GATE = 1e-3  # near-circular chief gate (see module docstring)
_ALT_MIN_KM, _ALT_MAX_KM = 160.0, 2000.0  # mirrors ChiefOrbit in cubesat.scenario
_REQUIRED_FIELDS = ("OBJECT_NAME", "NORAD_CAT_ID", "MEAN_MOTION", "ECCENTRICITY")


def _confine_output_path(
    parser: argparse.ArgumentParser, label: str, path: Path
) -> None:
    """Path-confinement guard, copied from cubesat/benchmark.py:366 (Mimosa
    finding: the guard shipped there only). The CLI-provided output path must
    resolve inside the repository (this file's parents[1]) before any write
    uses it. Refusal is a clean argparse error (usage + message on stderr,
    exit 2); nothing is read or written. Duplicated rather than imported so
    this module stays stdlib-only (see its module docstring)."""
    repo_root = Path(__file__).resolve().parents[1]
    try:
        resolved = Path(path).resolve()
        confined = (
            os.path.commonpath((str(resolved), str(repo_root))) == str(repo_root)
        )
    except ValueError:  # different drives on Windows
        confined = False
    if not confined:
        parser.error(
            f"refusing: {label} {str(path)!r} resolves outside the repository {repo_root}"
        )

# Reference blocks copied verbatim from data/scenarios/two_failure.json
# (the tuned G4 scenario); the generated swarm must behave like it.
_GAINS = {"wn": 0.01, "zeta": 1.0}
_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 2.0, "grid_extent_km": 30.0}
_ALLOCATION = {
    "w1": 1.0,
    "w2": 0.5,
    "w3": 2.0,
    "min_sep_km": 2.0,
    "dv_budget_mps": 200.0,
    "amp_sweep": [1.0],
    "phase_sweep_deg": [
        0.0, 30.0, 60.0, 90.0, 120.0, 150.0,
        180.0, 210.0, 240.0, 270.0, 300.0, 330.0,
    ],
    "method": "hungarian",
}


def _num(x) -> float:
    """float(str(x)): absorbs Space-Track string-typed numerics and CelesTrak numbers."""
    return float(str(x))


def _chief_raw(record: dict) -> dict:
    """Parse one OMM record into the chief dict, WITHOUT the circularity gates.

    n = MEAN_MOTION * 2*pi / 86400 (revs per solar day -> rad/s, sgp4
    convention); a = (MU/n^2)^(1/3); altitude_km = (a - R_EARTH)/1000.
    Malformed input (non-object or missing a required field) raises ValueError,
    never KeyError, so it reaches the CLI's clean-rejection path and the record
    picker instead of crashing with a traceback (both call _chief_raw).
    """
    if not isinstance(record, dict):
        raise ValueError(
            f"malformed OMM record: expected a JSON object, got {type(record).__name__}"
        )
    missing = [field for field in _REQUIRED_FIELDS if field not in record]
    if missing:
        raise ValueError("malformed OMM record: missing required field(s) " + ", ".join(missing))
    n = _num(record["MEAN_MOTION"]) * 2.0 * math.pi / 86400.0
    a = (MU / n**2) ** (1.0 / 3.0)
    return {
        "name": str(record["OBJECT_NAME"]),
        "norad_cat_id": int(_num(record["NORAD_CAT_ID"])),
        "mean_motion_rad_s": n,
        "altitude_km": (a - R_EARTH) / 1000.0,
        "eccentricity": _num(record["ECCENTRICITY"]),
    }


def chief_from_omm(record: dict) -> dict:
    """Chief orbit {name, norad_cat_id, mean_motion_rad_s, altitude_km,
    eccentricity} from one OMM record; ValueError for a malformed record or
    past the circularity gates."""
    chief = _chief_raw(record)
    if chief["eccentricity"] > _ECC_GATE:
        raise ValueError(
            f"eccentricity gate failed: e={chief['eccentricity']} > {_ECC_GATE} for "
            f"{chief['name']} (NORAD {chief['norad_cat_id']}); a hypothetical swarm "
            f"needs a near-circular chief (see module docstring)"
        )
    if not _ALT_MIN_KM < chief["altitude_km"] < _ALT_MAX_KM:
        raise ValueError(
            f"altitude gate failed: altitude_km={chief['altitude_km']:.3f} outside "
            f"({_ALT_MIN_KM}, {_ALT_MAX_KM}) for {chief['name']} "
            f"(NORAD {chief['norad_cat_id']}); mirrors the scenario schema bound"
        )
    return chief


def build_swarm_scenario(chief: dict, *, n_sats: int = 6, n_failures: int = 2) -> dict:
    """Schema-valid scenario dict: a hypothetical swarm on the chief's orbit.

    Guards keep the survivor minimum (leader + at least one imager + the
    downlink must survive n_failures DEAD fires). The altitude is rounded to
    3 decimals and n recomputed from the ROUNDED altitude via
    cubesat.hcw.mean_motion, so the file is self-consistent with the sim (the
    sim derives n from chief.altitude_km, not from the OMM mean motion).
    """
    if n_sats < 4:
        raise ValueError(f"n_sats={n_sats} < 4: cannot field leader + imager + downlink")
    if not 1 <= n_failures <= n_sats - 3:
        raise ValueError(
            f"n_failures={n_failures} outside 1..{n_sats - 3} for n_sats={n_sats}: "
            f"leader + at least one imager + the downlink must survive"
        )
    altitude_km = round(chief["altitude_km"], 3)
    # Rounding can cross a bound the raw value passed chief_from_omm's gate.
    if not _ALT_MIN_KM < altitude_km < _ALT_MAX_KM:
        raise ValueError(
            f"rounded altitude_km={altitude_km} outside ({_ALT_MIN_KM}, {_ALT_MAX_KM}) "
            f"for {chief['name']}"
        )
    n = mean_motion(altitude_km * 1000.0)
    return {
        "name": "hypothetical-swarm-on-" + chief["name"].replace(" ", "-"),
        "seed": 42,
        # Exactly 3 orbits of the (rounded) chief orbit.
        "duration_s": 3.0 * 2.0 * math.pi / n,
        "dt_s": 2.0,
        "chief": {"altitude_km": altitude_km},
        "formation": {"n_slots": n_sats, "radial_amp_km": 8.0, "phase_offset_deg": 0.0},
        "a_max_mps2": 0.1,
        "gains": deepcopy(_GAINS),
        "sensor": deepcopy(_SENSOR),
        "roles": ["leader"] + ["imager"] * (n_sats - 2) + ["downlink"],
        # ids 1..n_failures DEAD at 1200 s + 300 s stagger (two_failure pattern).
        "failures": [
            {"t": 1200.0 + 300.0 * j, "sat_id": 1 + j, "mode": "DEAD"}
            for j in range(n_failures)
        ],
        "recovery_enabled": True,
        "detection": {"missed_ticks_k": 3},
        "allocation": deepcopy(_ALLOCATION),
    }


def load_omm_records(path: Path | str) -> list[dict]:
    """Read an OMM snapshot: a single JSON object becomes a 1-record list; a
    list must contain only objects; anything else is a ValueError."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list) and all(isinstance(record, dict) for record in data):
        return data
    raise ValueError(f"{path}: expected an OMM JSON object or a list of objects")


def _record_line(index: int, record: dict) -> str:
    """One picker line for a record, computed WITHOUT the gates so even a
    rejected record shows its altitude and eccentricity; a malformed record
    shows why it is unparseable instead of crashing the picker."""
    try:
        raw = _chief_raw(record)
    except ValueError as exc:
        return f"[{index}] <unparseable OMM record: {exc}>"
    return (
        f"[{index}] {raw['name']} / NORAD {raw['norad_cat_id']} / "
        f"altitude_km {raw['altitude_km']:.3f} / eccentricity {raw['eccentricity']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cubesat.cluster_import", description="OMM JSON -> swarm scenario JSON"
    )
    parser.add_argument("--omm", required=True, type=Path, help="path to the OMM JSON snapshot")
    parser.add_argument("--index", type=int, default=0, help="record index to use as chief")
    parser.add_argument("--n-sats", type=int, default=6, help="swarm size (>= 4)")
    parser.add_argument("--n-failures", type=int, default=2, help="DEAD failures (1..n_sats-3)")
    parser.add_argument("--out", required=True, type=Path, help="path for the scenario JSON")
    args = parser.parse_args(argv)
    # Path-confinement guard (mirrors cubesat/benchmark.py, Mimosa finding:
    # command-line parameter -> path traversal): --out must resolve inside the
    # repository before anything is read.
    _confine_output_path(parser, "--out", args.out)

    try:
        records = load_omm_records(args.omm)
    except ValueError as exc:
        # Structurally invalid snapshot: nothing to pick an index from.
        print(f"invalid OMM snapshot: {exc}", file=sys.stderr)
        return 2
    if not 0 <= args.index < len(records):
        print(f"--index {args.index} out of range: {len(records)} records", file=sys.stderr)
        for i, record in enumerate(records):
            print(_record_line(i, record), file=sys.stderr)
        return 2
    try:
        chief = chief_from_omm(records[args.index])
        scenario = build_swarm_scenario(chief, n_sats=args.n_sats, n_failures=args.n_failures)
    except ValueError as exc:
        print(f"record [{args.index}] rejected: {exc}", file=sys.stderr)
        print("all records in the snapshot (pick another --index):", file=sys.stderr)
        for i, record in enumerate(records):
            print(_record_line(i, record), file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(scenario, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"chief {chief['name']} (NORAD {chief['norad_cat_id']}): "
        f"altitude {chief['altitude_km']:.3f} km, e {chief['eccentricity']:.4e}, "
        f"n {chief['mean_motion_rad_s']:.6f} rad/s"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
