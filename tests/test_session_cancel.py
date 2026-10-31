"""Abandoned compute threads are cancelled (audit B-5): reset, a superseded
start, a replaced inject, a client abort and shutdown all set the cancel Event
of the in-flight run_scenario thread."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from conftest import make_session, write_scenario

from cubesat.session import SessionError
from cubesat.sim import RunCancelled

# ---- item 2: cancel abandoned work ----------------------------------------


def _blocking_run(started: threading.Event, seen: list, exited: threading.Event):
    def run(scenario, cancel_event=None):
        seen.append(cancel_event)
        started.set()
        try:
            if cancel_event.wait(5.0):
                raise RunCancelled("cancelled")
            raise AssertionError("cancel event never set: orphan thread")
        finally:
            exited.set()

    return run


def test_reset_cancels_in_flight_start(tmp_path, monkeypatch):
    write_scenario(tmp_path, "a.json", name="a")
    started, exited, seen = threading.Event(), threading.Event(), []
    monkeypatch.setattr(
        "cubesat.session.run_scenario", _blocking_run(started, seen, exited)
    )

    async def main():
        _, session = make_session(tmp_path)
        start = asyncio.create_task(session.start_live("a.json", None, 1.0))
        while not started.is_set():
            await asyncio.sleep(0.01)
        t0 = time.monotonic()
        await session.reset()
        assert time.monotonic() - t0 < 2.0
        assert seen[0].is_set()
        assert exited.wait(2.0), "compute thread still running after reset"
        with pytest.raises(SessionError) as exc:
            await start
        assert exc.value.status_code == 409
        assert session.mode == "stopped" and session._source is None

    asyncio.run(main())


def test_shutdown_and_abort_cancel_in_flight_start(tmp_path, monkeypatch):
    write_scenario(tmp_path, "a.json", name="a")
    started, exited, seen = threading.Event(), threading.Event(), []
    monkeypatch.setattr(
        "cubesat.session.run_scenario", _blocking_run(started, seen, exited)
    )

    async def main():
        _, session = make_session(tmp_path)
        start = asyncio.create_task(session.start_live("a.json", None, 1.0))
        while not started.is_set():
            await asyncio.sleep(0.01)
        session.shutdown()
        assert seen[0].is_set()
        assert exited.wait(2.0)
        with pytest.raises(SessionError):
            await start
        # client abort (task cancelled) also stops the thread
        started.clear(), exited.clear(), seen.clear()
        start = asyncio.create_task(session.start_live("a.json", None, 1.0))
        while not started.is_set():
            await asyncio.sleep(0.01)
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start
        assert seen[0].is_set()
        assert exited.wait(2.0)
        assert session.mode == "stopped"  # no zombie "live" session without a source

    asyncio.run(main())


def test_replaced_inject_is_cancelled(tmp_path, monkeypatch):
    write_scenario(tmp_path, "a.json", name="a")
    seen, started, exited = [], threading.Event(), threading.Event()

    def blocking_wf(cls, base, sat, mode, t_now, degrade_s=0.0, cancel_event=None):
        seen.append(cancel_event)
        started.set()
        try:
            if cancel_event.wait(5.0):
                raise RunCancelled("cancelled")
        finally:
            exited.set()

    async def main():
        _, session = make_session(tmp_path)
        await session.start_live("a.json", None, 1.0)
        await session.pause()
        monkeypatch.setattr("cubesat.session.LiveSource.with_failure", classmethod(blocking_wf))
        inj = asyncio.create_task(session.inject_failure("SAT-1", "DEAD"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        t0 = time.monotonic()
        await session.reset()
        assert time.monotonic() - t0 < 2.0  # not parked behind the 5 s blocker
        assert seen[0].is_set() and exited.wait(2.0)
        with pytest.raises(SessionError) as exc:
            await inj
        assert exc.value.status_code == 409

    asyncio.run(main())


def test_app_shutdown_cancels_session(monkeypatch):
    """The API lifespan teardown calls Session.shutdown (SIGTERM must not wait
    for an abandoned compute)."""
    from fastapi.testclient import TestClient

    import cubesat.api
    from cubesat.session import Session

    calls = []
    monkeypatch.setattr(Session, "shutdown", lambda self: calls.append(self))
    cubesat.api._state = None
    with TestClient(cubesat.api.app):
        pass
    assert len(calls) == 1
    cubesat.api._state = None
