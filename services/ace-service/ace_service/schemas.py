"""Request and response contract of the ACE service.

Field meanings follow the HDB records the legacy task reads (FREQ, TIELINE, METERR, UNIT).
Inputs the legacy task turns into unsafe output are refused here (spec §6, D-1 to D-4).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=20)]
Quality = Annotated[str, StringConstraints(min_length=1, max_length=1)]

MAX_TIE_LINES = 32
MAX_UNITS = 64


class Frequency(BaseModel):
    id: Identifier = "AREA"
    actual_hz: FiniteFloat
    scheduled_hz: FiniteFloat = 60.0
    bias_mw_per_0_1hz: FiniteFloat
    quality: Quality = "N"


class TieLine(BaseModel):
    id: Identifier
    actual_mw: FiniteFloat
    scheduled_mw: FiniteFloat
    quality: Quality = "N"


class Unit(BaseModel):
    id: Identifier
    output_mw: FiniteFloat
    min_mw: FiniteFloat
    max_mw: FiniteFloat
    ramp_mw_per_min: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    participation: FiniteFloat
    on_agc: bool

    @model_validator(mode="after")
    def _limits_ordered(self) -> Unit:
        if self.min_mw > self.max_mw:
            raise ValueError(f"unit {self.id}: min_mw {self.min_mw} exceeds max_mw {self.max_mw}")
        return self


class AreaState(BaseModel):
    savecase: Annotated[str, StringConstraints(max_length=32)] = ""
    frequency: Frequency
    meter_error_mw: FiniteFloat = 0.0
    tie_lines: Annotated[list[TieLine], Field(max_length=MAX_TIE_LINES)] = []
    units: Annotated[list[Unit], Field(max_length=MAX_UNITS)] = []

    @model_validator(mode="after")
    def _unique_unit_ids(self) -> AreaState:
        seen: set[str] = set()
        for unit in self.units:
            if unit.id in seen:
                raise ValueError(f"duplicate unit id {unit.id}")
            seen.add(unit.id)
        return self


class UnitSetpoint(BaseModel):
    unit: str
    setpoint_delta_mw: float
    target_mw: float
    participating: bool


class DispatchResult(BaseModel):
    savecase: str
    ace_mw: float
    deadband_mw: float
    control_cycle_s: float
    in_deadband: bool
    setpoints: list[UnitSetpoint]
    warnings: list[str] = []
