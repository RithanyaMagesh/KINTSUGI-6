"""Scenario schema (pydantic v2). Scenarios are external JSON files (locked decision)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Resource bounds (audit: scenarios are uploaded through the API by an
# unauthenticated console user, so every derived allocation must be bounded --
# target_grid materializes (2*extent/step+1)^2 points per tick, the sweeps
# multiply into the replan's candidate count, and duration/dt set the tick
# count). Each cap sits ~5x above every committed scenario, benchmark and
# sweep value (largest legit: 961 grid points, 12-entry phase sweep, 8 sats,
# 8515 ticks), so canonical runs validate unchanged and logs stay
# byte-identical (AGENTS.md invariant 2).
MAX_GRID_POINTS = 10_000
MAX_SWEEP_ENTRIES = 64
MAX_SATS = 32
MAX_FAILURES = 64
MAX_DURATION_S = 86_400.0
MAX_TICKS = 100_000


class FailureMode(StrEnum):
    """DEAD: no comms, no thrust, coasts ballistically. THRUSTER_OUT: reports, cannot
    maneuver. EPS_DEGRADE: gradual power death -- with degrade_s > 0 the sat reports
    DEGRADED for degrade_s before dying exactly like DEAD; degrade_s == 0 is sudden."""

    DEAD = "DEAD"
    THRUSTER_OUT = "THRUSTER_OUT"
    EPS_DEGRADE = "EPS_DEGRADE"


class ChiefOrbit(BaseModel):
    altitude_km: float = Field(
        gt=160, lt=2000, description="Circular chief altitude above Earth, km"
    )
    inclination_deg: float = Field(
        default=97.4, ge=0, le=180,
        description="Chief inclination, deg (engine v2 only; SSO-like, illustrative default)",
    )
    raan_deg: float = Field(
        default=0.0, description="Chief right ascension of ascending node, deg (engine v2 only)"
    )
    epoch_utc: str = Field(
        default="2026-03-20T12:00:00Z",
        description="Fixed ISO-8601 UTC epoch of t=0 (engine v2 only; used for the sun "
        "direction and Earth rotation phase; illustrative fixed date, never the wall clock)",
    )


class Formation(BaseModel):
    n_slots: int = Field(
        ge=2, le=MAX_SATS, description="Number of phase-spaced passive-ellipse slots"
    )
    radial_amp_km: float = Field(
        gt=0, description="Radial amplitude of each drift-free 2:1 ellipse, km"
    )
    phase_offset_deg: float = Field(
        default=0.0, description="Common phase offset of all slots, deg"
    )


class Gains(BaseModel):
    wn: float = Field(gt=0, description="PD natural frequency, rad/s")
    zeta: float = Field(gt=0, description="PD damping ratio")


class Sensor(BaseModel):
    fov_half_angle_deg: float = Field(gt=0, le=45, description="Imager half field of view, deg")
    grid_step_km: float = Field(gt=0, description="Target grid spacing in the (y, z) plane, km")
    grid_extent_km: float = Field(gt=0, description="Half-extent of the square target grid, km")

    @model_validator(mode="after")
    def _grid_fits_budget(self) -> Sensor:
        # coverage.target_grid materializes (2*extent/step+1)^2 points per tick;
        # only gt=0 bounds would let one uploaded scenario pin unbounded memory
        # in the shared server process (audit, medium). Same point-count formula
        # as cubesat/coverage.py:33-35.
        n_per_axis = int(round(2.0 * self.grid_extent_km / self.grid_step_km)) + 1
        if n_per_axis * n_per_axis > MAX_GRID_POINTS:
            raise ValueError(
                f"target grid is {n_per_axis}x{n_per_axis} = {n_per_axis ** 2} points, "
                f"above the {MAX_GRID_POINTS}-point budget; raise grid_step_km or "
                f"lower grid_extent_km"
            )
        return self


class Failure(BaseModel):
    t: float = Field(ge=0, description="Failure time, sim seconds")
    sat_id: int = Field(ge=0)
    mode: FailureMode
    degrade_s: float = Field(
        default=0.0, ge=0,
        description="EPS_DEGRADE fade length, s: the sat is DEGRADED from "
        "max(t - degrade_s, 0) and dies at t; 0 = sudden (DEAD-equivalent "
        "run; the FAILURE_DETECTED mode label stays EPS_DEGRADE)",
    )


class Detection(BaseModel):
    """Heartbeat monitoring: every non-DEAD sat reports once per tick; a sat that
    stops reporting is declared failed after missed_ticks_k consecutive misses."""

    missed_ticks_k: int = Field(
        ge=1, default=3, description="Missed heartbeat ticks before declaring failure"
    )


class Allocation(BaseModel):
    """Two-step allocation parameters (MASTER_PROMPT 3.3). Weights apply to the
    normalized cost terms; the sweep grids are the survivor-formation candidates."""

    w1: float = Field(gt=0, default=1.0, description="Weight of normalized distance")
    w2: float = Field(gt=0, default=0.5, description="Weight of normalized distance/fuel")
    w3: float = Field(ge=0, default=2.0, description="Weight of role mismatch (0/1)")
    min_sep_km: float = Field(
        gt=0, default=2.0,
        description="Min pairwise separation constraint, km (dead sats included)",
    )
    dv_budget_mps: float = Field(
        gt=0, default=100.0,
        description="Per-transfer delta-v budget for seat reachability, m/s",
    )
    amp_sweep: list[float] = Field(
        default_factory=lambda: [1.0],
        min_length=1,
        max_length=MAX_SWEEP_ENTRIES,
        description="Radial-amplitude multipliers swept for the survivor formation",
    )
    phase_sweep_deg: list[float] = Field(
        default_factory=lambda: [0.0, 60.0, 120.0, 180.0, 240.0, 300.0],
        min_length=1,
        max_length=MAX_SWEEP_ENTRIES,
        description="Formation phase offsets swept, deg",
    )
    method: Literal["hungarian", "greedy"] = Field(
        default="hungarian",
        description="Assignment method; 'greedy' forces the fallback (demo toggle)",
    )


class Oracle(BaseModel):
    """Oracle early-warning parameters (Phase 2). Gated default-off; byte-inert when disabled."""

    enabled: bool = Field(
        default=False, description="True = oracle early warning active"
    )
    lead_s: float = Field(
        default=0.0, ge=0.0, description="Warning lead time L in seconds"
    )


class Safety(BaseModel):
    """Evasive collision avoidance (BACKEND_SPEC Addendum v1.2 item 5): a discrete
    bounded evasion maneuver -- explicitly NOT potential fields (MASTER_PROMPT 2
    lock preserved; min_sep stays logged every step). A sat inside evade_radius_m
    of another burns straight away from it at a_max for evade_ticks ticks; while
    the range is still inside the radius when the counter expires, a new episode
    starts (continuous burn until clear). Default-inertness is GEOMETRIC, not
    flag-off: at the 1000 m default radius the maneuver never fires on any
    canonical run (P0 worst survivor-dead clearance 1322.6 m, G4 worst min_sep
    3095.1 m -- GATES.md), so committed scenarios keep byte-identical logs."""

    evasion_enabled: bool = Field(
        default=True, description="True = evasive collision avoidance active"
    )
    evade_radius_m: float = Field(
        default=1000.0, gt=0, description="Keep-out radius that triggers evasion, m"
    )
    evade_ticks: int = Field(
        default=25, ge=1, description="Ticks per evasion episode (bounded burn length)"
    )


class Scenario(BaseModel):
    name: str = Field(min_length=1)
    seed: int = Field(ge=0)
    duration_s: float = Field(
        gt=0, le=MAX_DURATION_S, description="Simulated duration, seconds"
    )
    dt_s: float = Field(gt=0, le=10, description="Fixed integration step, seconds")
    chief: ChiefOrbit
    formation: Formation
    a_max_mps2: float = Field(gt=0, description="Thrust saturation, m/s^2")
    gains: Gains
    sensor: Sensor
    roles: list[str] = Field(
        min_length=2, max_length=MAX_SATS, description="One role per satellite, index = sat id"
    )
    failures: list[Failure] = Field(default_factory=list, max_length=MAX_FAILURES)
    recovery_enabled: bool = Field(
        default=True,
        description="False = detect failures but never replan (no-recovery baseline)",
    )
    recovery_delay_s: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Delay in seconds from first failure detection before triggering recovery "
            "replanning (0.0 = autonomous onboard recovery; 5400.0 = wait-for-ground baseline)"
        ),
    )
    reassign_on_degrade: bool = Field(
        default=False,
        description=(
            "Degrade-trigger policy (GATES.md 2026-10-29 pre-registration): when a "
            "satellite holding a critical role (leader/downlink) transitions "
            "NOMINAL -> DEGRADED (the EPS_DEGRADE fade onset), proactively swap its "
            "seat and role with the lowest-index healthy non-critical satellite -- "
            "the oracle path's swap, logged as ORACLE_SWAP with payload mode "
            "'degrade_trigger'. Default-off: canonical scenarios never set it and "
            "stay byte-identical."
        ),
    )
    detection: Detection = Field(default_factory=Detection)
    allocation: Allocation = Field(default_factory=Allocation)
    oracle: Oracle = Field(default_factory=Oracle)
    safety: Safety = Field(default_factory=Safety)
    engine: Literal["v1", "v2"] = Field(
        default="v1",
        description="'v1' = frozen linear-CW engine (every committed log); "
        "'v2' = truth-dynamics engine (cubesat/sim_v2.py)",
    )

    @property
    def n_sats(self) -> int:
        return len(self.roles)

    @model_validator(mode="after")
    def _failures_reference_existing_sats(self) -> Scenario:
        for failure in self.failures:
            if failure.sat_id >= self.n_sats:
                raise ValueError(
                    f"failure references sat_id={failure.sat_id}, but only {self.n_sats} sats exist"
                )
        return self

    @model_validator(mode="after")
    def _slots_match_roles(self) -> Scenario:
        # States are built from the slots but every loop runs over n_sats; a
        # mismatch would either pollute the log with phantom sats or IndexError.
        if self.formation.n_slots != self.n_sats:
            raise ValueError(
                f"formation.n_slots={self.formation.n_slots} must equal "
                f"len(roles)={self.n_sats}"
            )
        return self

    @model_validator(mode="after")
    def _bounded_step_count(self) -> Scenario:
        # The run length is duration/dt ticks (cubesat/sim.py:210); dt_s alone
        # has no useful lower bound, so duration_s=1e9 / dt_s=1e-9 must be
        # refused here, not discovered as an hour-long orphan compute thread
        # after the server's 60 s timeout (audit, medium).
        n_ticks = int(round(self.duration_s / self.dt_s)) + 1
        if n_ticks > MAX_TICKS:
            raise ValueError(
                f"duration_s={self.duration_s} / dt_s={self.dt_s} implies "
                f"{n_ticks} ticks, above the {MAX_TICKS}-tick budget; raise dt_s "
                f"or lower duration_s"
            )
        return self


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate_json(Path(path).read_text(encoding="utf-8"))
