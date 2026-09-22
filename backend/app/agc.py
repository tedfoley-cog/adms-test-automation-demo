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


def allocate_regulation(
    units: list[Unit], ace_mw: float, interval_s: float = 4.0
) -> dict[str, float]:
    """Distribute the correction across units on AGC by participation factor,
    clipped by ramp capability over the control interval and unit limits."""
    if abs(ace_mw) <= DEADBAND_MW:
        return {unit.name: 0.0 for unit in units}

    correction = -ace_mw
    on_agc = [unit for unit in units if unit.on_agc and unit.participation > 0.0]
    total_participation = sum(unit.participation for unit in on_agc)
    if total_participation <= 0.0:
        return {unit.name: 0.0 for unit in units}

    setpoints: dict[str, float] = {unit.name: 0.0 for unit in units}
    for unit in on_agc:
        share = correction * (unit.participation / total_participation)
        ramp_limit = unit.ramp_mw_per_min * (interval_s / 60.0)
        share = max(-ramp_limit, min(ramp_limit, share))
        target = unit.output_mw + share
        target = max(unit.min_mw, min(unit.max_mw, target))
        setpoints[unit.name] = round(target - unit.output_mw, 4)
    return setpoints
