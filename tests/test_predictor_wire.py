"""Display-only predictor risk on the wire (live sandbox, round 2).

The user order: the trained, sealed LightGBM predictor is invisible in the UI
-- make it visible. The display path: Session._install_predictor scores
predictor.runtime against the run's own Scenario + seed into a risk map
(t_s -> sat_id -> [0,1]); Session._frame_with_risk attaches sats[].risk to a
throwaway COPY of each frame (applied in _advance and at seek-time snapshot
build), and wire.py's existing optional passthrough (cubesat/wire.py:146)
carries it. The UI already renders the field (RiskPanel + Suspect labels).

BOUNDARY (the kill-switch verdict): this is the DISPLAY path only. Nothing in
the sim, allocation or replan consumes the map -- the predictor's CONTROL use
(triggering earlier reassignment) stays cut, pinned here by
test_predictor_live_control_use_stays_cut (source log bytes identical to a
bare core run).

Wire contract pinned here:
- POST /simulation/start and /replay/load body "predictor": bool (default
  false); the response echoes the RESOLVED state ("predictor": true iff the
  risk map installed), not the requested flag.
- WS hello carries "predictor": true IFF the risk map is active (deviation-only
  echo, same pattern as the policy echo); omitted otherwise, so predictor-off
  wire bytes are byte-identical to the pre-predictor stream.
- Scoring failure (missing model, lightgbm import, raise) -> the run starts
  anyway, exactly ONE warning event ("Predictor unavailable: <reason>") and no
  risk keys anywhere.

Windows/TestClient guard (the test_api.py:265 doctrine): a driver spawned
during an HTTP request is frozen when that request's ephemeral portal loop
closes, so every HTTP-level read here is BOUNDED to messages emitted
synchronously inside the request (hello/snapshot state, the pre-driver warning,
the INIT state + first frames). Anything needing a full stream drains a DIRECT
session (asyncio.run) instead.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest
from conftest import TINY_SCENARIO, write_tiny_scenario
from fastapi.testclient import TestClient

import cubesat.sim as sim_module
from cubesat.api import app
from cubesat.scenario import load_scenario
from cubesat.session import Hub, Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # predictor/ is a repo-root package, not pip-installed

client = TestClient(app)

SPEED_MAX = 1e6  # pacing neutralized (test_session.py pattern)

# conftest.TINY_SCENARIO with a longer run: predictor.runtime.telemetry_from_schedule
# needs > ~121 telemetry ticks (its internal windows draw integers(0, T-120)), so
# the 11-tick tiny scenario would fail scoring before score_run is ever called.
# 300 s -> T=151 ticks: telemetry succeeds, score_run runs (and can be made to
# raise), while the sim itself stays sub-second.
LONG_SCENARIO: dict = dict(TINY_SCENARIO, name="tiny_long", duration_s=300.0)

# 640 s -> T=321 ticks > WARM=300: scored rows exist (ticks 300/310/320 = t
# 600/620/640 s), so a live run can carry REAL risk on the wire, and the frames
# before t=600 pin the carry-forward lower boundary.
RISKY_SCENARIO: dict = dict(TINY_SCENARIO, name="tiny_risky", duration_s=640.0)


@pytest.fixture(autouse=True)
def _fresh_api_state():
    """Same one-Session-per-process reset as tests/test_policy_selection.py."""
    import cubesat.api

    cubesat.api._state = None
    yield
    state = cubesat.api._state
    if state is not None and state.session._driver is not None:
        state.session._driver.cancel()  # best effort: the loop is gone anyway
    cubesat.api._state = None


def _write_scenario(tmp_path, scenario: dict) -> Path:
    directory = tmp_path / "scenarios"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{scenario['name']}.json"
    path.write_text(json.dumps(scenario), encoding="utf-8", newline="\n")
    return path


def _make_session(tmp_path, scenario_name: str):
    """Direct Session over a scenarios dir that already holds scenario_name."""
    hub = Hub()
    session = Session(
        scenario_dir=tmp_path / "scenarios",
        log_dir=tmp_path / "logs",
        hub=hub,
        min_emit_interval=0.0,
    )
    return hub, session


def _log_bytes(lines: list[dict]) -> list[str]:
    """The exact cubesat.run JSONL serialization (cubesat/run.py:44)."""
    return [json.dumps(line, sort_keys=True) for line in lines]


def _source_lines(session: Session) -> list[dict]:
    src = session._source
    assert src is not None
    return [src.header] + src.frames + [src.summary]


async def _drain_until_run_complete(q, timeout: float = 30.0) -> list[dict]:
    msgs: list[dict] = []
    while True:
        msg = await asyncio.wait_for(q.get(), timeout)
        msgs.append(msg)
        if msg.get("type") == "event" and msg.get("message") == "Run complete":
            return msgs


def _assert_risk_values(msgs: list[dict]) -> int:
    """Every sats[].risk on these messages is a float in [0,1]; returns count."""
    seen = 0
    for m in msgs:
        if m.get("type") != "sim_state":
            continue
        for s in m.get("sats", []):
            if "risk" in s:
                assert isinstance(s["risk"], (int, float)) and 0.0 <= s["risk"] <= 1.0
                seen += 1
    return seen


def test_predictor_default_off_no_risk_on_wire(tmp_path, monkeypatch):
    """(a) Default start (predictor absent == false): NO sats[].risk key anywhere
    on the wire, and the hello omits the predictor echo entirely."""
    import cubesat.api

    write_tiny_scenario(tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "_MIN_EMIT_INTERVAL", 0.0)

    r = client.post("/simulation/start", json={"speed": SPEED_MAX})
    assert r.status_code == 200
    assert r.json()["predictor"] is False  # resolved echo: map never installed

    with client.websocket_connect("/ws/state") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["mode"] == "live"
        assert "predictor" not in hello  # deviation-only echo: absent when off
        snap = ws.receive_json()
        assert snap["type"] == "sim_state"
        assert _assert_risk_values([snap]) == 0

        # a second, slow-speed start streams to the CONNECTED client (the
        # test_policy_selection.py:364-379 pattern: at speed 2.0 the two
        # sim_states received are the INIT state + frame t=0, both emitted
        # synchronously inside the request -- the bounded-read guarantee).
        assert client.post("/simulation/reset").status_code == 200
        assert client.post("/simulation/start", json={"speed": 2.0}).status_code == 200
        got = 0
        while got < 2:
            m = ws.receive_json()
            if m["type"] == "sim_state":
                assert _assert_risk_values([m]) == 0
                got += 1
        assert client.post("/simulation/reset").status_code == 200


def test_predictor_replay_risk_past_warmup(tmp_path, monkeypatch):
    """(b) predictor=true replay of the committed two_failure log: ONE scoring
    run against the scenario resolved from scenarios_dir; seeking past the
    300-tick warmup (t=2000 s >> 600 s first scored tick) puts sats[].risk in
    [0,1] on the seeked snapshot (and the hello echoes the active map)."""
    import cubesat.api

    (tmp_path / "scenarios").mkdir()
    (tmp_path / "logs").mkdir()
    shutil.copyfile(ROOT / "data" / "scenarios" / "two_failure.json",
                    tmp_path / "scenarios" / "two_failure.json")
    shutil.copyfile(ROOT / "data" / "logs" / "two_failure.jsonl",
                    tmp_path / "logs" / "two_failure.jsonl")
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(cubesat.api, "_MIN_EMIT_INTERVAL", 0.0)

    load = client.post("/replay/load",
                       json={"filename": "two_failure.jsonl", "speed": SPEED_MAX,
                             "predictor": True})
    assert load.status_code == 200
    assert load.json()["predictor"] is True  # the one scoring run succeeded
    # Hold the session so the seek-time snapshot is not overwritten by the
    # respawned driver streaming on: pause -> seek freezes the cursor there.
    assert client.post("/replay/pause").status_code == 200
    assert client.post("/replay/seek", json={"t": 2000.0}).status_code == 200

    with client.websocket_connect("/ws/state") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["mode"] == "replay"
        assert hello["predictor"] is True
        snap = ws.receive_json()
        assert snap["type"] == "sim_state" and snap["sim_time"] == 2000.0
        risks = [s["risk"] for s in snap["sats"] if "risk" in s]
        assert risks  # past the warmup: scored sats carry the overlay
        assert all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in risks)


def test_predictor_scoring_failure_warning(tmp_path, monkeypatch):
    """(c) score_run raising -> the run starts fine, the warning event rides the
    wire ahead of the stream, and no risk key appears anywhere. The long
    scenario keeps telemetry synthesis alive so the raise lands IN score_run."""
    import cubesat.api
    import predictor.runtime as predictor_runtime

    write_tiny_scenario(tmp_path / "scenarios", scenario=LONG_SCENARIO)
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "_MIN_EMIT_INTERVAL", 0.0)

    def boom(telemetry):
        raise RuntimeError("model gone")

    monkeypatch.setattr(predictor_runtime, "score_run", boom)

    r = client.post("/simulation/start", json={"speed": SPEED_MAX, "predictor": True})
    assert r.status_code == 200  # the run starts fine despite the failure
    assert r.json()["predictor"] is False

    with client.websocket_connect("/ws/state") as ws:
        hello = ws.receive_json()
        assert "predictor" not in hello  # map never installed -> no echo
        assert _assert_risk_values([ws.receive_json()]) == 0  # run-1 snapshot

        # a second predictor=true start streams to the CONNECTED client. The
        # warning is published during start, BEFORE any driver frame, so the
        # bounded in-request read is deterministic: warning, INIT state, t=0.
        assert client.post("/simulation/reset").status_code == 200
        start = client.post("/simulation/start",
                            json={"speed": 2.0, "predictor": True})
        assert start.status_code == 200
        msgs = [ws.receive_json() for _ in range(3)]
        warning = msgs[0]
        assert warning["type"] == "event" and warning["level"] == "warning"
        assert warning["message"].startswith("Predictor unavailable: ")
        assert "RuntimeError" in warning["message"]  # boom's own reason, verbatim
        assert _assert_risk_values(msgs) == 0  # no risk keys anywhere


def test_predictor_live_control_use_stays_cut(tmp_path):
    """The boundary pin, on a DIRECT session (its driver lives for the whole
    run): a predictor=true LIVE run produces source log lines BYTE-IDENTICAL to
    a bare core run -- nothing in the sim consumed the risk map (the kill-switch
    verdict holds) -- while the wire gains sats[].risk only from the first
    scored tick (t=600 s) onward: the display path works AND stays fenced."""
    _write_scenario(tmp_path, RISKY_SCENARIO)
    direct = sim_module.run_scenario(
        load_scenario(tmp_path / "scenarios" / "tiny_risky.json"))

    async def main():
        hub, session = _make_session(tmp_path, "tiny_risky")
        q = hub.subscribe()
        await session.start_live("tiny_risky.json", None, SPEED_MAX, predictor=True)
        assert session.predictor_active
        assert session.hello()["predictor"] is True
        msgs = await _drain_until_run_complete(q)
        lines = _source_lines(session)
        await session.reset()
        return msgs, lines

    msgs, lines = asyncio.run(main())
    assert _log_bytes(lines) == _log_bytes(direct)  # CONTROL use stays cut
    states = [m for m in msgs if m.get("type") == "sim_state"]
    early = [m for m in states if m["sim_time"] < 600.0]
    late = [m for m in states if m["sim_time"] >= 600.0]
    assert early and all("risk" not in s for m in early for s in m["sats"])
    assert late and _assert_risk_values(late) > 0  # DISPLAY path live from t=600
