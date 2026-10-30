"""Tests for live telemetry ingestion, network security, and formation fitting.

Covers SSRF prevention, strict redirects, credential redaction, stream deadlines,
atomic cache management, OMM parsing, Kepler/Brouwer numerics, ellipse fitting,
and scenario generation under strict network isolation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from cubesat._live_network import (
    CacheManager,
    StrictRedirectHandler,
    download_stream,
    sanitize_url,
    validate_request_url,
)
from cubesat.live_import import (
    advance_brouwer_j2,
    build_scenario_payload,
    fit_passive_ellipse,
    keplerian_to_eci,
    parse_omm_records,
    solve_kepler,
)
from cubesat.live_import import (
    main as live_import_main,
)
from cubesat.scenario import Scenario

ROOT = Path(__file__).resolve().parents[1]
GRACEFO_OMM = ROOT / "data" / "celestrak" / "gracefo_omm.json"


@pytest.fixture(autouse=True)
def guard_no_network(monkeypatch):
    """Enforce absolute network isolation across all live import unit tests."""

    def _block(*args, **kwargs):
        raise RuntimeError("Network access forbidden in unit tests")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", _block)
    monkeypatch.setattr("socket.socket.connect", _block)


def test_network_url_validation_ssrf():
    with pytest.raises(ValueError, match="insecure scheme"):
        validate_request_url("http://celestrak.org/elements/gp.php")
    with pytest.raises(ValueError, match="Userinfo"):
        validate_request_url("https://user:pass@celestrak.org/elements")
    with pytest.raises(ValueError, match="not in ALLOWED_HOSTS"):
        validate_request_url("https://malicious-domain.com/data")
    with pytest.raises(ValueError, match="Non-standard HTTPS port"):
        validate_request_url("https://celestrak.org:8443/data")
    validate_request_url("https://celestrak.org/NORAD/elements/gp.php?NAME=GRACE-FO")


def test_network_strict_redirect_handler():
    handler = StrictRedirectHandler()
    req = MagicMock()
    with pytest.raises(ValueError, match="SSRF"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://celestrak.org/safe")
    with pytest.raises(ValueError, match="SSRF"):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.org/steal")


def test_network_credential_redaction():
    leak_url = "https://user:secret@api.n2yo.com/rest/v1/satellite/tle/25544&apiKey=secret123"
    sanitized = sanitize_url(leak_url)
    assert "secret123" not in sanitized
    assert "[REDACTED]" in sanitized
    assert "user" not in sanitized and "secret@" not in sanitized


def test_network_stream_limits_and_timeout(monkeypatch):
    class MockResp:
        def __init__(self, headers, chunks):
            self.headers = headers
            self.chunks = list(chunks)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            return self.chunks.pop(0) if self.chunks else b""

    class MockOpener:
        def __init__(self, resp):
            self.resp = resp

        def open(self, req, timeout=10.0):
            return self.resp

    # Content-Length check
    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *args: MockOpener(MockResp({"Content-Length": "6000000"}, [])),
    )
    with pytest.raises(ValueError, match="Payload size"):
        download_stream("https://celestrak.org/data")

    # Streaming byte limit check
    large_chunk = b"X" * (6 * 1024 * 1024)
    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *args: MockOpener(MockResp({}, [large_chunk])),
    )
    with pytest.raises(ValueError, match="exceeded 5242880 bytes"):
        download_stream("https://celestrak.org/data")

    # Cumulative timeout check
    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *args: MockOpener(MockResp({}, [b"data", b"more"])),
    )
    t = [100.0]

    def _advancing_clock():
        t[0] += 50.0
        return t[0]

    monkeypatch.setattr("time.monotonic", _advancing_clock)
    with pytest.raises(TimeoutError, match="Cumulative response read timeout"):
        download_stream("https://celestrak.org/data", cumulative_timeout_s=10.0)


def test_cache_manager_atomic_and_symlinks(tmp_path):
    cm = CacheManager(tmp_path, ttl_s=3600)
    p = cm.get_cache_path("celestrak", "GRACE-FO")
    cm.write_atomic(p, [{"NORAD_CAT_ID": 43476}])
    assert p.is_file() and cm.is_valid(p)
    recs, ft = cm.read(p)
    assert recs[0]["NORAD_CAT_ID"] == 43476 and ft is not None

    sym = tmp_path / "sym_link.json"
    try:
        sym.symlink_to(p)
        assert not cm.is_valid(sym)
        with pytest.raises(ValueError, match="symlink"):
            cm.read(sym)
    except (OSError, NotImplementedError):
        pass


def test_cli_path_confinement_traversal(capsys):
    with pytest.raises(SystemExit) as exc:
        live_import_main(["--out", "../../outside_repo.json"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "refusing" in err and "outside repo" in err


def test_omm_parser_numerics_and_gates():
    raw = json.loads(GRACEFO_OMM.read_text(encoding="utf-8"))
    elems = parse_omm_records(raw)
    assert len(elems) == 2 and elems[0]["norad"] == 43476
    str_raw = [{k: str(v) for k, v in raw[0].items()}]
    assert parse_omm_records(str_raw)[0]["norad"] == 43476

    with pytest.raises(ValueError, match="(?i)eccentricity"):
        parse_omm_records([{**raw[0], "ECCENTRICITY": 1.05}])
    with pytest.raises(ValueError, match="altitude"):
        parse_omm_records([{**raw[0], "MEAN_MOTION": 1.0}])
    with pytest.raises(ValueError, match="finite"):
        parse_omm_records([{**raw[0], "INCLINATION": float("nan")}])


def test_kepler_solver_convergence_and_limits():
    assert solve_kepler(0.0, 0.0) == 0.0
    e = 0.005
    M = math.pi / 3
    E = solve_kepler(M, e)
    assert abs(E - e * math.sin(E) - M) < 1e-12
    with pytest.raises(ValueError, match="invalid e"):
        solve_kepler(M, 1.2)


def test_brouwer_j2_secular_propagation():
    elems = parse_omm_records(json.loads(GRACEFO_OMM.read_text(encoding="utf-8")))
    adv, dt = advance_brouwer_j2(elems)
    assert len(adv) == 2
    assert adv[0]["delta_epoch_s"] != 0.0
    assert adv[0]["delta_epoch_s"] == pytest.approx(-adv[1]["delta_epoch_s"], abs=1e-3)
    assert dt != 0.0
    r, v = keplerian_to_eci(adv[0])
    assert np.linalg.norm(r) > 6.0e6
    assert np.linalg.norm(v) > 7.0e3


def test_ellipse_fitting_phase_presorting():
    phases = np.linspace(0, 2 * math.pi, 6, endpoint=False)
    pts = np.column_stack([2000.0 * np.cos(phases), 4000.0 * np.sin(phases), np.zeros(6)])
    amp, psi0 = fit_passive_ellipse(pts)
    assert amp == pytest.approx(2000.0, rel=1e-3)
    shuffled = pts.copy()
    np.random.default_rng(42).shuffle(shuffled)
    amp_shuf, _ = fit_passive_ellipse(shuffled)
    assert amp_shuf == pytest.approx(2000.0, rel=1e-3)


def test_small_cluster_swarm_expansion_and_hungarian():
    elems = parse_omm_records(json.loads(GRACEFO_OMM.read_text(encoding="utf-8")))
    adv, _ = advance_brouwer_j2(elems)
    rc, vc = keplerian_to_eci(adv[0])
    xh = rc / np.linalg.norm(rc)
    zh = np.cross(rc, vc) / np.linalg.norm(np.cross(rc, vc))
    yh = np.cross(zh, xh)
    lvlh = np.array([
        [float(np.dot(r - rc, ax)) for ax in (xh, yh, zh)]
        for r, _ in (keplerian_to_eci(el) for el in adv)
    ])
    scen, meta = build_scenario_payload(
        adv[0], adv, lvlh, n_swarm=6, n_failures=2, amp_m=8000.0, psi_0=0.0,
        seed=42, duration=100.0, dt=2.0,
    )
    assert scen["formation"]["n_slots"] == 6
    assert len(scen["roles"]) == 6
    assert len(meta["cluster_members"]) == 2
    Scenario.model_validate(scen)


def test_cli_live_import_offline_replay(tmp_path):
    out_scen = tmp_path / "live_replay.json"
    meta_scen = tmp_path / "live_replay.meta.json"
    ret = live_import_main([
        "--cluster", "GRACE-FO",
        "--fit-mode", "safe-envelope",
        "--out", str(out_scen.relative_to(ROOT)),
        "--meta-out", str(meta_scen.relative_to(ROOT)),
        "--offline",
    ])
    assert ret == 0
    scen = Scenario.model_validate(json.loads(out_scen.read_text(encoding="utf-8")))
    assert scen.formation.radial_amp_km == 8.0
    assert out_scen.exists() and meta_scen.exists()
