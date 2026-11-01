"""Track C scenario models (comms, recovery authority), split out of scenario_models.py
for its line budget; re-exported there and in cubesat/scenario.py."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from cubesat.scenario_models import MAX_DURATION_S, MAX_SATS


class LaserTerminal(BaseModel):
    """One optical crosslink terminal (engine v2, comms.model "laser"). Fields mirror
    cubesat/isl.py Terminal 1:1. CLICK-class (MIT/NASA CLICK-B/C) power, wavelength and rate cap;
    apertures, eta, photons/bit, pointing error, acquisition time, sun cone and terminal count
    are ASSUMPTIONS of this simulator, not hardware figures."""

    wavelength_m: float = Field(default=1.55e-6, gt=0, le=1e-3)
    p_tx_w: float = Field(default=0.2, gt=0, le=1e3)
    d_tx_m: float = Field(default=0.02, gt=0, le=10, description="assumption")
    d_rx_m: float = Field(default=0.02, gt=0, le=10, description="assumption")
    eta: float = Field(default=0.3, gt=0, le=1, description="optics x detector, assumption")
    photons_per_bit: float = Field(default=300.0, gt=0, le=1e9, description="assumption")
    max_rate_bps: float = Field(default=20e6, gt=0, le=1e12, description="modem cap")
    pointing_error_rad: float = Field(default=5e-6, ge=0, le=1, description="assumption")
    acquire_s: float = Field(default=30.0, ge=0, le=MAX_DURATION_S, description="assumption")
    sun_exclusion_rad: float = Field(default=0.05235987755982989, ge=0, le=1.5707963267948966,
                                     description="3 deg receive sun cone, assumption")
    terminals_per_sat: int = Field(default=2, ge=1, le=MAX_SATS, description="assumption")


class Comms(BaseModel):
    """Inter-satellite comms (track C). "ideal" = instant, lossless (every committed log);
    "laser" = point-to-point optical links (cubesat/comms_v2.py, engine v2 only): heartbeats
    travel only over LOCKED links. topology "mesh" = shortest-range greedy under the terminal
    cap; "star" = every sat links to the current leader (the hub carries n-1 terminals:
    assumption, the centralised layout)."""

    model: Literal["ideal", "laser"] = "ideal"
    topology: Literal["mesh", "star"] = "mesh"
    terminal: LaserTerminal = Field(default_factory=LaserTerminal)


class Recovery(BaseModel):
    """Who does the leader's job (track C4). "central" = one `leader` role (cubesat/roles_v2.py);
    "decentral" = the leader's six functions are spread over the swarm by a consensus auction
    over the LOCKED laser links (cubesat/decentral.py); needs comms.model "laser"."""

    authority: Literal["central", "decentral"] = "central"
    # exclude_if / None: the defaults stay out of model_dump, so fingerprints do not change
    ladder: bool = Field(
        default=False,
        exclude_if=lambda v: not v,
        description="Engine v2 only: on a declared failure run the recovery ladder L0-L5 "
        "(cubesat/ladder.py) and execute only certified plans; False = no plan, roles only",
    )
    coverage_floor: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False,
        description="Ladder only: a plan below this coverage fraction fails its certificate "
        "(then L4, DEGRADED_MISSION); None = no floor (illustrative knob)",
    )

    @model_validator(mode="after")
    def _ladder_is_central(self) -> Recovery:
        if self.ladder and self.authority == "decentral":
            raise ValueError('recovery.ladder needs authority "central" (the leader is a role)')
        if self.coverage_floor is not None and not self.ladder:
            raise ValueError("recovery.coverage_floor is read by the ladder only: set ladder true")
        return self
