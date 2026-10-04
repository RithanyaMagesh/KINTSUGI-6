"""Recovery policy selection tests (live sandbox, round 2).

The user demand: recovery ALGORITHMS selectable in live, not just displayed.
The seam of record is cubesat.benchmark.run_one's rebind of cubesat.sim.replan
(cubesat/benchmark.py:81-92; sim.py resolves the module global at its call
site, cubesat/sim.py:265). session.start_live applies the SAME rebind, scoped
to the run: installed in Session._prepare, restored in Session._teardown (and
in start_live's exception guard), so the selected policy drives replanning for
the initial run AND every failure-injection recompute, with zero core diffs.

Wire contract pinned here (frontend integration contract):
- POST /simulation/start body "policy": "hungarian" (default) | "even_split" |
  "hungarian_keepout"; anything else -> 422 (pydantic literal_error at the API
  boundary, SessionError 422 for direct session calls).
- The start response carries the active "policy".
- WS hello carries "policy" iff KNOWN: always on live runs (including the
  default "hungarian"); OMITTED when stopped or replaying -- a replayed log
  records no policy field, and the committed data/eval/benchmark logs include
  even_split/do_nothing runs, so reporting "hungarian" for any replay would be
  a fabrication (AGENTS.md invariant 1). Absence = unknown; the frontend
  defaults to "hungarian", which every pre-policy data/logs log is by
  construction.
- sim_state carries "policy" ONLY on deviation from "hungarian"
  (wire._policy_field): this keeps the default-policy wire bytes identical to
  the pinned golden fixture (tests/fixtures/wire_golden.json) and to the
  live==replay stream pin (tests/test_session.py::test_live_equals_replay_frames).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from conftest import tiny_log_lines, write_log, write_tiny_scenario
from fastapi.testclient import TestClient

import cubesat.allocate as allocate
import cubesat.sim as sim_module
from cubesat.api import app
from cubesat.benchmark_policies import even_split_replan
from cubesat.scenario import load_scenario
from cubesat.session import Hub, Session, SessionError
from cubesat.wire import POLICY_VALUES

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[1]
SPEED_MAX = 1e6  # pacing neutralized (test_session.py pattern)


@pytest.fixture(autouse=True)
def _fresh_api_state():
    """Same one-Session-per-process reset as tests/test_api.py (section 9.1)."""
    import cubesat.api

    cubesat.api._state = None
    yield
    state = cubesat.api._state
    if state is not None and state.session._driver is not None:
        state.session._driver.cancel()  # best effort: the loop is gone anyway
    cubesat.api._state = None


# 4-sat two-failure variant of conftest.TINY_SCENARIO (measured 2026-10-04:
# BOTH the core hungarian path and even_split complete on it; failures hit
# sats 1 and 3, survivors are the leader (0) and imager (2)).
TINY_TWO_FAILURE: dict = {
    "name": "tiny_two_failure",
    "seed": 7,
    "duration_s": 40.0,
    "dt_s": 2.0,
    "chief": {"altitude_km": 500.0},
    "formation": {"n_slots": 4, "radial_amp_km": 1.0, "phase_offset_deg": 0.0},
    "a_max_mps2": 0.01,
    "gains": {"wn": 0.01, "zeta": 1.0},
    "sensor": {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0},
    "roles": ["leader", "imager", "imager", "downlink"],
    "failures": [
        {"t": 6.0, "sat_id": 1, "mode": "DEAD"},
        {"t": 10.0, "sat_id": 3, "mode": "DEAD"},
    ],
}

# GOLDEN (measured 2026-10-04): even_split on data/scenarios/two_failure.json
# (seed 42) via the benchmark seam; identity slot mapping, unlike hungarian.
# Produced with the cubesat.benchmark.run_one rebind and pinned by this file:
# uv run python -m pytest tests/test_policy_selection.py -q
EVEN_SPLIT_GOLDEN = [
    (1208.0, [
        ("SAT-1", "imager", "slot_0"),
        ("SAT-3", "leader", "slot_1"),
        ("SAT-4", "imager", "slot_2"),
        ("SAT-5", "downlink", "slot_3"),
        ("SAT-6", "imager", "slot_4"),
    ]),
    (1508.0, [
        ("SAT-1", "imager", "slot_0"),
        ("SAT-4", "leader", "slot_1"),
        ("SAT-5", "imager", "slot_2"),
        ("SAT-6", "downlink", "slot_3"),
    ]),
]
EVEN_SPLIT_TWO_FAILURE_LOG_SHA256 = (
    "657679fbf1ac2151e1d859a775c36ef9c6e919f124e2ed58f2b40671408f3826"
)

# The hungarian reference for the SAME first replan tick, from the committed
# wire golden fixture (tests/fixtures/wire_golden.json, t=1208.0
# role_reassignment): non-identity -- SAT-1 takes slot_1, not slot_0.
HUNGARIAN_REFERENCE_FIRST_REPLAN = [
    ("SAT-1", "leader", "slot_1"),
    ("SAT-3", "imager", "slot_0"),
    ("SAT-4", "imager", "slot_2"),
    ("SAT-5", "imager", "slot_4"),
    ("SAT-6", "downlink", "slot_3"),
]


def _make_session(tmp_path):
    hub = Hub()
    session = Session(
        scenario_dir=tmp_path / "scenarios",
        log_dir=tmp_path / "logs",
        hub=hub,
        min_emit_interval=0.0,
    )
    return hub, session


def _write_two_failure_scenario(tmp_path) -> Path:
    """conftest.write_tiny_scenario always writes "tiny.json", so the 4-sat
    two-failure variant gets its own writer under its own name."""
    directory = tmp_path / "scenarios"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "tiny_two_failure.json"
    path.write_text(json.dumps(TINY_TWO_FAILURE), encoding="utf-8", newline="\n")
    return path


def _log_bytes(lines: list[dict]) -> list[str]:
    """The exact cubesat.run JSONL serialization (cubesat/run.py:44)."""
    return [json.dumps(line, sort_keys=True) for line in lines]


def _source_lines(session: Session) -> list[dict]:
    src = session._source
    assert src is not None
    return [src.header] + src.frames + [src.summary]


async def _drain_until_run_complete(q, timeout: float = 10.0) -> list[dict]:
    msgs: list[dict] = []
    while True:
        msg = await asyncio.wait_for(q.get(), timeout)
        msgs.append(msg)
        if msg.get("type") == "event" and msg.get("message") == "Run complete":
            return msgs


def _assignment_triples(msg: dict) -> list[tuple[str, str, str]]:
    return [(a["satellite_id"], a["new_role"], a["target_slot"]) for a in msg["assignments"]]


def test_policy_registry_matches_wire_literal():
    """Drift guard: the session's replan map covers exactly the non-default
    wire policies, and the default never rebinds (byte-identical mechanism)."""
    assert POLICY_VALUES == ("hungarian", "even_split", "hungarian_keepout")
    from cubesat.session import _POLICY_REPLANNERS

    assert set(_POLICY_REPLANNERS) == {"even_split", "hungarian_keepout"}
    assert _POLICY_REPLANNERS["even_split"] is even_split_replan
    assert "hungarian" not in _POLICY_REPLANNERS


def test_policy_hungarian_default_byte_identical(tmp_path):
    """policy='hungarian' (and the default start) must be byte-identical to a
    bare core run: same log lines, and cubesat.sim.replan is NEVER rebound."""
    write_tiny_scenario(tmp_path / "scenarios")  # conftest.TINY_SCENARIO
    direct = sim_module.run_scenario(load_scenario(tmp_path / "scenarios" / "tiny.json"))

    async def main():
        hub, session = _make_session(tmp_path)
        q = hub.subscribe()
        await session.start_live("tiny.json", None, SPEED_MAX)  # no policy arg
        assert session.enrich.policy == "hungarian"
        assert session.hello()["policy"] == "hungarian"
        assert sim_module.replan is allocate.replan  # default never rebinds
        await _drain_until_run_complete(q)
        lines_default = _source_lines(session)
        await session.reset()

        q2 = hub.subscribe()
        await session.start_live("tiny.json", None, SPEED_MAX, "hungarian")
        assert session.enrich.policy == "hungarian"
        await _drain_until_run_complete(q2)
        lines_explicit = _source_lines(session)
        await session.reset()
        return lines_default, lines_explicit

    lines_default, lines_explicit = asyncio.run(main())
    assert _log_bytes(lines_default) == _log_bytes(direct)
    assert _log_bytes(lines_explicit) == _log_bytes(direct)


def test_policy_unknown_rejected_422(tmp_path):
    """Unknown policy -> 422 at BOTH layers. do_nothing/greedy are benchmark
    baselines, deliberately NOT live-selectable. A rejected start must also
    leave a running session untouched (validation precedes any state change)."""
    write_tiny_scenario(tmp_path / "scenarios")

    async def main():
        hub, session = _make_session(tmp_path)
        await session.start_live("tiny.json", None, SPEED_MAX)
        for bad in ("greedy", "do_nothing", "EVEN_SPLIT", ""):
            with pytest.raises(SessionError) as exc:
                await session.start_live("tiny.json", None, SPEED_MAX, bad)
            assert exc.value.status_code == 422
            assert "policy" in exc.value.detail
        # the previously running session survived the rejected starts
        assert session.mode == "live"
        assert session.enrich.policy == "hungarian"
        await session.reset()

    asyncio.run(main())

    # API boundary: pydantic Literal -> 422 before the handler runs
    for bad in ("greedy", "do_nothing"):
        r = client.post("/simulation/start", json={"policy": bad})
        assert r.status_code == 422, bad
        assert "policy" in r.text


def test_policy_even_split_golden_assignment(tmp_path):
    """even_split on the real two-failure scenario completes and produces a
    DIFFERENT deterministic assignment than the shipped hungarian path (whose
    first replan is pinned by the committed wire fixture). Golden values are
    measured (see EVEN_SPLIT_GOLDEN); the full log sha256 pins end-to-end
    determinism per (scenario, seed, policy) (AGENTS.md invariant 2)."""
    two_failure = ROOT / "data" / "scenarios" / "two_failure.json"

    async def main():
        hub = Hub()
        session = Session(
            scenario_dir=two_failure.parent,
            log_dir=tmp_path / "logs",
            hub=hub,
            min_emit_interval=0.0,
        )
        q = hub.subscribe()
        await session.start_live("two_failure.json", None, SPEED_MAX, "even_split")
        assert session.hello()["policy"] == "even_split"
        assert sim_module.replan is even_split_replan  # seam open for the run
        msgs = await _drain_until_run_complete(q, timeout=30.0)
        lines = _source_lines(session)
        await session.reset()
        assert sim_module.replan is allocate.replan  # seam closed by teardown
        return msgs, lines

    msgs, lines = asyncio.run(main())

    reassign = [m for m in msgs if m["type"] == "role_reassignment"]
    assert [(m["sim_time"], _assignment_triples(m)) for m in reassign] == EVEN_SPLIT_GOLDEN
    assert _assignment_triples(reassign[0]) != HUNGARIAN_REFERENCE_FIRST_REPLAN
    # deviation echo on the wire: every sim_state carries the active policy
    states = [m for m in msgs if m["type"] == "sim_state"]
    assert states and all(m.get("policy") == "even_split" for m in states)
    # role_reassignment shape unchanged (no policy key invented there)
    assert all("policy" not in m for m in reassign)
    # end-to-end determinism pin: bytes exactly as cubesat.run writes them
    raw = "".join(line + "\n" for line in _log_bytes(lines)).encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == EVEN_SPLIT_TWO_FAILURE_LOG_SHA256
    # the run really completed
    assert lines[-1]["state"] == "SUMMARY"


def test_policy_even_split_double_run_byte_identical(tmp_path):
    """even_split is deterministic per (scenario, seed, policy) through the
    session path: two live runs give byte-identical logs (AGENTS.md invariant 2)."""
    _write_two_failure_scenario(tmp_path)

    async def one():
        hub, session = _make_session(tmp_path)
        q = hub.subscribe()
        await session.start_live("tiny_two_failure.json", None, SPEED_MAX, "even_split")
        await _drain_until_run_complete(q)
        lines = _source_lines(session)
        await session.reset()
        return lines

    first = asyncio.run(one())
    second = asyncio.run(one())
    assert _log_bytes(first) == _log_bytes(second)
    methods = {
        line["event"]["payload"]["method"]
        for line in first
        if (line.get("event") or {}).get("type") == "ASSIGNMENT"
    }
    assert methods == {"even_split"}


def test_policy_seam_active_across_injection(tmp_path):
    """The seam window spans the session's whole live lifetime: a failure
    injection recompute replans under the SELECTED policy, and teardown
    restores the core exactly (mirrors test_benchmark_replanning_rebinding_restored)."""
    _write_two_failure_scenario(tmp_path)

    async def main():
        hub, session = _make_session(tmp_path)
        q = hub.subscribe()
        await session.start_live("tiny_two_failure.json", None, 40.0, "even_split")
        assert sim_module.replan is even_split_replan  # window open
        while session.sim_time is None or session.sim_time < 2.0:
            await asyncio.wait_for(q.get(), 10.0)
        await session.inject_failure("SAT-3", "THRUSTER_OUT")  # SAT-3 = sat idx 2
        assert sim_module.replan is even_split_replan  # still open after recompute
        await session.set_speed(SPEED_MAX)  # drain the rest instantly
        await _drain_until_run_complete(q, timeout=30.0)
        methods = {
            line["event"]["payload"]["method"]
            for line in _source_lines(session)
            if (line.get("event") or {}).get("type") == "ASSIGNMENT"
        }
        await session.reset()
        assert sim_module.replan is allocate.replan  # window closed, core restored
        return methods

    methods = asyncio.run(main())
    assert "even_split" in methods  # recomputed run replanned under the policy


def test_policy_wire_echo_default_and_replay(tmp_path, monkeypatch):
    """Wire echo contract over HTTP+WS: live default -> hello carries
    "policy": "hungarian" while sim_states stay key-free (deviation-only echo);
    replay -> the key is OMITTED everywhere (unknown, not fabricated).

    Ordering note (section 9.5): hub messages published before any WS client
    subscribes go to zero queues, so each stream is read from a client that
    connected BEFORE the load/start that produces it (the test_ws_two_clients
    pattern). A first subscriber-less run flips the session state so the next
    connect's hello carries it without racing the driver."""
    import cubesat.api

    write_tiny_scenario(tmp_path / "scenarios")
    write_log(tmp_path / "logs", "tiny.jsonl", tiny_log_lines())
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(cubesat.api, "_MIN_EMIT_INTERVAL", 0.0)

    r = client.post("/simulation/start", json={"speed": SPEED_MAX})
    assert r.status_code == 200
    assert r.json()["policy"] == "hungarian"  # default start echoes the default

    with client.websocket_connect("/ws/state") as ws:
        hello = ws.receive_json()  # session still holds the first run's state
        assert hello["type"] == "hello" and hello["mode"] == "live"
        assert hello["policy"] == "hungarian"
        snap = ws.receive_json()
        assert snap["type"] == "sim_state"
        assert "policy" not in snap  # deviation-only echo on sim_state

        # a second start streams to the CONNECTED client. Run it at a slow wall
        # speed and read two live frames, then reset: with the default policy
        # NO sim_state carries a policy key (deviation-only echo; default wire
        # bytes stay pinned). No dependence on the run finishing under the
        # reader -- at SPEED_MAX the run completes before any read can win.
        assert client.post("/simulation/reset").status_code == 200
        assert client.post("/simulation/start", json={"speed": 2.0}).status_code == 200
        got = 0
        while got < 2:
            m = ws.receive_json()
            if m["type"] == "sim_state":
                assert "policy" not in m  # deviation-only echo on sim_state
                got += 1
        assert client.post("/simulation/reset").status_code == 200

    # replay: first load flips the session to replay mode (its stream has no
    # subscriber), then the connect's hello must OMIT policy -- unknown, not claimed
    assert client.post("/simulation/reset").status_code == 200
    load = client.post("/replay/load", json={"filename": "tiny.jsonl", "speed": SPEED_MAX})
    assert load.status_code == 200
    with client.websocket_connect("/ws/state") as ws2:
        hello = ws2.receive_json()
        assert hello["mode"] == "replay"
        assert "policy" not in hello  # unknown for replay: omitted, not fabricated
        snap = ws2.receive_json()
        assert "policy" not in snap

        # a second load streams to the connected client: same slow-speed pattern,
        # assert the streamed replay sim_states carry no policy key either.
        assert client.post("/simulation/reset").status_code == 200
        load = client.post("/replay/load", json={"filename": "tiny.jsonl", "speed": 2.0})
        assert load.status_code == 200
        got = 0
        while got < 2:
            m = ws2.receive_json()
            if m["type"] == "sim_state":
                assert "policy" not in m
                got += 1
        assert client.post("/simulation/reset").status_code == 200
