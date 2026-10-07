"""Port of the legacy RTGENACE task (legacy/habitat/src/ace_calc.f90).

RTGENACE reads an HDB savecase export, computes Reporting ACE (RPTACE) and
allocates regulation across the units on AGC for one 4 s control cycle
(ALLOCR). This module reproduces the task end to end, including its report
format and exit codes, so the two can be replayed side by side.

The Fortran stores every savecase value in single precision; the port works in
double. ``ace_parity_bound`` and ``setpoint_parity_bound`` give, per savecase,
the largest difference that single-precision storage and arithmetic can cause.
A legacy/modern difference inside the bound is rounding; one outside it is a
behavioural divergence.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from .agc import DEADBAND_MW, allocate_regulation_by_unit, reporting_ace
from .savecase import Savecase, SavecaseError, load_savecase

CONTROL_INTERVAL_S = 4.0
# Both sides print to 4 decimals (Fortran F12.4); the port rounds setpoints the same way.
PRINT_RESOLUTION_MW = 1e-4
_FLOAT32_UNIT_ROUNDOFF = 2.0**-24

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_READ_FAILED = 3


@dataclass(frozen=True)
class RtgenaceResult:
    savecase: str
    ace_mw: float
    setpoints: list[tuple[str, float]]


def run(case: Savecase) -> RtgenaceResult:
    ace = reporting_ace(case.balancing_state())
    # Per row, not per name: ALLOCR keeps one setpoint per unit record even if names repeat.
    allocation = allocate_regulation_by_unit(case.units, ace, CONTROL_INTERVAL_S)
    return RtgenaceResult(
        savecase=case.name,
        ace_mw=ace,
        setpoints=[(unit.name, mw) for unit, mw in zip(case.units, allocation, strict=True)],
    )


def _fortran_f(value: float, width: int = 12, decimals: int = 4) -> str:
    """Fortran ``Fw.d`` edit descriptor: a value that does not fit prints as ``*`` x w."""
    text = f"{value:{width}.{decimals}f}"
    return "*" * width if len(text) > width else text


def format_report(result: RtgenaceResult) -> list[str]:
    """Lines in the legacy layout: ``(A,A)``, ``(A,F12.4)``, ``(A,A20,F12.4)``."""
    lines = [f"SAVECASE {result.savecase[:32]}", f"ACE_MW   {_fortran_f(result.ace_mw)}"]
    lines += [f"SETPT    {name[:20]:<20}{_fortran_f(mw)}" for name, mw in result.setpoints]
    return lines


def legacy_setpoints_consistent(
    case: Savecase, legacy_ace_mw: float, legacy_setpoints: list[float]
) -> bool:
    """Judge legacy setpoints for a savecase whose ACE is ``deadband_indeterminate``.

    The printed legacy ACE is the Fortran's own value rounded to 4 decimals, so it
    fixes which side of the deadband the Fortran was on, except when it prints exactly
    5.0000: then the deadband may or may not have been taken. Outside the deadband the
    setpoints must match the allocation for the legacy ACE within the setpoint bound;
    inside it they must all be zero; at 5.0000 either is consistent."""
    deadband_taken = all(mw == 0.0 for mw in legacy_setpoints)
    expected = allocate_regulation_by_unit(
        case.units, legacy_ace_mw, CONTROL_INTERVAL_S, deadband_mw=0.0
    )
    regulated = len(expected) == len(legacy_setpoints) and all(
        abs(ours - theirs) <= setpoint_parity_bound(case, index, legacy_ace_mw)
        for index, (ours, theirs) in enumerate(zip(expected, legacy_setpoints, strict=True))
    )
    if abs(abs(legacy_ace_mw) - DEADBAND_MW) < PRINT_RESOLUTION_MW / 2:
        return deadband_taken or regulated
    if abs(legacy_ace_mw) > DEADBAND_MW:
        return regulated
    return deadband_taken


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("RTGENACE: usage: rtgenace <savecase-export>")
        return EXIT_USAGE
    try:
        case = load_savecase(Path(args[0]))
    except SavecaseError as exc:
        print(f"RTGENACE: savecase read failed, ierr={exc.ierr:2d}")
        return EXIT_READ_FAILED
    print("\n".join(format_report(run(case))))
    return EXIT_OK


def _float32_error(value: float) -> float:
    """How far ``value`` moves when the Fortran stores it as REAL (binary32)."""
    return abs(struct.unpack("f", struct.pack("f", value))[0] - value)


def ace_parity_bound(case: Savecase) -> float:
    """Worst-case |legacy ACE - modern ACE| caused by single precision.

    Every input is weighted by its sensitivity in RPTACE (the frequencies by the
    10B bias factor), and each of the n + 4 float32 operations contributes at
    most one unit roundoff of the magnitudes involved.
    """
    ties = case.tie_lines
    bias = case.frequency_bias_mw_per_0_1hz
    freq_error = case.actual_frequency_hz - case.scheduled_frequency_hz
    representation = (
        sum(_float32_error(t.actual_mw) + _float32_error(t.scheduled_mw) for t in ties)
        + 10.0
        * abs(bias)
        * (_float32_error(case.actual_frequency_hz) + _float32_error(case.scheduled_frequency_hz))
        + 10.0 * abs(freq_error) * _float32_error(bias)
        + _float32_error(case.meter_error_mw)
    )
    magnitude = (
        sum(abs(t.actual_mw) + abs(t.scheduled_mw) for t in ties)
        + 10.0 * abs(bias * freq_error)
        + abs(case.meter_error_mw)
    )
    arithmetic = (len(ties) + 4) * _FLOAT32_UNIT_ROUNDOFF * magnitude
    return representation + arithmetic + PRINT_RESOLUTION_MW


def setpoint_parity_bound(case: Savecase, unit_index: int, ace_mw: float) -> float:
    """Worst-case |legacy - modern| regulation setpoint for one unit (ALLOCR)."""
    unit = case.units[unit_index]
    if not unit.on_agc or unit.participation <= 0.0:
        return PRINT_RESOLUTION_MW
    pool = [u.participation for u in case.units if u.on_agc and u.participation > 0.0]
    total = sum(pool)
    ratio = unit.participation / total
    share_error = (
        ratio * ace_parity_bound(case)
        + abs(ace_mw)
        * (_float32_error(unit.participation) + ratio * sum(_float32_error(p) for p in pool))
        / total
    )
    limits_error = (
        _float32_error(unit.ramp_mw_per_min) * CONTROL_INTERVAL_S / 60.0
        + _float32_error(unit.output_mw)
        + _float32_error(unit.min_mw)
        + _float32_error(unit.max_mw)
    )
    magnitude = abs(unit.output_mw) + abs(unit.min_mw) + abs(unit.max_mw) + abs(ace_mw)
    arithmetic = (len(pool) + 6) * _FLOAT32_UNIT_ROUNDOFF * magnitude
    return share_error + limits_error + arithmetic + 2 * PRINT_RESOLUTION_MW


def deadband_indeterminate(case: Savecase, ace_mw: float) -> bool:
    """True when single precision alone could move ACE across the 5 MW deadband."""
    return abs(abs(ace_mw) - DEADBAND_MW) <= ace_parity_bound(case)


if __name__ == "__main__":
    sys.exit(main())
