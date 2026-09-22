"""Domain models for the distribution/energy management services.

Field names follow IEC 61970/61968 (CIM) naming where a direct equivalent
exists: ConductingEquipment mRID, Switch normalOpen, Measurement value.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SwitchKind(StrEnum):
    BREAKER = "breaker"
    RECLOSER = "recloser"
    SECTIONALIZER = "sectionalizer"
    TIE = "tie"


class Switch(BaseModel):
    mrid: str
    name: str
    kind: SwitchKind
    normal_open: bool = False
    open: bool = False
    scada_controllable: bool = True
    from_node: str
    to_node: str


class Section(BaseModel):
    """A stretch of feeder between two switching devices."""

    mrid: str
    name: str
    from_node: str
    to_node: str
    customers: int = 0
    load_kw: float = 0.0
    fault_indicator: bool = False


class Feeder(BaseModel):
    mrid: str
    name: str
    substation: str
    nominal_kv: float
    source_node: str
    rating_amps: float
    sections: list[Section] = Field(default_factory=list)
    switches: list[Switch] = Field(default_factory=list)


class NetworkModel(BaseModel):
    feeders: list[Feeder] = Field(default_factory=list)


class Measurement(BaseModel):
    """A telemetered analog value referenced to a CIM mRID."""

    mrid: str
    kind: str  # "P", "Q", "V", "I"
    value: float
    sigma: float = 0.01
    valid: bool = True


class IsolationStep(BaseModel):
    switch_mrid: str
    action: str  # "open" | "close"
    reason: str


class RestorationPlan(BaseModel):
    feeder_mrid: str
    faulted_section: str | None
    isolation: list[IsolationStep] = Field(default_factory=list)
    restoration: list[IsolationStep] = Field(default_factory=list)
    customers_restored: int = 0
    customers_remaining: int = 0
    transferred_load_kw: float = 0.0
    notes: list[str] = Field(default_factory=list)


class TieLine(BaseModel):
    name: str
    actual_mw: float
    scheduled_mw: float


class BalancingState(BaseModel):
    """Inputs to the Reporting ACE calculation (NERC BAL-001)."""

    tie_lines: list[TieLine]
    actual_frequency_hz: float
    scheduled_frequency_hz: float = 60.0
    frequency_bias_mw_per_0_1hz: float
    meter_error_mw: float = 0.0


class Unit(BaseModel):
    name: str
    output_mw: float
    min_mw: float
    max_mw: float
    ramp_mw_per_min: float
    participation: float  # regulation participation factor, 0..1
    on_agc: bool = True
