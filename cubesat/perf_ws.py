"""Websocket throughput for `--mode perf` (cubesat/perf_bench.py): a real uvicorn on an ephemeral
port plus a `websockets` client, POST /simulation/start at each speed, count what arrives."""

from __future__ import annotations

import asyncio
import json
import statistics
import threading
import time
import urllib.request
from pathlib import Path

from cubesat.scenario import load_scenario
from cubesat.session import Hub, Session

_pc = time.perf_counter
_STATS_KEYS = ("first_frame_s", "start_http_returned_s", "frames_per_s", "bytes_per_s")


def stats(xs: list) -> dict:
    xs = [float(x) for x in xs if x is not None]
    if not xs:
        return {"median": None, "min": None, "max": None, "n": 0}
    r = lambda v: float(f"{v:.6g}")  # noqa: E731
    return {"median": r(statistics.median(xs)), "min": r(min(xs)), "max": r(max(xs)), "n": len(xs)}


def _post(port: int, path: str, body: dict | None = None) -> int:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body or {}).encode(), method="POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status


async def _ws_once(port: int, name: str, speed: float, window: float, frames_total: int) -> dict:
    import websockets

    async with websockets.connect(f"ws://127.0.0.1:{port}/ws/state", max_size=None) as c:
        await c.recv(), await c.recv()  # hello + snapshot
        t_post = _pc()

        async def start() -> float:  # blocks for the whole precompute: that IS the measurement
            await asyncio.to_thread(
                _post, port, "/simulation/start", {"scenario": f"{name}.json", "speed": speed})
            return _pc() - t_post

        post = asyncio.create_task(start())
        n = nbytes = 0
        first = last = last_sim = None
        while True:
            left = 600.0 if first is None else window - (_pc() - first)
            if left <= 0:
                break
            try:
                raw = await asyncio.wait_for(c.recv(), timeout=left)
            except TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("type") == "sim_state" and msg.get("sats"):
                first = first or _pc()
                last, last_sim, n, nbytes = _pc(), msg["sim_time"], n + 1, nbytes + len(raw)
            elif msg.get("type") == "run_summary":
                break
        http_back = await post
        await asyncio.to_thread(_post, port, "/simulation/reset")
    span = (last - first) if n > 1 else None
    return {
        "first_frame_s": (first - t_post) if first else None, "start_http_returned_s": http_back,
        "sim_states_received": n, "frames_total": frames_total,
        "frames_per_s": (n - 1) / span if span else None,
        "bytes_per_s": nbytes / span if span else None, "last_sim_time_s": last_sim,
    }


def websocket_section(sdir: Path, name: str, speeds, window: float, repeats: int) -> dict:
    try:
        import uvicorn

        from cubesat import api

        scn = load_scenario(sdir / f"{name}.json")
        hub = Hub()
        api._state = api.AppState(hub, Session(
            sdir, sdir / "logs", hub, min_emit_interval=api._MIN_EMIT_INTERVAL))
        server = uvicorn.Server(uvicorn.Config(
            api.app, host="127.0.0.1", port=0, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        total = int(round(scn.duration_s / scn.dt_s)) + 1
        runs = []
        try:
            for speed in speeds:
                raw = [asyncio.run(_ws_once(port, name, speed, window, total))
                       for _ in range(repeats)]
                med = {k: stats([r[k] for r in raw]) for k in _STATS_KEYS}
                got = statistics.median(r["sim_states_received"] for r in raw)
                runs.append({"speed": speed, "frames_total": total,
                             "sim_states_received": int(got), **med, "repeats_raw": raw})
        finally:
            server.should_exit = True
            thread.join(30)
            api._state = None
        return {"feasible": True, "scenario": name, "window_s": window, "runs": runs,
                "method": "uvicorn thread on 127.0.0.1:<ephemeral>, websockets asyncio client, "
                          "POST /simulation/start with the speed, default 30 Hz emit cap"}
    except Exception as exc:  # noqa: BLE001 -- feasibility is the question, never crash the report
        return {"feasible": False, "reason": f"{type(exc).__name__}: {exc}"}
