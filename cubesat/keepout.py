"""P2 dead-satellite drift keep-out report (docs/ENDGAME_PLAN.md section 5).

PURE POST-HOC LOG ANALYSIS -- this module must not import cubesat.sim or the
benchmark driver (asserted by tests/test_keepout.py in a fresh interpreter).
It consumes written JSONL log bytes, the logged r/v at each dead satellite's
DEAD-flip tick (the sim coasts dead sats ballistically from exactly that state,
sim.py:130-139 and 307-308), hcw.propagate and mean_motion -- nothing else.

Per dead satellite (ENDGAME_PLAN 5a/5b):
  - run-window min survivor-to-dead clearance from the ACTUAL logged
    trajectories, ticks t >= t_death (extends G4's reconfig-window-only 3095.1 m);
  - drift-horizon clearance: the dead sat is propagated 3 orbits with
    hcw.propagate (601 samples) from its death state; survivors are read from
    the log inside the logged overlap and propagated (labeled counterfactual)
    past log end. Effective horizon = min(log_end, t_death + 3 orbits) --
    the horizon-honesty rule: anything past log end is counterfactual.
  - the CW secular along-track drift rate -(6 n x + 3 v_y) from the death
    state (drift-free condition v_y = -2 n x, MASTER_PROMPT section 2.2).

Section 5(c): the min clearance with vs without the policy-5 exclusion decides
whether the 2 km keep-out is ever binding -> KEEP or CUT, recorded verbatim
with the measured numbers (AGENTS.md invariant 1).

Physics caveat (research patch #5, GATES.md:27): boundedness holds
linear/unperturbed only; J2/drag would drift dead sats further.

Determinism: index iteration only, no sets/dict-order dependence, no RNG, no
wall clock (AGENTS.md invariant 2).
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from cubesat.hcw import propagate

N_SAMPLES = 601  # mirrors tests/test_hcw.py:123
DRIFT_ORBITS = 3.0

J2_DRAG_CAVEAT = (
    "Boundedness of the dead-satellite coast holds under linear, unperturbed CW "
    "dynamics only; J2 and atmospheric drag would drift the dead satellites "
    "further than reported here (GATES.md:27, README.md:89-90)."
)


def dead_death_states(ticks: list[dict]) -> list[dict]:
    """Per sat that ever flips DEAD: the FIRST tick whose status reads DEAD.
    Failures fire before that tick's heartbeat, so its r/v is exactly the
    state the ballistic coast starts from (sim.py:130-139). Index iteration."""
    deaths: list[dict] = []
    for sat_id in range(len(ticks[0]["sats"])):
        for line in ticks:
            sat = line["sats"][sat_id]
            if sat["status"] == "DEAD":
                deaths.append(
                    {
                        "sat_id": sat_id,
                        "t_death_s": float(line["t"]),
                        "r": [float(c) for c in sat["r"]],
                        "v": [float(c) for c in sat["v"]],
                    }
                )
                break
    return deaths


def secular_drift_rate(death: dict, n: float) -> float:
    """CW secular along-track drift rate [m/s]: -(6 n x0 + 3 vy0) from the STM's
    y-row secular terms (hcw.py:42-46). Zero exactly on the drift-free
    condition vy0 = -2 n x0."""
    return -(6.0 * n * death["r"][0] + 3.0 * death["v"][1])


def _survivor_positions(
    ticks: list[dict], survivor_ids: list[int], times: np.ndarray,
    tick_dt: float, log_end: float, last_states: dict[int, np.ndarray], n: float,
) -> list[np.ndarray]:
    """Survivor positions at the sample times: logged tick positions inside the
    log (nearest tick), hcw.propagate from the last logged state past log end
    (labeled counterfactual by the caller)."""
    t0 = float(ticks[0]["t"])
    out = []
    for t in times:
        if t <= log_end + 1e-9:
            idx = int(round((float(t) - t0) / tick_dt))
            idx = max(0, min(idx, len(ticks) - 1))
            line = ticks[idx]
            out.append(
                np.array([line["sats"][i]["r"] for i in survivor_ids], dtype=float)
            )
        else:
            out.append(
                np.array(
                    [propagate(last_states[i], float(t) - log_end, n)[:3] for i in survivor_ids]
                )
            )
    return out


def drift_horizon_clearance(
    ticks: list[dict],
    death: dict,
    *,
    survivor_ids: list[int],
    n: float,
    horizon_s: float,
    log_end: float,
    tick_dt: float,
    n_samples: int = N_SAMPLES,
) -> dict:
    """Run-window clearance from logged bytes + drift-horizon clearance with the
    horizon-honesty rule (ENDGAME_PLAN 5b)."""
    dead_id = death["sat_id"]
    t_death = death["t_death_s"]
    # (a) run window: ACTUAL logged trajectories, ticks t >= t_death.
    run_min = math.inf
    for line in ticks:
        if line["t"] < t_death - 1e-9:
            continue
        dead_r = np.array(line["sats"][dead_id]["r"], dtype=float)
        for i in survivor_ids:
            d = float(np.linalg.norm(np.array(line["sats"][i]["r"], dtype=float) - dead_r))
            if d < run_min:
                run_min = d
    # (b) drift horizon: dead propagated 3 orbits from the death state.
    # ELAPSED times since death -- hcw.propagate maps from its state0 argument,
    # so sample k is at absolute t_death + times[k].
    state0 = np.array(death["r"] + death["v"], dtype=float)
    times = np.linspace(0.0, horizon_s, n_samples)
    dead_states = propagate(state0, times, n)
    last_states = {
        i: np.array(ticks[-1]["sats"][i]["r"] + ticks[-1]["sats"][i]["v"], dtype=float)
        for i in survivor_ids
    }
    survivor_positions = _survivor_positions(
        ticks, survivor_ids, t_death + times, tick_dt, log_end, last_states, n
    )
    effective = min(log_end, t_death + horizon_s)
    overlap_min = math.inf
    counterfactual_min = math.inf
    n_past_log_end = 0
    for k in range(n_samples):
        t = t_death + float(times[k])
        dead_r = dead_states[k][:3]
        d_min = math.inf
        for pos in survivor_positions[k]:
            d_min = min(d_min, float(np.linalg.norm(pos - dead_r)))
        counterfactual_min = min(counterfactual_min, d_min)
        if t > log_end + 1e-9:
            n_past_log_end += 1
        if t <= effective + 1e-9:
            overlap_min = min(overlap_min, d_min)
    return {
        "run_window_min_clearance_m": float(run_min),
        "effective_horizon_s": float(effective),
        "effective_horizon_orbits": float((effective - t_death) / (horizon_s / DRIFT_ORBITS)),
        "min_clearance_logged_overlap_m": float(overlap_min),
        "counterfactual_min_clearance_full_horizon_m": float(counterfactual_min),
        "n_samples_past_log_end_labeled_counterfactual": n_past_log_end,
    }


def _per_log_analysis(
    log_path: Path, *, n: float, tick_dt: float, keepout_radius_m: float, horizon_s: float
) -> list[dict]:
    import json

    raw = log_path.read_bytes()
    lines = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    ticks = [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]
    log_end = float(ticks[-1]["t"])
    survivor_ids = [
        s["id"] for s in ticks[-1]["sats"] if s["status"] == "NOMINAL"
    ]
    entries = []
    for death in dead_death_states(ticks):
        h = drift_horizon_clearance(
            ticks, death, survivor_ids=survivor_ids, n=n,
            horizon_s=horizon_s, log_end=log_end, tick_dt=tick_dt,
        )
        entries.append(
            {
                "sat_id": death["sat_id"],
                "t_death_s": death["t_death_s"],
                "drift_rate_mps": secular_drift_rate(death, n),
                "keepout_radius_m": keepout_radius_m,
                **h,
            }
        )
    return entries


def _binding(entries: list[dict], radius: float) -> bool:
    return any(e["run_window_min_clearance_m"] < radius - 1e-9 for e in entries)


def _min_clearance(entries: list[dict]) -> float:
    return min(e["run_window_min_clearance_m"] for e in entries)


def keepout_verdict(
    min_wo: float,
    min_w: float,
    binding_wo: bool,
    binding_w: bool,
    identical: bool,
    radius: float,
) -> tuple[str, str]:
    """KEEP/CUT and its sentence, both computed from the measured worst
    run-window clearances (C-1: the sentence used to be hard-coded "improves").
    min_wo belongs to policy 'hungarian' (do-no-harm hold on), min_w to
    'hungarian_keepout' (exclusion term on, hold off): see KEEPOUT_NOTES."""
    wo = f"{min_wo:.1f} m for hungarian (without the exclusion)"
    w = f"{min_w:.1f} m for hungarian_keepout (with the exclusion)"
    if not binding_wo and not binding_w:
        return "CUT", (
            f"keep-out never binding ({wo}; {w}; both >= threshold {radius:.1f} m); "
            "term not added"
        )
    if identical:
        return "CUT", (
            f"policy-5 exclusion never fired: {w} equals {wo} on every pair; the "
            f"sphere is entered by post-replan dead-sat drift, which seat selection at "
            f"replan time cannot prevent; policy 5 cut"
        )
    if min_w > min_wo + 1e-9:
        return "KEEP", (
            f"the exclusion improves the worst clearance: {w} vs {wo} "
            f"(threshold {radius:.1f} m); policy 5 kept"
        )
    if min_w < min_wo - 1e-9:
        return "CUT", (
            f"the exclusion worsens the worst clearance: {w} vs {wo} "
            f"(threshold {radius:.1f} m); policy 5 cut"
        )
    return "CUT", (
        f"worst clearance unchanged by the exclusion: {w} vs {wo} "
        f"(threshold {radius:.1f} m); no measured benefit; policy 5 cut"
    )


KEEPOUT_NOTES = (
    "Confound (audit C-1/B4): policy 'hungarian' runs WITH the do-no-harm hold "
    "(allocate.replan may return do_no_harm_hold) while policy 'hungarian_keepout' "
    "runs WITHOUT it (benchmark_policies.hungarian_keepout_replan accepts but "
    "ignores current_slots), so the with/without comparison changes two things at "
    "once: the exclusion term and the hold. The verdict is therefore about the "
    "policy pair, not about the exclusion term alone."
)


def keepout_report(
    *,
    log_paths: dict[str, list[Path]],
    n: float,
    tick_dt: float,
    keepout_radius_m: float,
    command: str,
    drift_orbits: float = DRIFT_ORBITS,
    n_samples: int = N_SAMPLES,
) -> dict:
    """Full section-5 report over the given logs (policies 1 and 4 at minimum;
    the policy-5 exclusion logs under key 'hungarian_keepout' when available).
    Pure function of log bytes + orbital parameters."""
    horizon_s = drift_orbits * 2.0 * math.pi / n
    per_policy: dict[str, list[dict]] = {}
    for policy in sorted(log_paths):
        entries = []
        for log_path in log_paths[policy]:
            for entry in _per_log_analysis(
                log_path, n=n, tick_dt=tick_dt,
                keepout_radius_m=keepout_radius_m, horizon_s=horizon_s,
            ):
                entry["log"] = log_path.name
                entry["log_sha256"] = hashlib.sha256(log_path.read_bytes()).hexdigest()
                entries.append(entry)
        per_policy[policy] = entries

    comparison: dict = {"keepout_radius_m": keepout_radius_m}
    without = per_policy.get("hungarian", [])
    with_excl = per_policy.get("hungarian_keepout")
    decision = "CUT"
    if not without:
        comparison["decision_text"] = "no hungarian logs provided; section 5(c) not measurable"
    else:
        min_wo = _min_clearance(without)
        binding_wo = _binding(without, keepout_radius_m)
        comparison["min_clearance_without_exclusion_m"] = min_wo
        comparison["binding_without_exclusion"] = binding_wo
        if with_excl:
            min_w = _min_clearance(with_excl)
            binding_w = _binding(with_excl, keepout_radius_m)
            identical = all(
                abs(a["run_window_min_clearance_m"] - b["run_window_min_clearance_m"]) <= 1e-9
                for a, b in zip(
                    sorted(without, key=lambda e: (e["log"], e["sat_id"])),
                    sorted(with_excl, key=lambda e: (e["log"], e["sat_id"])),
                    strict=True,
                )
            )
            comparison["min_clearance_with_exclusion_m"] = min_w
            comparison["binding_with_exclusion"] = binding_w
            comparison["exclusion_changed_any_clearance"] = not identical
            decision, comparison["decision_text"] = keepout_verdict(
                min_wo, min_w, binding_wo, binding_w, identical, keepout_radius_m
            )
        else:
            comparison["decision_text"] = (
                f"run-window min {min_wo:.1f} m vs threshold {keepout_radius_m:.1f} m "
                f"(binding: {binding_wo}); policy-5 exclusion logs not provided -- "
                f"with-exclusion branch of 5(c) not measurable"
            )
    comparison["decision"] = decision
    return {
        "command": command,
        "orbit_period_s": 2.0 * math.pi / n,
        "drift_orbits": drift_orbits,
        "n_samples": n_samples,
        "keepout_radius_m": keepout_radius_m,
        "policies": sorted(log_paths),
        "per_policy": per_policy,
        "keepout_binding_comparison": comparison,
        "notes": KEEPOUT_NOTES,
        "j2_drag_caveat": J2_DRAG_CAVEAT,
    }
