"""Automatic generation control.

Reporting ACE follows NERC BAL-001:
    ACE = (NI_a - NI_s) - 10B (F_a - F_s) - I_ME
where B is the frequency bias setting in MW/0.1 Hz.
"""

from __future__ import annotations

from .models import BalancingState, Unit

DEADBAND_MW = 5.0


def reporting_ace(state: BalancingState) -> float:
    actual_interchange = sum(line.actual_mw for line in state.tie_lines)
    scheduled_interchange = sum(line.scheduled_mw for line in state.tie_lines)
    frequency_error = state.actual_frequency_hz - state.scheduled_frequency_hz
    bias_term = 10.0 * state.frequency_bias_mw_per_0_1hz * frequency_error
    return (actual_interchange - scheduled_interchange) - bias_term - state.meter_error_mw


def _regulated(unit: Unit) -> bool:
    return unit.on_agc and unit.participation > 0.0


def allocate_regulation_by_unit(
    units: list[Unit], ace_mw: float, interval_s: float = 4.0, deadband_mw: float = DEADBAND_MW
) -> list[float]:
    """Setpoint change for each unit row, in order (one per row, as in legacy ALLOCR).

    The correction is distributed across units on AGC by participation factor,
    clipped by ramp capability over the control interval and then unit limits."""
    setpoints = [0.0] * len(units)
    if abs(ace_mw) <= deadband_mw:
        return setpoints

    correction = -ace_mw
    total_participation = sum(unit.participation for unit in units if _regulated(unit))
    if total_participation <= 0.0:
        return setpoints

    for index, unit in enumerate(units):
        if not _regulated(unit):
            continue
        share = correction * (unit.participation / total_participation)
        ramp_limit = unit.ramp_mw_per_min * (interval_s / 60.0)
        share = max(-ramp_limit, min(ramp_limit, share))
        target = unit.output_mw + share
        target = min(unit.max_mw, max(unit.min_mw, target))
        setpoints[index] = round(target - unit.output_mw, 4)
    return setpoints


def allocate_regulation(
    units: list[Unit], ace_mw: float, interval_s: float = 4.0
) -> dict[str, float]:
    """``allocate_regulation_by_unit`` keyed by unit name (names must be unique)."""
    setpoints: dict[str, float] = {unit.name: 0.0 for unit in units}
    for unit, delta in zip(
        units, allocate_regulation_by_unit(units, ace_mw, interval_s), strict=True
    ):
        if _regulated(unit):
            setpoints[unit.name] = delta
    return setpoints
