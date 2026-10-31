"""Engine v2: stepper-native truth-dynamics loop (ECI two-body + J2 + drag, RK4).

Log schema = cubesat/sim.py (v1) plus optional keys (`events`, INIT `engine`). Phase 1 scope:
truth propagation, v1 PDController seat holding on the LVLH state (until Phase 5), failures coast
in the truth model (DEAD = tumbling area), v1-style heartbeat detection, NO recovery.
Contract: EngineV2(scenario, injections) replayed from t=0 gives the identical log.
"""

from __future__ import annotations

import math
import pickle
import threading
from collections.abc import Iterator

import numpy as np

from cubesat import truth
from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.hcw import mean_motion, stm
from cubesat.pd import PDController
from cubesat.scenario import Failure, FailureMode, Scenario
from cubesat.sim import (
    LOG_SCHEMA_VERSION,
    STATE_FAILURE_DETECTED,
    STATE_INIT,
    STATE_NOMINAL,
    STATE_SUMMARY,
    STATUS_DEAD,
    STATUS_DEGRADED,
    STATUS_NOMINAL,
    STATUS_THRUSTER_OUT,
    RunCancelled,
    build_slots,
)

# Draw-order table (docs/PHYSICS_V2.md). Row positions are fixed: new draws are APPENDED,
# never inserted; conditional rows (4, 6, 7) come after the tick's unconditional ones.
DRAW_ORDER: tuple[str, ...] = (
    "heartbeat_loss",  # 1 rng.random()            Phase 4, every sat every tick
    "measurement_noise",  # 2 rng.standard_normal(6) Phase 4, every sat every tick
    "seu",  # 3 rng.random()                        Phase 3, every sat every tick
    "seu_duration",  # 4 rng.uniform(30, 120)        Phase 3, only on an SEU hit
    "impact",  # 5 rng.random()                      Phase 3, every sat every tick
    "impact_component",  # 6 rng.random()            Phase 3, only on an impact hit
    "impact_fraction",  # 7 rng.uniform(0.2, 0.6)    Phase 3, only on an impact hit
)


