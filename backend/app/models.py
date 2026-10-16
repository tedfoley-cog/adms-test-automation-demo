"""Domain models for the distribution/energy management services.

Field names follow IEC 61970/61968 (CIM) naming where a direct equivalent
exists: ConductingEquipment mRID, Switch normalOpen, Measurement value.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Final

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    StrictStr,
)

# Tie-capacity characteristic parameters: the one production source (design section 2,
# Q-DESIGN-1). Values from spec Q-SPEC-1/2/4/10/12; consumers import them, never restate them.
TIE_CAPACITY_TOLERANCE_KW: Final = 0.5  # kW, L <= C + tolerance closes (Q-SPEC-1, Q-SPEC-4)
TIE_CAPACITY_MAX_AGE: Final = timedelta(seconds=20)  # age > max -> CAPACITY_STALE (Q-SPEC-2)
TIE_CAPACITY_MAX_LEAD: Final = timedelta(seconds=2)  # age < -lead -> CAPACITY_INVALID (Q-SPEC-10)
AS_OF_MAX_LAG: Final = timedelta(seconds=60)  # server_now - as_of > lag -> 422 (Q-SPEC-12)
AS_OF_MAX_LEAD: Final = timedelta(seconds=2)  # as_of - server_now > lead -> 422 (Q-SPEC-12)
TIE_CAPACITY_GOOD_QUALITY: Final = "GOOD"  # any other quality -> CAPACITY_UNKNOWN (Q-SPEC-2)


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


def _require_iso_string(value: object) -> object:
    """Accept a datetime (Python callers) or an ISO-8601 string only; never a Unix number."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError("timestamp must be an ISO-8601 string")


IsoAwareDatetime = Annotated[AwareDatetime, BeforeValidator(_require_iso_string)]


class TieCapacity(BaseModel):
    """Alternate-feeder spare capacity for one tie switch, as scanned by SCADA.

    Types are strict per field; range and freshness are judged by the planner, not here.
    """

    model_config = ConfigDict(extra="forbid")

    kw: StrictFloat
    timestamp: IsoAwareDatetime
    quality: StrictStr


class TieBlockReason(StrEnum):
    """Why a candidate tie was not closed. Declaration order is the reporting precedence."""

    FAULTED_SECTION = "FAULTED_SECTION"
    CAPACITY_INVALID = "CAPACITY_INVALID"
    CAPACITY_UNKNOWN = "CAPACITY_UNKNOWN"
    CAPACITY_STALE = "CAPACITY_STALE"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"


class BlockedTie(BaseModel):
    tie_id: str
    reason: TieBlockReason


class RestorationPlan(BaseModel):
    feeder_mrid: str
    faulted_section: str | None
    isolation: list[IsolationStep] = Field(default_factory=list)
    restoration: list[IsolationStep] = Field(default_factory=list)
    customers_restored: int = 0
    customers_remaining: int = 0
    transferred_load_kw: float = 0.0
    notes: list[str] = Field(default_factory=list)
    blocked_ties: list[BlockedTie] = Field(default_factory=list)


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
