"""Phase 5a fix round: `role` display order, benchmark.metrics_from_log and wire read `roles`."""

import json
from pathlib import Path

import pytest

from cubesat.benchmark import metrics_from_log
from cubesat.roles_v2 import primary_role
from cubesat.scenario import Scenario
from cubesat.sim_v2 import run_scenario_v2
from cubesat.wire import SessionEnrich, _track_roles, to_messages

ROOT = Path(__file__).resolve().parents[2]
SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}


@pytest.mark.parametrize(
    "roles, want",
    [(["imager", "leader"], "leader"), (["downlink", "imager"], "downlink"),
     (["downlink", "leader"], "leader"), (["downlink", "imager", "leader"], "leader"),
     (["imager"], "imager"), (["spare"], "spare"), ([], "none")],
)
def test_primary_role_uses_the_fixed_display_order(roles, want):
    assert primary_role(roles) == want


# --- benchmark.metrics_from_log ---------------------------------------------------------------
def _sat(i, status="NOMINAL", role="imager", roles=None):
    row = {"id": i, "role": role, "status": status, "r": [0.0, 0.0, 0.0], "dv_used": 0.0}
    if roles is not None:
        row["roles"] = roles
    return row


def _log(tmp_path, *tick_sats):
    lines = [{"v": 1, "t": 0.0, "state": "INIT"}]
    for k, sats in enumerate(tick_sats):
        lines.append({"v": 1, "t": 2.0 * k, "state": "NOMINAL", "coverage": 0.5, "sats": sats})
    lines.append({"v": 1, "t": 2.0 * len(tick_sats), "state": "SUMMARY",
                  "coverage_mean_last_orbit": 0.5})
    path = tmp_path / "log.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return metrics_from_log(path, first_failure_t=0.0, dead_ids=[], duration_s=4.0)


def test_stacked_leader_on_an_imager_counts_as_both(tmp_path):
    sats = [_sat(0, role="leader", roles=["imager", "leader"]),
            _sat(1, role="downlink", roles=["downlink"])]
    m = _log(tmp_path, sats, sats)
    assert m["critical_roles_held_end"] and m["imagers_end"] == 1 and m["critical_vacancy_s"] == 0.0


def test_stacked_downlink_on_an_imager_counts_as_both(tmp_path):
    sats = [_sat(0, role="leader", roles=["leader"]),
            _sat(1, role="imager", roles=["downlink", "imager"])]  # label hides the downlink
    m = _log(tmp_path, sats)
    assert m["critical_roles_held_end"] and m["imagers_end"] == 1


def test_both_critical_roles_stacked_on_one_imager(tmp_path):
    sats = [_sat(0, role="leader", roles=["downlink", "imager", "leader"]),
            _sat(1, status="DEAD", role="none", roles=[])]
    m = _log(tmp_path, sats)
    assert m["critical_roles_held_end"] and m["imagers_end"] == 1


def test_a_dead_sat_that_keeps_its_roles_is_not_service(tmp_path):
    sats = [_sat(0, status="DEAD", role="leader", roles=["leader"]),
            _sat(1, role="downlink", roles=["downlink"])]
    assert not _log(tmp_path, sats)["critical_roles_held_end"]


def test_v1_logs_without_roles_fall_back_to_the_role_label(tmp_path):
    sats = [_sat(0, role="leader"), _sat(1, role="downlink"), _sat(2), _sat(3, status="DEAD")]
    m = _log(tmp_path, sats)
    assert m["critical_roles_held_end"] and m["imagers_end"] == 1


def test_v2_dead_leader_keeps_roles_and_vacancy_is_the_detection_latency(tmp_path):
    d = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    scn = Scenario.model_validate({
        **d, "engine": "v2", "duration_s": 300.0, "sensor": SENSOR,
        "failures": [{"t": 100.0, "sat_id": 0, "mode": "DEAD"}],
    })
    path = tmp_path / "v2.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in run_scenario_v2(scn)) + "\n")
    m = metrics_from_log(path, first_failure_t=100.0, dead_ids=[0], duration_s=300.0)
    assert m["critical_roles_held_end"] and m["imagers_end"] == 4
    assert m["critical_vacancy_s"] == 4.0  # ticks 100 and 102 = (K - 1) * dt of detection


# --- wire --------------------------------------------------------------------------------------
def _wsat(i, status="NOMINAL", role="imager", roles=None, orig="imager"):
    row = {"id": i, "role": role, "status": status, "r": [1.0, 2.0, 3.0], "v": [0.0] * 3,
           "dv_used": 0.0}
    if roles is not None:
        row.update(roles=roles, original_role=orig)
    return row


