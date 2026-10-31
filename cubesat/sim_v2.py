"""Engine v2: stepper-native truth-dynamics loop (ECI two-body + J2 + drag, RK4).

Log schema = cubesat/sim.py (v1) plus optional keys: `chief` + `station` on every tick (Earth
view, cubesat/geo_v2.py), `events` (every event of the tick), INIT `engine` and per sat
`roles` / `role` / `original_role` (cubesat/roles_v2.py, Phase 5a, plus ROLE_HANDOFF events).
Consumers that read only `frame["event"]` (wire.py, dv_bound.py) see just the FIRST of several
simultaneous events; `events` carries all of them. Phase 1 scope: truth propagation, v1
PDController seat holding on the LVLH state (until Phase 5), failures coast in the truth model
(cubesat/faults_v2.py), a re-entry guard, NO recovery.

Contract: EngineV2(scenario, injections) replayed from t=0 gives the identical log; the
injections to replay are `engine.injections` (inject() records the RESOLVED failure).
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Iterator

import numpy as np

from cubesat import comms_v2, geo_v2, truth
from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.faults_v2 import STATUS_REENTERED, Faults
from cubesat.hcw import mean_motion, stm
from cubesat.pd import PDController
from cubesat.rng_v2 import draw_tick, make_rng
from cubesat.roles_v2 import assign_roles, believe, handoff_events, imaging_sats, primary_role
from cubesat.scenario import Failure, Scenario
from cubesat.sim import (
    LOG_SCHEMA_VERSION,
    STATE_INIT,
    STATE_SUMMARY,
    STATUS_DEAD,
    RunCancelled,
    build_slots,
)
from cubesat.spacecraft import thrust_limited

REENTRY_ALTITUDE_M = 100e3  # below this a sat is flagged REENTERED and frozen


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
        self._b_active = tr.cd * tr.area_active_m2 / tr.mass_kg
        self._b_dead = tr.cd * tr.area_dead_m2 / tr.mass_kg
        self.r_f = footprint_radius(alt, math.radians(scenario.sensor.fov_half_angle_deg))
        sensor = scenario.sensor
        self.grid = target_grid(sensor.grid_step_km * 1000.0, sensor.grid_extent_km * 1000.0)
        self.rng = make_rng(scenario)
        self.k = 0
        self.dv = np.zeros(self.n_sats)
        self.hold = np.zeros((self.n_sats, 6))  # LVLH state of re-entered sats, frozen at re-entry
        self.faults = Faults(scenario)
        self.cov: list[tuple[float, float]] = []
        self.roles = [[r] for r in scenario.roles]  # holders now = incumbents (Phase 5a)
        self.believed = [["NOMINAL", True, True] for _ in scenario.roles]
        laser = scenario.comms is not None and scenario.comms.model == "laser"
        self.comms = comms_v2.CommsState(scenario) if laser else None  # track C2
        for f in injections:
            self.inject(f)

    @property
    def injections(self) -> list[Failure]:
        return self.faults.injections

    @property
    def status(self) -> list[str]:
        return self.faults.status

    def header(self) -> dict:
        s = self.scenario
        return {
            "v": LOG_SCHEMA_VERSION,
            "t": 0.0,
            "state": STATE_INIT,
            "scenario": s.name,
            "seed": s.seed,
            "n_sats": s.n_sats,
            "engine": "v2",
        }

    def inject(self, failure: Failure) -> None:
        """Apply `failure` at the current tick (past times clamp to now) and record the
        resolved failure in `injections`."""
        if self.k >= self.n_ticks:
            raise RuntimeError("run finished: cannot inject")
        self.faults.inject(failure, self.k * self.dt)

    def step(self) -> dict:
        """Process tick k (re-entry, failures, detection, log line), then advance by dt."""
        if self.k >= self.n_ticks:
            raise RuntimeError("run finished")
        t = self.k * self.dt
        c = self.X[0]
        lvlh = truth.eci_to_lvlh(self.X[1:, :3], self.X[1:, 3:], c[:3], c[3:])
        events = self._reentries(t, lvlh)  # before faults: detection reads the new status
        ev, links = comms_v2.fault_tick(self.comms, self.faults, t, self.dt, lvlh, c, self.roles,
                                        self.X[1:, 3:])  # = faults.tick() without laser comms
        events += ev
        events += self._update_roles()
        draw_tick(self.rng, self.n_sats)  # Phases 3-4 use these rows; ignored for now
        status = self.faults.status
        gone = np.array([s == STATUS_REENTERED for s in status])
        lvlh[gone] = self.hold[gone]  # a re-entered sat shows its state at re-entry
        imagers = imaging_sats(self.roles, status, self.faults.sats)  # physical, not believed
        cov = coverage_fraction(lvlh[imagers, 1:3], self.grid, self.r_f)
        line = {
            "v": LOG_SCHEMA_VERSION,
            "t": t,
            "state": self.faults.mission,
            "sats": [
                {
                    "id": i,
                    "role": primary_role(self.roles[i]),  # display label (fixed order)
                    "roles": list(self.roles[i]),
                    "original_role": self.scenario.roles[i],
                    "status": status[i],
                    "r": lvlh[i, :3].tolist(),
                    "v": lvlh[i, 3:].tolist(),
                    "dv_used": float(self.dv[i]),
                    "stuck": self.faults.sats[i].stuck_vec is not None,
                    "fuel_kg": self.faults.sats[i].m_prop_kg,
                    "fuel_mps_left": self.faults.sats[i].fuel_mps_left,
                    "k": self.faults.sats[i].k,
                    "payload_ok": self.faults.sats[i].payload_ok,
                    "radio_ok": self.faults.sats[i].radio_ok,
                }
                for i in range(self.n_sats)
            ],
            "coverage": cov,
            "min_sep": self._min_sep(lvlh[:, :3]),
            **geo_v2.tick_fields(c[:3], self.scenario.chief.epoch_utc, t),  # Earth view (v2 only)
            **links,  # laser comms only: links, components
        }
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
        yield {
            "v": LOG_SCHEMA_VERSION,
            "t": self.cov[-1][0],
            "state": STATE_SUMMARY,
            "coverage_mean_last_orbit": sum(tail) / len(tail),
        }

    # -- snapshot: JSON data (not code), guarded by a scenario fingerprint -----------------------
    def _fingerprint(self) -> dict:
        dump = self.scenario.model_dump_json(exclude_none=True)  # no `comms` key = old print
        digest = hashlib.sha256(dump.encode()).hexdigest()
        return {"scenario_sha256": digest, "n_sats": self.n_sats, "schema": LOG_SCHEMA_VERSION}

    def snapshot(self) -> bytes:
        """Full state incl. the Generator state, as JSON bytes (floats round-trip exactly)."""
        state = {
            "k": self.k,
            "X": self.X.tolist(),
            "refs": self.refs.tolist(),
            "dv": self.dv.tolist(),
            "hold": self.hold.tolist(),
            "cov": self.cov,
            "roles": self.roles,
            "believed": self.believed,
            "faults": self.faults.state(),
            "rng": self.rng.bit_generator.state,
            **({"comms": self.comms.state()} if self.comms else {}),
        }
        doc = {"fingerprint": self._fingerprint(), "state": state}
        return json.dumps(doc, sort_keys=True).encode()

    def restore(self, blob: bytes) -> None:
        try:
            doc = json.loads(blob)
            fingerprint, state = doc["fingerprint"], doc["state"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"not an EngineV2 snapshot: {exc}") from exc
        if fingerprint != self._fingerprint():
            raise ValueError("snapshot fingerprint mismatch: different scenario, n_sats or schema")
        try:  # parse everything first: a bad snapshot must leave the engine untouched
            k, X, refs = int(state["k"]), np.array(state["X"]), np.array(state["refs"])
            dv, hold = np.array(state["dv"]), np.array(state["hold"])
            cov = [(t, c) for t, c in state["cov"]]
            roles = [[str(r) for r in rs] for rs in state["roles"]]
            believed = [[str(b[0]), bool(b[1]), bool(b[2])] for b in state["believed"]]
            if len(roles) != self.n_sats or len(believed) != self.n_sats:
                raise ValueError(f"roles/believed lists must hold {self.n_sats} entries")
            rng = make_rng(self.scenario)
            rng.bit_generator.state = state["rng"]
            if comms := self.comms and comms_v2.CommsState(self.scenario):
                comms.load(state["comms"])
            self.faults.load(state["faults"])  # atomic itself; raises ValueError first
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bad EngineV2 snapshot: {exc!r}") from exc
        self.k, self.X, self.refs, self.dv, self.hold, self.cov = k, X, refs, dv, hold, cov
        self.roles, self.believed = roles, believed
        self.rng, self.comms = rng, comms

    # -- internals ---------------------------------------------------------------------------------
    def _reentries(self, t: float, lvlh: np.ndarray) -> list[dict]:
        """Flag (once) every sat whose altitude fell below REENTRY_ALTITUDE_M; remember its LVLH
        state at that moment (the ECI state is frozen too, see _advance)."""
        alt = np.linalg.norm(self.X[1:, :3], axis=1) - truth.RE
        events = []
        for i in range(self.n_sats):
            if alt[i] < REENTRY_ALTITUDE_M and self.faults.status[i] != STATUS_REENTERED:
                self.hold[i] = lvlh[i]
                events.append(self.faults.mark_reentered(i, t, float(alt[i])))
        return events

    def _update_roles(self) -> list[dict]:
        """Re-assign capability roles from the BELIEVED statuses (cubesat/roles_v2.py; no motion
        is touched) and return the ROLE_HANDOFF events of this tick. Only roles the scenario
        labels exist at all: a scenario without a downlink has that role vacant from the start."""
        f = self.faults
        self.believed = believe(self.believed, f.status, f.sats, f.declared)
        view = [
            {"status": b[0], "payload_ok": b[1], "radio_ok": b[2], "roles": rs}
            for b, rs in zip(self.believed, self.roles, strict=True)
        ]
        priority = [r for r in self.scenario.role_priority if r in self.scenario.roles]
        new = assign_roles(view, priority, self.scenario.roles.count("imager"))
        payloads = handoff_events(self.roles, new, f.status, priority)
        self.roles = new
        return [{"type": "ROLE_HANDOFF", "payload": p} for p in payloads]

    def _min_sep(self, rho: np.ndarray) -> float:
        """Minimum pairwise LVLH distance among sats not re-entered (all sats if fewer than 2)."""
        keep = [i for i, s in enumerate(self.faults.status) if s != STATUS_REENTERED]
        pts = rho[keep] if len(keep) >= 2 else rho
        d = pts[:, None, :] - pts[None, :, :]
        return float(np.sqrt(np.min((d**2).sum(-1)[np.triu_indices(len(pts), 1)])))

    def _advance(self, lvlh: np.ndarray) -> None:
        """PD command per sat that can still fly (LVLH, zero-order hold) through thrust_limited
        (thrust cap k F_max / m, propellant use), then one batched RK4 step. A stuck-open
        thruster ignores the PD and fires along its fixed ECI vector."""
        status, dt = self.faults.status, self.dt
        u = np.zeros((self.n_sats, 3))  # applied LVLH acceleration
        a_stuck = np.zeros((self.n_sats, 3))  # applied ECI acceleration of stuck-open sats
        for i, s in enumerate(status):
            if s in (STATUS_DEAD, STATUS_REENTERED):
                continue
            sat = self.faults.sats[i]
            if sat.stuck_vec is not None:
                a_stuck[i], _ = thrust_limited(sat, u[i], dt)
            else:
                cmd = self.pd.command(lvlh[i, :3], lvlh[i, 3:], self.refs[i, :3], self.refs[i, 3:])
                u[i], _ = thrust_limited(sat, cmd, dt)
        self.dv += np.linalg.norm(u + a_stuck, axis=1) * dt
        a_dep = truth.thrust_eci(u, self.X[0, :3], self.X[0, 3:]) + a_stuck
        a_thrust = np.vstack([np.zeros(3), a_dep])
        b = np.array([0.0] + [self._b_dead if s == STATUS_DEAD else self._b_active for s in status])
        tr = self.scenario.truth

        def accel(r, v):
            a = truth.accel_gravity(r) + truth.accel_drag(r, v, b, tr.density_factor) + a_thrust
            return a + truth.accel_j2(r) if tr.j2_enabled else a

        new = truth.rk4_step(self.X, dt, accel)
        frozen = np.array([False] + [s == STATUS_REENTERED for s in status])  # chief never frozen
        self.X = np.where(frozen[:, None], self.X, new)
        self.refs = self.refs @ self.phi_dt.T


def run_scenario_v2(scenario: Scenario, cancel_event: threading.Event | None = None) -> list[dict]:
    """[INIT header, tick..., SUMMARY]; RunCancelled between ticks, no partial output."""
    return list(EngineV2(scenario).run(cancel_event))
