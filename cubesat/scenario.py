"""Scenario schema (pydantic v2). Scenarios are external JSON files (locked decision).

The leaf models and MAX_* bounds live in cubesat/scenario_models.py and are re-exported
here, so ``from cubesat.scenario import Failure`` (etc.) keeps working with the same objects."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from cubesat.scenario_models import (  # noqa: F401  (re-exports: the public scenario API)
    MAX_DURATION_S,
    MAX_FAILURES,
    MAX_GRID_POINTS,
    MAX_SATS,
    MAX_SWEEP_ENTRIES,
    MAX_TICKS,
    ROLE_PRIORITY,
    V2_ONLY_MODES,
    Allocation,
    ChiefOrbit,
    Detection,
    Failure,
    FailureMode,
    Formation,
    Gains,
    Oracle,
    Safety,
    Sensor,
    Spacecraft,
    Truth,
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
    truth: Truth = Field(default_factory=Truth)
    spacecraft: Spacecraft = Field(default_factory=Spacecraft)
    role_priority: list[str] = Field(
        default_factory=lambda: list(ROLE_PRIORITY),
        description="Engine v2 only: order in which capability roles are filled each tick "
        "(cubesat/roles_v2.py). Must be a permutation of downlink, imager, leader (spare is "
        "only an output label). v1 never reads it.",
    )
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
    def _v2_only_failure_modes(self) -> Scenario:
        # the frozen v1 engine treats every unknown mode as DEAD; refuse instead of misreading
        if self.engine != "v2":
            for f in self.failures:
                if f.mode in V2_ONLY_MODES:
                    raise ValueError(
                        f'failure mode {f.mode.value} (sat {f.sat_id}) requires engine "v2"; '
                        f'this scenario uses engine "{self.engine}"'
                    )
        return self

    @model_validator(mode="after")
    def _v1_only_cartwheel(self) -> Scenario:
        # the v1 allocator's formation sweep rebuilds cartwheel slots; refuse instead of mixing
        if self.engine != "v2" and self.formation.shape != "cartwheel":
            raise ValueError(
                f'formation.shape "{self.formation.shape}" requires engine "v2"; '
                f'this scenario uses engine "{self.engine}"'
            )
        return self

    @model_validator(mode="after")
    def _role_priority_is_a_permutation(self) -> Scenario:
        if sorted(self.role_priority) != sorted(ROLE_PRIORITY):
            raise ValueError(
                f"role_priority={self.role_priority} must be a permutation of "
                f"{', '.join(sorted(ROLE_PRIORITY))}"
            )
        return self

    @model_validator(mode="after")
    def _propellant_fits_in_wet_mass(self) -> Scenario:
        # v2 only: v1 never reads the block, and a v1 scenario with a tiny truth.mass_kg stays valid
        if self.engine == "v2" and self.spacecraft.m_prop_kg > 0.5 * self.truth.mass_kg:
            raise ValueError(
                f"spacecraft.m_prop_kg={self.spacecraft.m_prop_kg} exceeds half the wet mass "
                f"truth.mass_kg={self.truth.mass_kg}: the dry mass must be at least half the "
                f"wet mass (the drag model keeps the wet mass)"
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
