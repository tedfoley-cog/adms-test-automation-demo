"""Unit coverage for the AGC service: Reporting ACE and regulation allocation."""

from __future__ import annotations

import pytest

from app.agc import DEADBAND_MW, allocate_regulation, reporting_ace
from app.models import BalancingState, TieLine, Unit


def balancing_state(
    *,
    actual: list[float],
    scheduled: list[float],
    actual_hz: float = 60.0,
    scheduled_hz: float = 60.0,
    bias: float = -100.0,
    meter_error: float = 0.0,
) -> BalancingState:
    lines = [
        TieLine(name=f"TIE.{index}", actual_mw=a, scheduled_mw=s)
        for index, (a, s) in enumerate(zip(actual, scheduled, strict=True))
    ]
    return BalancingState(
        tie_lines=lines,
        actual_frequency_hz=actual_hz,
        scheduled_frequency_hz=scheduled_hz,
        frequency_bias_mw_per_0_1hz=bias,
        meter_error_mw=meter_error,
    )


def unit(
    name: str,
    output: float,
    *,
    minimum: float = 0.0,
    maximum: float = 500.0,
    ramp: float = 600.0,
    participation: float = 0.5,
    on_agc: bool = True,
) -> Unit:
    return Unit(
        name=name,
        output_mw=output,
        min_mw=minimum,
        max_mw=maximum,
        ramp_mw_per_min=ramp,
        participation=participation,
        on_agc=on_agc,
    )


def test_reporting_ace_is_interchange_error_when_on_schedule_frequency():
    state = balancing_state(actual=[418.2, -132.6], scheduled=[400.0, -140.0])

    assert reporting_ace(state) == pytest.approx(25.6)


def test_reporting_ace_subtracts_the_frequency_bias_term():
    state = balancing_state(
        actual=[100.0], scheduled=[100.0], actual_hz=59.95, bias=-412.0
    )

    # -10 * -412.0 * -0.05 = -206.0, subtracted from a zero interchange error.
    assert reporting_ace(state) == pytest.approx(-206.0, abs=1e-6)


def test_reporting_ace_subtracts_the_metering_error():
    state = balancing_state(actual=[100.0], scheduled=[90.0], meter_error=2.5)

    assert reporting_ace(state) == pytest.approx(7.5)


def test_reporting_ace_of_a_balanced_area_is_zero():
    state = balancing_state(actual=[50.0, 50.0], scheduled=[50.0, 50.0])

    assert reporting_ace(state) == pytest.approx(0.0)


@pytest.mark.parametrize("ace", [0.0, DEADBAND_MW, -DEADBAND_MW, 4.9])
def test_ace_inside_the_deadband_moves_no_unit(ace: float):
    units = [unit("GEN.A", 100.0), unit("GEN.B", 100.0)]

    assert allocate_regulation(units, ace) == {"GEN.A": 0.0, "GEN.B": 0.0}


def test_allocation_splits_the_correction_by_participation_factor():
    units = [
        unit("GEN.A", 100.0, participation=0.75),
        unit("GEN.B", 100.0, participation=0.25),
    ]

    setpoints = allocate_regulation(units, ace_mw=-40.0)

    assert setpoints["GEN.A"] == pytest.approx(30.0)
    assert setpoints["GEN.B"] == pytest.approx(10.0)


def test_allocation_corrects_against_the_sign_of_the_ace():
    units = [unit("GEN.A", 100.0, participation=1.0)]

    assert allocate_regulation(units, ace_mw=20.0)["GEN.A"] == pytest.approx(-20.0)
    assert allocate_regulation(units, ace_mw=-20.0)["GEN.A"] == pytest.approx(20.0)


def test_units_off_agc_or_with_no_participation_are_excluded():
    units = [
        unit("GEN.ON", 100.0, participation=0.5),
        unit("GEN.OFF", 100.0, participation=0.5, on_agc=False),
        unit("GEN.BASELOAD", 100.0, participation=0.0),
    ]

    setpoints = allocate_regulation(units, ace_mw=-20.0)

    assert setpoints["GEN.OFF"] == 0.0
    assert setpoints["GEN.BASELOAD"] == 0.0
    # The whole correction lands on the only regulating unit.
    assert setpoints["GEN.ON"] == pytest.approx(20.0)


def test_no_regulating_units_leaves_every_setpoint_at_zero():
    units = [unit("GEN.A", 100.0, on_agc=False), unit("GEN.B", 100.0, participation=0.0)]

    assert allocate_regulation(units, ace_mw=-50.0) == {"GEN.A": 0.0, "GEN.B": 0.0}


def test_ramp_capability_clips_the_share_over_the_control_interval():
    # 6 MW/min over a 4 s cycle is 0.4 MW of movement.
    units = [unit("GEN.SLOW", 200.0, ramp=6.0, participation=1.0)]

    setpoints = allocate_regulation(units, ace_mw=-100.0, interval_s=4.0)

    assert setpoints["GEN.SLOW"] == pytest.approx(0.4)


def test_ramp_clipping_is_symmetric_for_a_downward_correction():
    units = [unit("GEN.SLOW", 200.0, ramp=6.0, participation=1.0)]

    setpoints = allocate_regulation(units, ace_mw=100.0, interval_s=4.0)

    assert setpoints["GEN.SLOW"] == pytest.approx(-0.4)


def test_a_longer_interval_allows_more_movement():
    units = [unit("GEN.SLOW", 200.0, ramp=6.0, participation=1.0)]

    assert allocate_regulation(units, ace_mw=-100.0, interval_s=60.0)["GEN.SLOW"] == pytest.approx(
        6.0
    )


def test_unit_maximum_caps_the_setpoint():
    units = [unit("GEN.TOPPED", 248.0, maximum=250.0, ramp=600.0, participation=1.0)]

    setpoints = allocate_regulation(units, ace_mw=-40.0)

    assert setpoints["GEN.TOPPED"] == pytest.approx(2.0)


def test_unit_minimum_floors_the_setpoint():
    units = [unit("GEN.FLOORED", 121.0, minimum=120.0, ramp=600.0, participation=1.0)]

    setpoints = allocate_regulation(units, ace_mw=40.0)

    assert setpoints["GEN.FLOORED"] == pytest.approx(-1.0)


def test_a_unit_already_at_its_limit_cannot_help():
    units = [unit("GEN.MAXED", 250.0, maximum=250.0, ramp=600.0, participation=1.0)]

    assert allocate_regulation(units, ace_mw=-40.0)["GEN.MAXED"] == pytest.approx(0.0)


def test_allocation_reports_every_unit_including_non_regulating_ones():
    units = [unit("GEN.A", 100.0), unit("GEN.B", 100.0, on_agc=False)]

    assert set(allocate_regulation(units, ace_mw=-20.0)) == {"GEN.A", "GEN.B"}
