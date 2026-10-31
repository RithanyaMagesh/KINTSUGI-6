"""E1 item 3: Earth-view data on the wire (sim_state chief/station, v2 hello) via a real session."""

import asyncio
import json
from pathlib import Path

from cubesat import geo_v2
from cubesat.scenario import load_scenario
from cubesat.session import Hub, Session
from cubesat.wire import SessionEnrich, to_messages

ROOT = Path(__file__).resolve().parents[2]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"
HELLO_V2_KEYS = {
    "epoch_utc", "inclination_deg", "raan_deg", "orbit_ring", "ground_track", "sun_vector_eci",
    "ground_station",
}
LINE = {
    "v": 1, "t": 4.0, "state": "NOMINAL", "coverage": 0.1, "min_sep": 100.0,
    "sats": [{"id": 0, "role": "leader", "status": "NOMINAL", "r": [1, 2, 3], "v": [0, 0, 0],
              "dv_used": 0.0}],
}
EARTH = {"chief": {"r_eci": [6878137.0, 0.0, 0.0], "lat_deg": 0.0, "lon_deg": 1.5, "alt_m": 5e5},
         "station": {"elevation_deg": -30.0, "visible": False}}


def _write_v2_scenario(tmp_path, engine="v2"):
    scn = load_scenario(TWO_FAILURE).model_copy(update={"engine": engine, "duration_s": 60.0})
    d = tmp_path / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    (d / "two_failure.json").write_text(scn.model_dump_json())
    return scn


async def _run(tmp_path, engine):
    _write_v2_scenario(tmp_path, engine)
    hub = Hub(maxsize=100_000)
    session = Session(tmp_path / "scenarios", tmp_path / "logs", hub, min_emit_interval=0.0)
    q = hub.subscribe()
    await session.start_live("two_failure.json", speed=1e6)
    msgs = []
    while True:
        m = await asyncio.wait_for(q.get(), 30)
        msgs.append(m)
        if m.get("type") == "event" and m.get("message") == "Run complete":
            return session, msgs


def test_to_messages_copies_chief_and_station_only_when_present():
    with_earth = to_messages({**LINE, **EARTH}, SessionEnrich())[0]
    assert with_earth["chief"] == EARTH["chief"] and with_earth["station"] == EARTH["station"]
    plain = to_messages(LINE, SessionEnrich())[0]
    assert "chief" not in plain and "station" not in plain


def test_v2_hello_has_all_keys_sized_json_safe_and_sim_state_carries_earth(tmp_path):
    session, msgs = asyncio.run(_run(tmp_path, "v2"))
    hello = session.hello()
    assert HELLO_V2_KEYS <= set(hello)
    assert len(hello["orbit_ring"]) == 256 and len(hello["orbit_ring"][0]) == 3
    assert len(hello["ground_track"]) == 257 and len(hello["ground_track"][0]) == 2
    assert hello["ground_station"] == {
        "name": "Bengaluru", "lat_deg": 13.03, "lon_deg": 77.51, "min_elevation_deg": 10.0
    }
    assert hello["epoch_utc"] == "2026-03-20T12:00:00Z"
    assert (hello["inclination_deg"], hello["raan_deg"]) == (97.4, 0.0)
    assert abs(sum(c * c for c in hello["sun_vector_eci"]) - 1.0) < 1e-5
    assert "time_warp" not in hello  # no existing field to carry; none invented
    text = json.dumps(hello, allow_nan=False)
    assert len(text) < 60_000
    states = [m for m in msgs if m["type"] == "sim_state" and m["sats"]]
    assert states and all("chief" in m and "station" in m for m in states)
    # hello is composed once per run: the very same objects come back
    assert session.hello()["orbit_ring"] is hello["orbit_ring"]
    # the ring is rounded to 3 decimals (mm), the track to 4
    assert all(round(c, 3) == c for p in hello["orbit_ring"] for c in p)
    assert all(round(c, 4) == c for p in hello["ground_track"] for c in p)


def test_v1_hello_and_sim_state_are_unchanged(tmp_path):
    session, msgs = asyncio.run(_run(tmp_path, "v1"))
    hello = session.hello()
    assert not (HELLO_V2_KEYS & set(hello))
    assert set(hello) == {"type", "mode", "scenario", "seed", "sim_time", "skipped", "policy"}
    assert all("chief" not in m and "station" not in m for m in msgs)


def test_hello_fields_match_helper_outputs():
    scn = load_scenario(TWO_FAILURE).model_copy(update={"engine": "v2"})
    f = geo_v2.hello_fields(scn)
    assert f["sun_vector_eci"] == [round(c, 6) for c in
                                   geo_v2.sun_direction_eci(scn.chief.epoch_utc)]
    assert f["orbit_ring"][0] == [round(c, 3) for c in geo_v2.orbit_ring(scn)[0]]