def make_rng(scenario: Scenario) -> np.random.Generator:
    """The one sim-owned Generator (v1 never touches it; the seed stays write-only there)."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(scenario.seed)))


def draw_tick(rng: np.random.Generator, n_sats: int) -> dict[str, np.ndarray]:
    """One tick's unconditional rows (1, 2, 3, 5) per sat in ascending id.

    Phases 3-4 are not implemented yet: the values are drawn and ignored so a later phase
    changes no stream position (tests/v2/test_draw_order.py)."""
    hb, seu, imp = np.empty(n_sats), np.empty(n_sats), np.empty(n_sats)
    noise = np.empty((n_sats, 6))
    for i in range(n_sats):
        hb[i] = rng.random()
        noise[i] = rng.standard_normal(6)
        seu[i] = rng.random()
        imp[i] = rng.random()
    return {"heartbeat_u": hb, "noise": noise, "seu_u": seu, "impact_u": imp}


def consume_reserved(rng: np.random.Generator, n_sats: int) -> None:
    """No-op consumer of the reserved rows (Phases 3-4 replace it)."""
    draw_tick(rng, n_sats)



_STATE = ("k", "X", "refs", "dv", "status", "missed", "declared", "t_fail", "fail_mode",
          "mission", "pending", "fired", "injections", "cov")  # fmt: skip


class EngineV2:
    """Stepper-native v2 engine: step() -> one tick line; inject(); snapshot()/restore(); run()."""
    def __init__(
        self,
        scenario: Scenario,
        injections: list[Failure] = (),
        initial_lvlh: np.ndarray | None = None,
    ) -> None:
        """initial_lvlh (N, 6) overrides the start states (validation hook; seat references
        stay the formation slots). Default: sat i starts on slot i, as v1."""
        self.scenario = scenario
        self.dt = scenario.dt_s
        self.n_sats = scenario.n_sats
        alt = scenario.chief.altitude_km * 1000.0
        self.n = mean_motion(alt)
        self.n_ticks = int(round(scenario.duration_s / self.dt)) + 1
        slots = np.array(build_slots(scenario, self.n))
        chief = truth.chief_initial(alt, scenario.chief.inclination_deg, scenario.chief.raan_deg)
        start = slots if initial_lvlh is None else np.asarray(initial_lvlh, dtype=float)
        r0, v0 = truth.lvlh_to_eci(start, chief[:3], chief[3:])
        self.X = np.vstack([chief, np.hstack([r0, v0])])  # row 0 = virtual chief (no drag)
        self.refs = slots.copy()  # seat references, advanced by the cached Phi(dt)
        self.phi_dt = stm(self.dt, self.n)  # cached once; G(dt) comes with the LP (Ph. 5)
        self.pd = PDController(scenario.gains.wn, scenario.gains.zeta, scenario.a_max_mps2)
        tr = scenario.truth
        self._b = {s: tr.cd * a / tr.mass_kg for s, a in (("act", tr.area_active_m2),
                                                          ("dead", tr.area_dead_m2))}  # fmt: skip
        self.r_f = footprint_radius(alt, math.radians(scenario.sensor.fov_half_angle_deg))
        self.grid = target_grid(scenario.sensor.grid_step_km * 1000.0,
                                scenario.sensor.grid_extent_km * 1000.0)  # fmt: skip
        self.rng = make_rng(scenario)
        self.k = 0
        self.dv = np.zeros(self.n_sats)
        self.status = [STATUS_NOMINAL] * self.n_sats
        self.missed = [0] * self.n_sats
        self.declared = [False] * self.n_sats
        self.t_fail = [0.0] * self.n_sats
        self.fail_mode = [""] * self.n_sats
        self.mission = STATE_NOMINAL
        self.injections: list[Failure] = []
        self.pending = sorted(scenario.failures, key=lambda f: (f.t, f.sat_id))
        self.fired = 0
        for f in injections:
            self.inject(f)
        self.cov: list[tuple[float, float]] = []

    def header(self) -> dict:
        s = self.scenario
        return {"v": LOG_SCHEMA_VERSION, "t": 0.0, "state": STATE_INIT, "scenario": s.name,
                "seed": s.seed, "n_sats": s.n_sats, "engine": "v2"}  # fmt: skip

    def inject(self, failure: Failure) -> None:
        """Apply `failure` at the current tick (a past time is clamped to now) and record it."""
        if failure.sat_id >= self.n_sats:
            raise ValueError(f"sat_id={failure.sat_id}, only {self.n_sats} sats exist")
        now = self.k * self.dt
        if failure.t < now:
            failure = failure.model_copy(update={"t": now})
        self.injections.append(failure)
        rest = [*self.pending[self.fired :], failure]  # stable: scenario failures stay first
        self.pending, self.fired = sorted(rest, key=lambda f: (f.t, f.sat_id)), 0

    def step(self) -> dict:
        """Process tick k (failures, detection, log line), then advance the truth state by dt."""
        if self.k >= self.n_ticks:
            raise RuntimeError("run finished")
        t = self.k * self.dt
        events = self._failures_and_detection(t)
        consume_reserved(self.rng, self.n_sats)  # Phases 3-4 draw rows, ignored for now
        lvlh = truth.eci_to_lvlh(self.X[1:, :3], self.X[1:, 3:], self.X[0, :3], self.X[0, 3:])
        imagers = [i for i, role in enumerate(self.scenario.roles)
                   if role == "imager" and self.status[i] != STATUS_DEAD]  # fmt: skip
        cov = coverage_fraction(lvlh[imagers, 1:3], self.grid, self.r_f)
        d = lvlh[:, None, :3] - lvlh[None, :, :3]
        min_sep = float(np.sqrt(np.min((d**2).sum(-1)[np.triu_indices(self.n_sats, 1)])))
        line = {
            "v": LOG_SCHEMA_VERSION, "t": t, "state": self.mission,
            "sats": [{"id": i, "role": self.scenario.roles[i], "status": self.status[i],
                      "r": lvlh[i, :3].tolist(), "v": lvlh[i, 3:].tolist(),
                      "dv_used": float(self.dv[i])} for i in range(self.n_sats)],
            "coverage": cov, "min_sep": min_sep,
        }  # fmt: skip
        if events:
            line["event"], line["events"] = events[0], events
        self.cov.append((t, cov))
        self._advance(lvlh)
        self.k += 1
        return line

    def run(self, cancel_event: threading.Event | None = None) -> Iterator[dict]:
        """Yield [header (k == 0 only), ticks..., SUMMARY]; RunCancelled between ticks."""
        if self.k == 0:
            yield self.header()
        while self.k < self.n_ticks:
            if cancel_event is not None and cancel_event.is_set():
                raise RunCancelled(f"run cancelled before tick {self.k}")
            yield self.step()
        window = self.scenario.duration_s - 2.0 * math.pi / self.n
        tail = [c for (t, c) in self.cov if t >= window - 1e-9]
        yield {"v": LOG_SCHEMA_VERSION, "t": self.cov[-1][0], "state": STATE_SUMMARY,
               "coverage_mean_last_orbit": sum(tail) / len(tail)}  # fmt: skip

    def snapshot(self) -> bytes:
        """Full state incl. Generator state (pickle: restore only your own blobs)."""
        state = {name: getattr(self, name) for name in _STATE}
        return pickle.dumps((state, self.rng.bit_generator.state), protocol=4)

    def restore(self, blob: bytes) -> None:
        state, rng_state = pickle.loads(blob)  # noqa: S301 (own snapshots only)
        for name, value in state.items():
            setattr(self, name, value)
        self.rng.bit_generator.state = rng_state

    def _failures_and_detection(self, t: float) -> list[dict]:
        events: list[dict] = []
        sc = self.scenario
        for f in sc.failures + self.injections:  # EPS_DEGRADE fade onset: DEGRADED, still holding
            if (f.mode == FailureMode.EPS_DEGRADE and f.degrade_s > 0
                    and max(f.t - f.degrade_s, 0.0) <= t + 1e-9
                    and self.status[f.sat_id] == STATUS_NOMINAL and f.t > t + 1e-9):  # fmt: skip
                self.status[f.sat_id] = STATUS_DEGRADED
                events.append({"type": "DEGRADE_START", "payload": {
                    "sat_id": f.sat_id, "t_fail": f.t, "degrade_s": f.degrade_s}})  # fmt: skip
        while self.fired < len(self.pending) and self.pending[self.fired].t <= t + 1e-9:
            f = self.pending[self.fired]
            self.fired += 1
            i = f.sat_id
            if self.status[i] == STATUS_DEAD:
                continue
            thr = f.mode == FailureMode.THRUSTER_OUT
            self.status[i] = STATUS_THRUSTER_OUT if thr else STATUS_DEAD
            self.t_fail[i], self.fail_mode[i] = f.t, f.mode.value
            if thr:  # self-reported, like v1
                self.mission = STATE_FAILURE_DETECTED
                events.append({"type": "FAILURE_DETECTED", "payload": {
                    "sat_id": i, "mode": f.mode.value, "t_fail": f.t, "t_detect": t,
                    "self_report": True}})  # fmt: skip
        for i in range(self.n_sats):  # heartbeat: only DEAD sats are silent
            self.missed[i] = self.missed[i] + 1 if self.status[i] == STATUS_DEAD else 0
            if (self.status[i] == STATUS_DEAD and not self.declared[i]
                    and self.missed[i] >= sc.detection.missed_ticks_k):  # fmt: skip
                self.declared[i] = True
                self.mission = STATE_FAILURE_DETECTED
                events.append({"type": "FAILURE_DETECTED", "payload": {
                    "sat_id": i, "mode": self.fail_mode[i], "t_fail": self.t_fail[i],
                    "t_detect": t}})  # fmt: skip
        return events

    def _advance(self, lvlh: np.ndarray) -> None:
        """PD command per holding sat (LVLH, zero-order hold), then one batched RK4 step."""
        n_s, dt = self.n_sats, self.dt
        u = np.zeros((n_s, 3))
        for i in range(n_s):
            if self.status[i] in (STATUS_NOMINAL, STATUS_DEGRADED):
                u[i] = self.pd.command(lvlh[i, :3], lvlh[i, 3:], self.refs[i, :3], self.refs[i, 3:])
        self.dv += np.linalg.norm(u, axis=1) * dt
        a_thrust = np.vstack([np.zeros(3), u @ truth.lvlh_dcm(self.X[0, :3], self.X[0, 3:])])
        b = np.array([0.0] + [self._b["dead" if s == STATUS_DEAD else "act"] for s in self.status])
        tr = self.scenario.truth

        def accel(r, v):
            a = truth.accel_gravity(r) + truth.accel_drag(r, v, b, tr.density_factor) + a_thrust
            return a + truth.accel_j2(r) if tr.j2_enabled else a

        self.X = truth.rk4_step(self.X, dt, accel)
        self.refs = self.refs @ self.phi_dt.T


def run_scenario_v2(scenario: Scenario, cancel_event: threading.Event | None = None) -> list[dict]:
    """[INIT header, tick..., SUMMARY]; RunCancelled between ticks, no partial output."""
    return list(EngineV2(scenario).run(cancel_event))
