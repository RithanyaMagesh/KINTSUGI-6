"""C5 pre-registered comms benchmark (`benchmark --mode comms`; hypotheses in GATES.md 2026-11-01).

Matrix: cells (comms model x topology x authority) x kill sets (the 15 DEAD pairs of the base
at 1200 s / 1500 s, plus the leader alone at 1200 s), engine v2, the base's full duration.
Metrics come from the in-memory log lines; every one is defined in `run_metrics`. A cell the
engine cannot run yet (decentral before C4) is reported "unmeasured", never estimated.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

from cubesat import geo_v2
from cubesat.scenario import Scenario

FAIL_TIMES = (1200.0, 1500.0)
_DEC = {"recovery": {"authority": "decentral"}}
CELLS = [
    {"name": "ideal-central", "update": {}},
    {"name": "laser-mesh-central", "update": {"comms": {"model": "laser", "topology": "mesh"}}},
    {"name": "laser-star-central", "update": {"comms": {"model": "laser", "topology": "star"}}},
    {"name": "laser-mesh-decentral",
     "update": {"comms": {"model": "laser", "topology": "mesh"}, **_DEC}},
    {"name": "laser-star-decentral",
     "update": {"comms": {"model": "laser", "topology": "star"}, **_DEC}},
]
NA_CELLS = [
    {"name": "ideal-decentral", "why": "the scenario refuses decentral authority without laser "
     "comms: an auction over ideal, instant links has no topology to decentralise over"},
    {"name": "ideal-mesh/ideal-star", "why": "ideal comms has no links, so topology is not read; "
     "ideal-central is the single ideal cell"},
]
_DEAD = ("DEAD", "REENTERED")


def kill_sets(n_sats: int, leader: int = 0) -> list[tuple[int, ...]]:
    return [*itertools.combinations(range(n_sats), 2), (leader,)]


def _scenario(base: dict, cell: dict, kills: tuple[int, ...]) -> Scenario:
    unknown = [k for k in cell["update"] if k not in Scenario.model_fields]
    if unknown:  # pydantic ignores unknown keys: a decentral cell would silently run central
        raise ValueError(f"scenario has no field {unknown} (needs C4)")
    fails = [{"t": t, "sat_id": s, "mode": "DEAD"} for s, t in zip(kills, FAIL_TIMES, strict=False)]
    name = f"comms_{cell['name']}_{'-'.join(map(str, kills))}"
    return Scenario.model_validate({**base, "engine": "v2", "name": name, "failures": fails,
                                    **cell["update"]})


def _held(sat: dict) -> list:
    return sat["roles"] if "roles" in sat else [sat["role"]]


def _crit_held(line: dict) -> bool:
    """Leader and downlink on NOMINAL sats (benchmark.metrics_from_log rule). Decentral logs
    (a `functions_vacant` key): the leader counts as held iff no leader function is vacant."""
    nominal = {r for s in line["sats"] if s["status"] == "NOMINAL" for r in _held(s)}
    leader = not line["functions_vacant"] if "functions_vacant" in line else "leader" in nominal
    return leader and "downlink" in nominal


def run_metrics(lines, *, killed, first_failure_t, period_s, dt) -> dict:
    ticks = [x for x in lines if "sats" in x]
    laser = any("components" in x for x in ticks)
    decentral = any("functions_vacant" in x for x in ticks)
    lat, false_iso, iso_s, part_s, locked, rows = [], 0, 0.0, 0.0, 0, 0
    for x in ticks:
        for e in x.get("events") or ([x["event"]] if x.get("event") else []):
            p = e.get("payload") or {}
            if e.get("type") != "FAILURE_DETECTED":
                continue
            if p.get("cause") == "isolated":
                false_iso += p.get("sat_id") not in killed
            elif p.get("sat_id") in killed:
                lat.append(p["t_detect"] - p["t_fail"])
        if laser:
            comps = x.get("components", [])
            part_s += dt * (len(comps) > 1)
            iso_s += dt * sum(1 for c in comps if len(c) == 1 and c[0] not in killed)
            rows += len(x.get("links", []))
            locked += sum(1 for r in x.get("links", []) if r[2] == "LOCKED")
    post = [x for x in ticks if x["t"] >= first_failure_t - 1e-9]
    orbits = len(ticks) * dt / period_s
    summary = next((x for x in lines if x.get("state") == "SUMMARY"), {})
    return {
        "detection_latency_s": sum(lat) / len(lat) if lat else None,
        "false_isolations": false_iso,
        "isolated_sat_s": iso_s if laser else None,
        "partition_s": part_s if laser else None,
        "partition_s_per_orbit": part_s / orbits if laser else None,
        "locked_frac": locked / rows if laser and rows else None,
        "critical_vacancy_s": dt * sum(1 for x in post if not _crit_held(x)),
        "function_vacancy_s": dt * sum(1 for x in post if x.get("functions_vacant"))
        if decentral else None,
        "split_brain_s": dt * sum(1 for x in post if x.get("split_brain")) if decentral else None,
        "coverage_mean_last_orbit": summary.get("coverage_mean_last_orbit"),
    }


def _by(rows, cell):
    return {tuple(r["killed"]): r for r in rows if r["cell"] == cell and "error" not in r}


def _count(pred, keys, *cells) -> int | None:
    """Kill sets in `keys` where pred holds; None when any cell lacks a kill set (not run).
    A None metric (e.g. no detection) fails the condition rather than raising."""
    if not keys or any(k not in c for c in cells for k in keys):
        return None
    hits = 0
    for k in keys:
        try:
            hits += bool(pred(*(c[k] for c in cells)))
        except TypeError:
            pass
    return hits


def _mean(cell, keys, metric) -> float | None:
    vals = [cell[k][metric] for k in keys if k in cell]
    return sum(vals) / len(vals) if keys and len(vals) == len(keys) and None not in vals else None


def _verdict(value, ok, threshold: str) -> dict:
    v = "unmeasured" if value is None else ("PASS" if ok(value) else "FAIL")
    return {"verdict": v, "value": value, "threshold": threshold}


def verdicts(rows: list[dict]) -> dict:
    """Each hypothesis against its pre-registered threshold (GATES.md; never edited after)."""
    ideal, mesh, star, dmesh, dstar = (_by(rows, c["name"]) for c in CELLS)
    ks = kill_sets(6)
    lk = [k for k in ks if 0 in k]
    lat = "detection_latency_s"
    vac = "critical_vacancy_s"
    return {
        "C5-H1": _verdict(_count(lambda m, i: abs(m[lat] - i[lat]) <= 2.0, ks, mesh, ideal),
                          lambda n: n == 16, "16/16 kill sets |mesh - ideal| <= 2 s"),
        "C5-H2": _verdict(_count(lambda m: m["false_isolations"] == 0, ks, mesh),
                          lambda n: n >= 15, ">= 15/16 kill sets with 0"),
        "C5-H3": _verdict(_count(lambda s: s["false_isolations"] >= 1, lk, star),
                          lambda n: n == 6, "6/6 leader kills with >= 1"),
        "C5-H4": _verdict(_mean(mesh, ks, "partition_s_per_orbit"), lambda m: m <= 400.0,
                          "mean <= 400 s/orbit"),
        "C5-H5": _verdict(_count(lambda m, i: m[vac] <= i[vac] + 2.0, ks, mesh, ideal),
                          lambda n: n == 16, "16/16 mesh <= ideal + 2 s"),
        "C5-H6": _verdict(_mean(mesh, ks, "locked_frac"), lambda m: m >= 0.95, "mean >= 0.95"),
        "C5-H7": _verdict(_count(lambda d: d["split_brain_s"] == 0, ks, dmesh),
                          lambda n: n >= 15, ">= 15/16 kill sets with 0 s"),
        "C5-H8": _verdict(_count(lambda d: d["split_brain_s"] > 0, lk, dstar),
                          lambda n: n == 6, "6/6 leader kills with > 0 s"),
        "C5-H9": _verdict(_count(lambda d, m: d[vac] <= m[vac], lk, dmesh, mesh),
                          lambda n: n >= 5, ">= 5/6 leader kills decentral <= central"),
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, command: str) -> int:
    from cubesat.sim_v2 import run_scenario_v2

    base = json.loads(args.base.read_text(encoding="utf-8"))
    probe = _scenario(base, CELLS[0], ())
    period, dt = geo_v2.chief_period_s(probe), probe.dt_s
    rows = []
    for cell in CELLS:
        for kills in kill_sets(probe.n_sats):
            row = {"cell": cell["name"], "killed": list(kills)}
            try:
                scn = _scenario(base, cell, kills)
            except ValueError as exc:  # pydantic: field unknown before C4
                rows.append({**row, "error": f"unmeasured: {str(exc).splitlines()[0]}"})
                continue
            m = run_metrics(run_scenario_v2(scn), killed=list(kills),
                            first_failure_t=FAIL_TIMES[0], period_s=period, dt=dt)
            rows.append({**row, **m})
            print(row["cell"], kills, m["critical_vacancy_s"], flush=True)
    src = Path(__file__).resolve().parent
    report = {
        "command": command,
        "preregistration": "GATES.md, 2026-11-01 C5 pre-registration",
        "inputs_sha256": {str(args.base): _sha(args.base),
                          **{f"cubesat/{f}": _sha(src / f) for f in
                             ("comms_bench.py", "comms_v2.py", "isl.py", "faults_v2.py",
                              "sim_v2.py")}},
        "period_s": period, "dt_s": dt, "failure_times_s": list(FAIL_TIMES),
        "cells": [c["name"] for c in CELLS], "na_cells": NA_CELLS,
        "verdicts": verdicts(rows), "rows": rows,
    }
    text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
    args.report.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(report["verdicts"], indent=1))
    return 0
