"""Scenario schema (pydantic v2). Scenarios are external JSON files (locked decision)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FailureMode(StrEnum):
    """DEAD: no comms, no thrust, coasts ballistically. THRUSTER_OUT: reports, cannot maneuver."""

    DEAD = "DEAD"
    THRUSTER_OUT = "THRUSTER_OUT"


class ChiefOrbit(BaseModel):
    altitude_km: float = Field(
        gt=160, lt=2000, description="Circular chief altitude above Earth, km"
    )


class Formation(BaseModel):
    n_slots: int = Field(
        ge=2, description="Number of phase-spaced passive-ellipse slots"
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


class Failure(BaseModel):
    t: float = Field(ge=0, description="Failure time, sim seconds")
    sat_id: int = Field(ge=0)
    mode: FailureMode


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
        description="Radial-amplitude multipliers swept for the survivor formation",
    )
    phase_sweep_deg: list[float] = Field(
        default_factory=lambda: [0.0, 60.0, 120.0, 180.0, 240.0, 300.0],
        min_length=1,
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


class Scenario(BaseModel):
    name: str = Field(min_length=1)
    seed: int = Field(ge=0)
    duration_s: float = Field(gt=0, description="Simulated duration, seconds")
    dt_s: float = Field(gt=0, le=10, description="Fixed integration step, seconds")
    chief: ChiefOrbit
    formation: Formation
    a_max_mps2: float = Field(gt=0, description="Thrust saturation, m/s^2")
    gains: Gains
    sensor: Sensor
    roles: list[str] = Field(min_length=2, description="One role per satellite, index = sat id")
    failures: list[Failure] = Field(default_factory=list)
    recovery_enabled: bool = Field(
        default=True,
        description="False = detect failures but never replan (no-recovery baseline)",
    )
    detection: Detection = Field(default_factory=Detection)
    allocation: Allocation = Field(default_factory=Allocation)
    oracle: Oracle = Field(default_factory=Oracle)

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


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate_json(Path(path).read_text(encoding="utf-8"))
