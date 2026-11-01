"""Validate before teardown (B-17): a bad request never clobbers the running session."""

from __future__ import annotations

import asyncio

import pytest
from conftest import make_session, write_scenario

from cubesat.session import SessionError

# ---- item 3: validate before teardown --------------------------------------


def test_invalid_requests_leave_running_session_streaming(tmp_path):
    write_scenario(tmp_path, "a.json", name="a")
    (tmp_path / "scenarios" / "broken.json").write_text("{}", encoding="utf-8")

    async def main():
        hub, session = make_session(tmp_path)
        await session.start_live("a.json", None, 1.0)
        for bad in (
            session.start_live("nope.json", None, 1.0),
            session.start_live("broken.json", None, 1.0),
            session.start_live("a.json", None, 1.0, "no_such_policy"),
            session.load_replay("nope.jsonl", 1.0),
        ):
            with pytest.raises(SessionError) as exc:
                await bad
            assert exc.value.status_code in (404, 422)
        assert session.mode == "live" and session.enrich.scenario == "a"
        assert session._driver is not None and not session._driver.done()
        t0 = session.sim_time
        await asyncio.sleep(2.5)  # speed 1: one frame (dt 2 s) is due
        assert session.sim_time > t0
        await session.reset()

    asyncio.run(main())