def _frame(sats, t=10.0, **extra):
    return {"v": 1, "t": t, "state": "NOMINAL", "coverage": 0.1, "min_sep": 50.0,
            "sats": sats, **extra}


def test_wire_forwards_roles_and_original_role_only_when_the_log_has_them():
    rows = to_messages(_frame([_wsat(0, roles=["imager"]), _wsat(1)]), SessionEnrich())[0]["sats"]
    assert rows[0]["roles"] == ["imager"] and rows[0]["original_role"] == "imager"
    assert "roles" not in rows[1] and "original_role" not in rows[1]


def test_track_roles_sees_a_stacked_downlink_gained_by_the_leader_sat():
    enrich = SessionEnrich()
    before = _frame([_wsat(0, role="leader", roles=["leader"]),
                     _wsat(1, role="downlink", roles=["downlink"])], t=100.0)
    after = _frame([_wsat(0, role="leader", roles=["downlink", "leader"]),
                    _wsat(1, status="DEAD", role="none", roles=[])], t=104.0)
    _track_roles(before, enrich)
    old, handoffs = _track_roles(after, enrich)
    assert old == {1: "downlink"}  # the display label of sat 0 did not change
    assert handoffs == [{"role": "downlink", "from_sat": "SAT-2", "to_sat": "SAT-1"}]


def test_track_roles_sees_a_leader_stacked_on_an_imager():
    enrich = SessionEnrich()
    before = _frame(
        [_wsat(0, role="leader", roles=["imager", "leader"]), _wsat(1, roles=["imager"])]
    )
    after = _frame([_wsat(0, status="DEAD", role="none", roles=[]),
                    _wsat(1, role="leader", roles=["imager", "leader"])], t=12.0)
    _track_roles(before, enrich)
    assert _track_roles(after, enrich)[1] == [
        {"role": "leader", "from_sat": "SAT-1", "to_sat": "SAT-2"}
    ]


def _handoff(payload, t=104.0):
    ev = {"type": "ROLE_HANDOFF", "payload": payload}
    frame = _frame([_wsat(0)], t=t, event=ev, events=[ev])
    msgs = to_messages(frame, SessionEnrich())
    return [m for m in msgs if m["type"] == "event"]


@pytest.mark.parametrize(
    "payload, text",
    [
        ({"role": "leader", "from_sat": 0, "to_sat": 1, "reason": "DEAD"},
         "SAT-1 leader role handed to SAT-2 because SAT-1 failed"),
        ({"role": "downlink", "from_sat": 5, "to_sat": 2, "reason": "RADIO_SILENT"},
         "SAT-6 downlink role handed to SAT-3 because SAT-6 lost its radio"),
        ({"role": "leader", "from_sat": 0, "to_sat": 1, "reason": "REENTERED"},
         "SAT-1 leader role handed to SAT-2 because SAT-1 re-entered the atmosphere"),
        ({"role": "leader", "from_sat": 0, "to_sat": None, "reason": "DEAD"},
         "SAT-1 failed; the leader role is now vacant (no capable satellite is left)"),
        ({"role": "leader", "from_sat": None, "to_sat": 3, "reason": "VACANT"},
         "SAT-4 took over the vacant leader role"),
        ({"role": "leader", "from_sat": 0, "to_sat": 1, "reason": "WARP_CORE"},
         "SAT-1 leader role handed to SAT-2"),
        ({"role": "leader", "from_sat": None, "to_sat": None, "reason": "VACANT"},
         "The leader role is now vacant"),
        ({}, "A satellite critical role handed to another satellite"),
    ],
)
def test_role_handoff_event_sentence(payload, text):
    (ev,) = _handoff(payload)
    assert ev["message"] == text and ev["level"] == "info"
    if payload.get("from_sat") is not None:
        assert ev["sat_id"] == f"SAT-{payload['from_sat'] + 1}"


def test_real_v2_log_leader_death_becomes_one_plain_event():
    d = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    scn = Scenario.model_validate({
        **d, "engine": "v2", "duration_s": 120.0, "sensor": SENSOR,
        "failures": [{"t": 100.0, "sat_id": 0, "mode": "DEAD"}],
    })
    enrich, texts = SessionEnrich(), []
    for line in run_scenario_v2(scn):
        texts += [m["message"] for m in to_messages(line, enrich) if m["type"] == "event"]
    assert "SAT-1 leader role handed to SAT-2 because SAT-1 failed" in texts
    assert sum("role handed" in t for t in texts) == 1
