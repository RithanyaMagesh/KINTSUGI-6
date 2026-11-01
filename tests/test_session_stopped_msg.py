"""Reset visibility (B-19): viewers learn that the run was reset/stopped."""

from __future__ import annotations

import asyncio

from conftest import drain, make_session, write_scenario

SPEED_MAX = 1e6


def test_reset_publishes_stopped_to_viewers(tmp_path):
    write_scenario(tmp_path, "a.json", name="a")

    async def main():
        hub, session = make_session(tmp_path)
        q = hub.subscribe()
        await session.start_live("a.json", None, SPEED_MAX)
        drain(q)
        await session.reset()
        msgs = drain(q)
        assert [m["type"] for m in msgs] == ["hello", "sim_state"]
        assert msgs[0]["mode"] == "stopped" and msgs[0]["scenario"] is None
        assert msgs[1]["sats"] == [] and msgs[1]["sim_time"] == 0.0
        await session.reset()  # already stopped: nothing new to announce
        assert drain(q) == []

    asyncio.run(main())
