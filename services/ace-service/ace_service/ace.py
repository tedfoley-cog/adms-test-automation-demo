"""Reporting ACE and regulation allocation (legacy RPTACE and ALLOCR).

Reporting ACE follows NERC BAL-001:
    ACE = (NI_a - NI_s) - 10 B (F_a - F_s) - I_ME
with B in MW/0.1 Hz, negative by convention. Requirement IDs refer to docs/specs/RTGENACE.md.
"""

from __future__ import annotations

import math

from .schemas import AreaState, DispatchResult, Unit, UnitSetpoint

DEADBAND_MW = 5.0
CONTROL_CYCLE_S = 4.0
RESOLUTION_DP = 4


def reporting_ace(area: AreaState) -> float:
    """ACE-1 to ACE-3."""
    actual = sum(line.actual_mw for line in area.tie_lines)
    scheduled = sum(line.scheduled_mw for line in area.tie_lines)
    frequency_error = area.frequency.actual_hz - area.frequency.scheduled_hz
    bias_mw = 10.0 * area.frequency.bias_mw_per_0_1hz * frequency_error
    return (actual - scheduled) - bias_mw - area.meter_error_mw


def participates(unit: Unit) -> bool:
    """AL-3."""
    return unit.on_agc and unit.participation > 0.0


def allocate_regulation(units: list[Unit], ace_mw: float) -> list[float]:
    """AL-1 to AL-8: one delta per unit, in input order."""
    deltas = [0.0] * len(units)
    if abs(ace_mw) <= DEADBAND_MW:
        return deltas

    total = sum(unit.participation for unit in units if participates(unit))
    if total <= 0.0:
        return deltas

    correction = -ace_mw
    for index, unit in enumerate(units):
        if not participates(unit):
            continue
        share = correction * (unit.participation / total)
        ramp_limit = unit.ramp_mw_per_min * (CONTROL_CYCLE_S / 60.0)
        share = max(-ramp_limit, min(ramp_limit, share))
        target = unit.output_mw + share
        target = max(unit.min_mw, target)
        target = min(unit.max_mw, target)
        deltas[index] = target - unit.output_mw
    return deltas


def _rounded(value: float) -> float:
    return round(value, RESOLUTION_DP) + 0.0


def _warnings(area: AreaState) -> list[str]:
    notes: list[str] = []
    if area.frequency.quality != "N":
        notes.append(
            f"F-2: frequency {area.frequency.id} quality '{area.frequency.quality}' is not "
            "normal and still drives the bias term"
        )
    for line in area.tie_lines:
        if line.quality != "N":
            notes.append(
                f"F-2: tie line {line.id} quality '{line.quality}' is not normal and is "
                "still summed into net interchange"
            )
    for unit in area.units:
        if participates(unit) and not unit.min_mw <= unit.output_mw <= unit.max_mw:
            notes.append(
                f"F-1: unit {unit.id} output {unit.output_mw} MW is outside "
                f"[{unit.min_mw}, {unit.max_mw}] and is snapped to the limit regardless of "
                "ramp rate and ACE sign"
            )
    return notes


class NonFiniteResult(ValueError):
    """Finite inputs whose sums overflow; RTGENACE would emit Infinity setpoints (D-1)."""


def dispatch(area: AreaState) -> DispatchResult:
    ace = reporting_ace(area)
    deltas = allocate_regulation(area.units, ace)
    if not all(math.isfinite(value) for value in (ace, *deltas)):
        raise NonFiniteResult("area state overflows to a non-finite ACE or setpoint")
    return DispatchResult(
        savecase=area.savecase,
        ace_mw=_rounded(ace),
        deadband_mw=DEADBAND_MW,
        control_cycle_s=CONTROL_CYCLE_S,
        in_deadband=abs(ace) <= DEADBAND_MW,
        setpoints=[
            UnitSetpoint(
                unit=unit.id,
                setpoint_delta_mw=_rounded(delta),
                target_mw=_rounded(unit.output_mw + delta),
                participating=participates(unit),
            )
            for unit, delta in zip(area.units, deltas, strict=True)
        ],
        warnings=_warnings(area),
    )
