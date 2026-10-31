"""Laser (optical) inter-satellite links: link budget, acquisition state machine, topology.

Pure, deterministic, SI. Not wired into the engines yet (track C plan, step C2).

Physics (order-of-magnitude, far-field, diffraction-limited apertures):
  G = (pi D / lambda)^2                      aperture gain (tx and rx)
  L_fs = (lambda / (4 pi R))^2               free-space loss
  L_p = exp(-G_tx * e^2)                     Gaussian pointing loss, e = pointing error, rad
  P_rx = P_tx G_tx G_rx L_fs L_p eta
  rate = min(P_rx / (h c / lambda) / photons_per_bit, max_rate)
Defaults are CLICK-class (MIT/NASA CLICK-B/C: 1.5U, ~200 mW EDFA, 1537/1563 nm, >20 Mbps
crosslink at 25-580 km). Apertures, photons_per_bit, acquire_s and sun_exclusion_rad are
ASSUMPTIONS for this simulator, not hardware figures; every report must say so.

The point the model makes: at formation ranges (km) the budget closes by tens of dB, the link is
limited by POINTING (a 2 cm aperture beam is ~50 urad wide; CubeSat body pointing is ~1e-3 rad) and
by being point-to-point (one terminal = one partner, each new partner costs an acquisition).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

H_PLANCK = 6.62607015e-34
C_LIGHT = 299_792_458.0

DOWN, ACQUIRING, LOCKED = "DOWN", "ACQUIRING", "LOCKED"


@dataclass(frozen=True)
class Terminal:
    wavelength_m: float = 1.55e-6
    p_tx_w: float = 0.2
    d_tx_m: float = 0.02  # assumption
    d_rx_m: float = 0.02  # assumption
    eta: float = 0.3  # optics x detector efficiency, assumption
    photons_per_bit: float = 300.0  # receiver sensitivity, assumption
    max_rate_bps: float = 20e6  # modem cap, CLICK-class
    pointing_error_rad: float = 5e-6  # with a fine steering mirror, assumption
    acquire_s: float = 30.0  # beacon acquisition + fine lock, assumption
    sun_exclusion_rad: float = math.radians(3.0)  # assumption
    terminals_per_sat: int = 2


def gain(d_m: float, wavelength_m: float) -> float:
    return (math.pi * d_m / wavelength_m) ** 2


def received_power_w(range_m: float, term: Terminal, pointing_error_rad: float | None = None):
    """Received optical power, W. Raises ValueError for range <= 0."""
    if range_m <= 0.0:
        raise ValueError("range must be > 0")
    e = term.pointing_error_rad if pointing_error_rad is None else pointing_error_rad
    g_tx = gain(term.d_tx_m, term.wavelength_m)
    g_rx = gain(term.d_rx_m, term.wavelength_m)
    l_fs = (term.wavelength_m / (4.0 * math.pi * range_m)) ** 2
    return term.p_tx_w * g_tx * g_rx * l_fs * math.exp(-g_tx * e * e) * term.eta


def data_rate_bps(range_m: float, term: Terminal, pointing_error_rad: float | None = None):
    p = received_power_w(range_m, term, pointing_error_rad)
    photon_rate = p / (H_PLANCK * C_LIGHT / term.wavelength_m)
    return min(photon_rate / term.photons_per_bit, term.max_rate_bps)


def margin_db(range_m: float, term: Terminal, pointing_error_rad: float | None = None) -> float:
    """Link margin vs the power needed for max_rate_bps, dB (>= 0: runs at the cap)."""
    need = term.max_rate_bps * term.photons_per_bit * H_PLANCK * C_LIGHT / term.wavelength_m
    p = received_power_w(range_m, term, pointing_error_rad)
    return -math.inf if p <= 0.0 else 10.0 * math.log10(p / need)


def beam_halfwidth_rad(term: Terminal) -> float:
    """Pointing error at which the pointing loss reaches 1/e (sqrt(1/G_tx))."""
    return 1.0 / math.sqrt(gain(term.d_tx_m, term.wavelength_m))


def sun_blinded(los: np.ndarray, sun_unit: np.ndarray, term: Terminal) -> bool:
    """True if the sun is within the exclusion cone around the receive line of sight."""
    c = float(np.dot(los, sun_unit) / (np.linalg.norm(los) * np.linalg.norm(sun_unit)))
    return c >= math.cos(term.sun_exclusion_rad)


def step_link(state: str, timer_s: float, usable: bool, dt: float, term: Terminal):
    """One tick of a link's state machine -> (state, timer_s).

    DOWN -> ACQUIRING when usable; ACQUIRING -> LOCKED after acquire_s of continuous use;
    any state -> DOWN the tick it becomes unusable (partner dead, out of budget, sun)."""
    if not usable:
        return DOWN, 0.0
    if state == LOCKED:
        return LOCKED, 0.0
    t = (timer_s if state == ACQUIRING else 0.0) + dt
    return (LOCKED, 0.0) if t >= term.acquire_s else (ACQUIRING, t)


def plan_topology(
    pos: np.ndarray, alive: list[bool], term: Terminal, keep: set | None = None
) -> set[tuple[int, int]]:
    """Point-to-point link set (i < j) under a per-sat terminal cap.

    Links in `keep` (already acquired) that are still alive and closeable are kept first, so a
    replan does not drop working links (each new link costs acquire_s). Then shortest-range-first
    greedy, ties by (i, j): deterministic. pos: (n, 3) LVLH positions, m."""
    n = len(alive)
    deg = [0] * n
    chosen: set[tuple[int, int]] = set()

    def ok(i: int, j: int) -> bool:
        r = float(np.linalg.norm(pos[i] - pos[j]))
        return (
            alive[i] and alive[j] and r > 0.0 and margin_db(r, term) >= 0.0
            and deg[i] < term.terminals_per_sat and deg[j] < term.terminals_per_sat
        )

    cands = sorted(
        ((float(np.linalg.norm(pos[i] - pos[j])), i, j) for i in range(n) for j in range(i + 1, n)),
    )
    for first in (True, False):
        for _, i, j in cands:
            if (i, j) in chosen or (first and (i, j) not in (keep or set())):
                continue
            if ok(i, j):
                chosen.add((i, j))
                deg[i] += 1
                deg[j] += 1
    return chosen


def star_topology(hub: int, n: int) -> set[tuple[int, int]]:
    """The centralised layout: every sat links to the hub (needs n-1 terminals on the hub)."""
    return {(min(hub, j), max(hub, j)) for j in range(n) if j != hub}


def components(n: int, links: set[tuple[int, int]], alive: list[bool]) -> list[list[int]]:
    """Connected components among alive sats (sorted, deterministic)."""
    adj = {i: [] for i in range(n)}
    for i, j in links:
        if alive[i] and alive[j]:
            adj[i].append(j)
            adj[j].append(i)
    seen, out = set(), []
    for s in range(n):
        if not alive[s] or s in seen:
            continue
        comp, q = [], deque([s])
        seen.add(s)
        while q:
            u = q.popleft()
            comp.append(u)
            for v in sorted(adj[u]):
                if v not in seen:
                    seen.add(v)
                    q.append(v)
        out.append(sorted(comp))
    return out
