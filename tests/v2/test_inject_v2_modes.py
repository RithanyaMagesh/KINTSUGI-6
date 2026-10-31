"""W2 item 5: live injection of the engine-v2 modes through Session and the API."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cubesat.scenario import Failure, load_scenario
from cubesat.session import Hub, Session, SessionError
from cubesat.sim_v2 import EngineV2
from cubesat.wire import SessionEnrich, to_messages

ROOT = Path(__file__).resolve().parents[2]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"
V2_MODES = ["PAYLOAD_FAIL", "PARTIAL_THRUST", "THRUSTER_STUCK_OPEN", "RADIO_FAIL"]


def _write(tmp_path, engine="v2", failures=(), name="two_failure.json"):
    scn = load_scenario(TWO_FAILURE).model_copy(
        update={"engine": engine, "duration_s": 60.0, "failures": list(failures)}
    )
    d = tmp_path / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(scn.model_dump_json())
    return scn


def _session(tmp_path):
    hub = Hub(maxsize=100_000)
    return hub, Session(tmp_path / "scenarios", tmp_path / "logs", hub, min_emit_interval=0.0)


async def _start_until(session, q, t, msgs):
    await session.start_live("two_failure.json", speed=20.0)
    while session.sim_time is None or session.sim_time < t:
        msgs.append(await asyncio.wait_for(q.get(), 30))


async def _finish(q, msgs):
    while not (msgs and msgs[-1].get("message") == "Run complete"):
        msgs.append(await asyncio.wait_for(q.get(), 60))
    return msgs


def _inject_run(tmp_path, mode, sat="SAT-3", failures=(), degrade_s=600.0):
    _write(tmp_path, "v2", failures)

    async def main():
        hub, session = _session(tmp_path)
        q = hub.subscribe()
        msgs: list = []
        await _start_until(session, q, 10.0, msgs)
        t_inject = session.sim_time
        await session.inject_failure(sat, mode, degrade_s)
        return session, t_inject, await _finish(q, msgs)

    return asyncio.run(main())


def _last_row(msgs, sat_id):
    states = [m for m in msgs if m["type"] == "sim_state" and m["sats"]]
    return next(r for r in states[-1]["sats"] if r["id"] == sat_id)


@pytest.mark.parametrize("mode,status,event_text", [
    ("PAYLOAD_FAIL", "PAYLOAD_FAILED",
     "SAT-3 camera failed; it keeps flying but can no longer image"),
    ("RADIO_FAIL", "RADIO_SILENT", "SAT-3 lost its radio; it keeps flying but is silent"),
])
def test_v2_injection_streams_status_event_and_equals_engine_replay(
    tmp_path, mode, status, event_text
):
    session, t_inject, msgs = _inject_run(tmp_path, mode)
    row = _last_row(msgs, "SAT-3")
    assert (row["status"], row["failure_type"]) == ("degraded", status)
    events = [m for m in msgs if m["type"] == "event"]
    hit = [e for e in events if e["message"] == event_text]
    assert hit and hit[0]["sat_id"] == "SAT-3" and hit[0]["sim_time"] >= t_inject
    # live == replay: an EngineV2 injected between ticks (the engine's own live path) records
    # the resolved failure, and its log is the session's recomputed log, wire for wire
    scn = session._source.scenario.model_copy(update={"failures": []})
    eng = EngineV2(scn)
    lines = [eng.header()]
    while eng.k * scn.dt_s <= t_inject:
        lines.append(eng.step())
    eng.inject(Failure(t=0.0, sat_id=2, mode=mode))
    assert [f.t for f in eng.injections] == [t_inject + scn.dt_s]
    lines += list(eng.run())
    replay = list(EngineV2(scn, eng.injections).run())
    assert json.dumps(lines, sort_keys=True) == json.dumps(replay, sort_keys=True)
    enrich = SessionEnrich(scenario="two_failure", seed=scn.seed)
    expect = [m for line in replay for m in to_messages(line, enrich)]
    got = [m for m in msgs if "failure injected; recomputing" not in m.get("message", "")]
    assert json.dumps(got, sort_keys=True) == json.dumps(expect, sort_keys=True)


def test_every_v2_mode_can_be_injected_live(tmp_path):
    for mode in V2_MODES:
        _, _, msgs = _inject_run(tmp_path, mode)
        assert _last_row(msgs, "SAT-3")["failure_type"] in {
            "PAYLOAD_FAILED", "RADIO_SILENT", "DEGRADED", "FUEL_DEPLETED", "REENTERED"}


def test_stuck_open_injection_shows_on_the_sat_row(tmp_path):
    # not self-reported and not silent, so the wire shows it through the resource keys
    _, _, msgs = _inject_run(tmp_path, "THRUSTER_STUCK_OPEN")
    row = _last_row(msgs, "SAT-3")
    assert row["stuck"] is True and row["status"] in ("degraded", "failed")


def test_eps_degrade_live_injection_still_works_on_v2(tmp_path):
    _, _, msgs = _inject_run(tmp_path, "EPS_DEGRADE", sat="SAT-2", degrade_s=20.0)
    assert _last_row(msgs, "SAT-2")["status"] == "failed"


def test_inject_onto_sat_with_an_existing_benign_failure_is_allowed(tmp_path):
    earlier = [Failure(t=4.0, sat_id=2, mode="PAYLOAD_FAIL")]
    _, _, msgs = _inject_run(tmp_path, "RADIO_FAIL", failures=earlier)
    assert _last_row(msgs, "SAT-3")["failure_type"] == "RADIO_SILENT"


def test_inject_onto_a_dead_sat_is_409_with_a_plain_reason(tmp_path):
    with pytest.raises(SessionError) as exc:
        _inject_run(tmp_path, "PARTIAL_THRUST", failures=[Failure(t=4.0, sat_id=2, mode="DEAD")])
    assert exc.value.status_code == 409
    assert exc.value.detail == "SAT-3 is already dead"


def test_inject_onto_a_reentered_sat_is_409(tmp_path):
    _write(tmp_path, "v2")

    async def main():
        hub, session = _session(tmp_path)
        q = hub.subscribe()
        await _start_until(session, q, 10.0, [])
        last = session._source.frames[session._cursor - 1]
        last["sats"][2]["status"] = "REENTERED"
        with pytest.raises(SessionError) as exc:
            await session.inject_failure("SAT-3", "RADIO_FAIL")
        return exc.value

    err = asyncio.run(main())
    assert (err.status_code, err.detail) == (409, "SAT-3 has already re-entered")


@pytest.mark.parametrize("mode", V2_MODES)
def test_v2_modes_on_a_v1_run_are_422_with_the_engine_named(tmp_path, mode):
    _write(tmp_path, "v1")

    async def main():
        hub, session = _session(tmp_path)
        await session.start_live("two_failure.json", speed=20.0)
        with pytest.raises(SessionError) as exc:
            await session.inject_failure("SAT-3", mode)
        return exc.value

    err = asyncio.run(main())
    assert err.status_code == 422
    assert err.detail == (
        f'failure mode {mode} requires engine "v2"; the running scenario uses engine "v1"'
    )


def test_api_accepts_v2_modes_on_v2_and_rejects_them_on_v1(tmp_path, monkeypatch):
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    client = TestClient(cubesat.api.app)
    body = {"sat_id": "SAT-3", "mode": "PAYLOAD_FAIL"}
    _write(tmp_path, "v1")
    assert client.post("/simulation/start", json={"speed": 20.0}).status_code == 200
    r = client.post("/failure/inject", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == (
        'failure mode PAYLOAD_FAIL requires engine "v2"; the running scenario uses engine "v1"'
    )
    client.post("/simulation/reset")
    _write(tmp_path, "v2")
    assert client.post("/simulation/start", json={"speed": 20.0}).status_code == 200
    r = client.post("/failure/inject", json=body)
    assert r.status_code == 200 and r.json()["injected"] == body
    client.post("/simulation/reset")
