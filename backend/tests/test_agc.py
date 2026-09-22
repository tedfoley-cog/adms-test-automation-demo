"""Reporting ACE (NERC BAL-001) and regulation allocation."""

from __future__ import annotations

import pytest

from app.agc import DEADBAND_MW, allocate_regulation, reporting_ace
from app.models import BalancingState, TieLine, Unit


def balancing_state(**overrides) -> BalancingState:
    defaults = dict(
        tie_lines=[
            TieLine(name="TIE.NORTH340", actual_mw=418.2, scheduled_mw=400.0),
            TieLine(name="TIE.EAST115", actual_mw=-132.6, scheduled_mw=-140.0),
            TieLine(name="TIE.SOUTH230", actual_mw=97.4, scheduled_mw=105.0),
        ],
        actual_frequency_hz=59.968,
        scheduled_frequency_hz=60.0,
        frequency_bias_mw_per_0_1hz=-412.0,
        meter_error_mw=2.5,
    )
    defaults.update(overrides)
    return BalancingState(**defaults)


def agc_units() -> list[Unit]:
    return [
        Unit(
            name="GEN.HARBOR1",
            output_mw=212.0,
            min_mw=120.0,
            max_mw=260.0,
            ramp_mw_per_min=6.0,
            participation=0.45,
            on_agc=True,
        ),
        Unit(
            name="GEN.HARBOR2",
            output_mw=188.5,
            min_mw=120.0,
            max_mw=260.0,
            ramp_mw_per_min=6.0,
            participation=0.35,
            on_agc=True,
        ),
        Unit(
            name="GEN.MESQUITE_CT",
            output_mw=44.0,
            min_mw=20.0,
            max_mw=120.0,
            ramp_mw_per_min=18.0,
            participation=0.20,
            on_agc=True,
        ),
        Unit(
            name="GEN.CEDAR_STM",
            output_mw=305.0,
            min_mw=240.0,
            max_mw=340.0,
            ramp_mw_per_min=3.0,
            participation=0.0,
            on_agc=False,
        ),
    ]


def test_reporting_ace_matches_bal_001_definition():
    # (383.0 - 365.0) - 10 * (-412.0) * (-0.032) - 2.5
    assert reporting_ace(balancing_state()) == pytest.approx(-116.34, abs=1e-2)


def test_reporting_ace_is_zero_when_on_schedule():
    state = balancing_state(
        tie_lines=[TieLine(name="TIE.NORTH340", actual_mw=400.0, scheduled_mw=400.0)],
        actual_frequency_hz=60.0,
        meter_error_mw=0.0,
    )

    assert reporting_ace(state) == pytest.approx(0.0)


def test_reporting_ace_bias_term_responds_to_frequency():
    """Under-frequency with a negative bias setting pulls ACE negative."""
    over = reporting_ace(balancing_state(actual_frequency_hz=60.02))
    under = reporting_ace(balancing_state(actual_frequency_hz=59.98))

    assert over > under
    assert over - under == pytest.approx(10.0 * 412.0 * 0.04, abs=1e-6)


def test_reporting_ace_subtracts_meter_error():
    without = reporting_ace(balancing_state(meter_error_mw=0.0))
    with_error = reporting_ace(balancing_state(meter_error_mw=2.5))

    assert without - with_error == pytest.approx(2.5)


def test_allocation_inside_deadband_is_zero():
    setpoints = allocate_regulation(agc_units(), DEADBAND_MW)

    assert setpoints == {unit.name: 0.0 for unit in agc_units()}


def test_allocation_just_outside_deadband_moves_units():
    setpoints = allocate_regulation(agc_units(), DEADBAND_MW + 0.1)

    assert setpoints["GEN.HARBOR1"] < 0.0
    assert setpoints["GEN.CEDAR_STM"] == 0.0


def test_allocation_splits_by_participation_factor():
    """A correction small enough to stay inside every ramp limit splits by factor."""
    setpoints = allocate_regulation(agc_units(), -10.0, interval_s=60.0)

    assert setpoints["GEN.HARBOR1"] == pytest.approx(4.5)
    assert setpoints["GEN.HARBOR2"] == pytest.approx(3.5)
    assert setpoints["GEN.MESQUITE_CT"] == pytest.approx(2.0)
    assert setpoints["GEN.CEDAR_STM"] == 0.0
    assert sum(setpoints.values()) == pytest.approx(10.0)


def test_allocation_is_clipped_by_ramp_capability():
    """116.34 MW of correction over a 4 s cycle is ramp-bound on every unit."""
    setpoints = allocate_regulation(agc_units(), -116.34)

    assert setpoints["GEN.HARBOR1"] == pytest.approx(0.4)  # 6 MW/min * 4/60
    assert setpoints["GEN.HARBOR2"] == pytest.approx(0.4)
    assert setpoints["GEN.MESQUITE_CT"] == pytest.approx(1.2)  # 18 MW/min * 4/60


def test_allocation_respects_a_longer_control_interval():
    setpoints = allocate_regulation(agc_units(), -116.34, interval_s=60.0)

    assert setpoints["GEN.HARBOR1"] == pytest.approx(6.0)
    assert setpoints["GEN.MESQUITE_CT"] == pytest.approx(18.0)


def test_allocation_is_clipped_by_unit_maximum():
    units = agc_units()
    units[0].output_mw = 259.9
    units[0].ramp_mw_per_min = 600.0

    setpoints = allocate_regulation(units, -60.0)

    assert setpoints["GEN.HARBOR1"] == pytest.approx(0.1)


def test_allocation_is_clipped_by_unit_minimum():
    units = agc_units()
    units[0].output_mw = 120.05
    units[0].ramp_mw_per_min = 600.0

    setpoints = allocate_regulation(units, 60.0)

    assert setpoints["GEN.HARBOR1"] == pytest.approx(-0.05)


def test_allocation_skips_units_off_agc_and_zero_participation():
    units = agc_units()
    units[1].on_agc = False
    units[2].participation = 0.0

    setpoints = allocate_regulation(units, -10.0, interval_s=60.0)

    # sole regulating unit takes the whole correction, ramp-limited to 6 MW/min
    assert setpoints["GEN.HARBOR1"] == pytest.approx(6.0)
    assert setpoints["GEN.HARBOR2"] == 0.0
    assert setpoints["GEN.MESQUITE_CT"] == 0.0


def test_allocation_with_no_regulating_units():
    units = [unit for unit in agc_units() if not unit.on_agc]

    assert allocate_regulation(units, -50.0) == {"GEN.CEDAR_STM": 0.0}


def test_allocation_positive_ace_lowers_generation():
    setpoints = allocate_regulation(agc_units(), 116.34)

    assert setpoints["GEN.HARBOR1"] == pytest.approx(-0.4)
    assert setpoints["GEN.MESQUITE_CT"] == pytest.approx(-1.2)
