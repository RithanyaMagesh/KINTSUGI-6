"""Leaf pydantic models of the scenario schema, split out of cubesat/scenario.py (which
re-exports every public name here, so ``cubesat.scenario.Failure is
cubesat.scenario_models.Failure``). Scenario itself and its cross-field validators stay in
cubesat/scenario.py."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
ROLE_PRIORITY = ("downlink", "imager", "leader")  # = roles_v2.DEFAULT_PRIORITY (test-pinned)
MAX_TICKS = 100_000


class FailureMode(StrEnum):
    """DEAD: no comms, no thrust, coasts ballistically. THRUSTER_OUT: reports, cannot
    maneuver. EPS_DEGRADE: gradual power death -- with degrade_s > 0 the sat reports
    DEGRADED for degrade_s before dying exactly like DEAD; degrade_s == 0 is sudden."""

    DEAD = "DEAD"
    THRUSTER_OUT = "THRUSTER_OUT"
    EPS_DEGRADE = "EPS_DEGRADE"
    # Engine v2 only (resource damage, cubesat/spacecraft.py): PAYLOAD_FAIL = no imaging,
    # PARTIAL_THRUST = thrust health 0.5, THRUSTER_STUCK_OPEN = constant thrust along a fixed
    # ECI vector until the propellant is empty, RADIO_FAIL = alive and flying but silent.
    PAYLOAD_FAIL = "PAYLOAD_FAIL"
    PARTIAL_THRUST = "PARTIAL_THRUST"
    THRUSTER_STUCK_OPEN = "THRUSTER_STUCK_OPEN"
    RADIO_FAIL = "RADIO_FAIL"


V2_ONLY_MODES = frozenset(
    {
        FailureMode.PAYLOAD_FAIL,
        FailureMode.PARTIAL_THRUST,
        FailureMode.THRUSTER_STUCK_OPEN,
        FailureMode.RADIO_FAIL,
    }
)


class ChiefOrbit(BaseModel):
    altitude_km: float = Field(
        gt=160, lt=2000, description="Circular chief altitude above Earth, km"
    )
    inclination_deg: float = Field(
        default=97.4, ge=0, le=180, allow_inf_nan=False,
        description="Chief inclination, deg (engine v2 only; SSO-like, illustrative default)",
    )
    raan_deg: float = Field(
        default=0.0, ge=-360, le=360, allow_inf_nan=False,
        description="Chief right ascension of ascending node, deg, in [-360, 360] "
        "(engine v2 only)",
    )
    epoch_utc: str = Field(
        default="2026-03-20T12:00:00Z",
        description="Fixed ISO-8601 UTC epoch of t=0 (engine v2 only; reserved for the sun "
        "direction; illustrative fixed date, never the wall clock)",
    )

    @field_validator("epoch_utc")
    @classmethod
    def _epoch_is_iso(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"epoch_utc must be an ISO-8601 timestamp: {exc}") from exc
        return value


class Truth(BaseModel):
    """Truth-model constants (engine v2 only). ALL defaults are illustrative, not measured
    hardware: Cd 2.2 is the usual flat-plate value, areas follow a 10x10x30 cm 3U box
    (end-on 0.010 m^2; tumbling mean projected area = surface/4 = 0.035 m^2), 4 kg mass.
    Bounds only keep every log finite; they are not claims about real spacecraft."""

    cd: float = Field(
        default=2.2, gt=0, le=10, allow_inf_nan=False, description="Drag coefficient (illustrative)"
    )
    area_active_m2: float = Field(
        default=0.010, gt=0, le=100, allow_inf_nan=False,
        description="Drag area, active attitude-held sat, m^2 (illustrative)",
    )
    area_dead_m2: float = Field(
        default=0.035, gt=0, le=100, allow_inf_nan=False,
        description="Mean drag area, dead tumbling sat, m^2 (illustrative)",
    )
    mass_kg: float = Field(
        default=4.0, ge=1e-3, le=1e4, allow_inf_nan=False,
        description="Spacecraft mass, kg (illustrative)",
    )
    density_factor: float = Field(
        default=1.0, ge=0, le=1e4, allow_inf_nan=False,
        description="Multiplier on the exponential-atmosphere density (1 = table, 0 = drag off, "
        ">1 = storm); illustrative",
    )
    j2_enabled: bool = Field(default=True, description="False = two-body gravity only (validation)")


class Spacecraft(BaseModel):
    """Propulsion resources (engine v2 only). ALL defaults are illustrative, not measured
    hardware: a 3U cold-gas CubeSat. The wet mass is truth.mass_kg (4.0 kg); dry mass =
    wet - m_prop_kg. Tank delta-v = Isp g0 ln(wet/dry) = 20.12 m/s with the defaults."""

    m_prop_kg: float = Field(
        default=0.2, ge=0, le=1e3, allow_inf_nan=False,
        description="Propellant mass at t=0, kg, included in truth.mass_kg (illustrative)",
    )
    isp_s: float = Field(
        default=40.0, gt=0, le=1e4, allow_inf_nan=False,
        description="Specific impulse, s (cold gas class, illustrative)",
    )
    f_max_n: float = Field(
        default=0.04, gt=0, le=1e4, allow_inf_nan=False,
        description="Maximum thrust, N: 0.04 N / 4 kg = 0.01 m/s^2 (illustrative)",
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
    cross_track_phase_deg: float = Field(
        default=0.0,
        ge=-360,
        le=360,
        allow_inf_nan=False,
        description="Cross-track phase psi of the slots, deg: z = B cos(theta + psi). "
        "v2 only; 0 reproduces v1 slots",
    )
    # exclude_if: the default is left out of model_dump, so every existing scenario keeps its
    # sha256 fingerprint (sim_v2._fingerprint); a non-default shape is dumped and fingerprinted.
    shape: Literal["cartwheel", "pco", "gco", "helix", "string"] = Field(
        default="cartwheel",
        exclude_if=lambda v: v == "cartwheel",
        description="Formation shape (cubesat/formations.py). 'cartwheel' = the v1 slots; "
        "pco/gco/helix/string are engine v2 only. For 'string', radial_amp_km is the "
        "along-track spacing",
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
