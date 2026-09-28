"""Scenario schema (pydantic v2). Scenarios are external JSON files (locked decision)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

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


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate_json(Path(path).read_text(encoding="utf-8"))
