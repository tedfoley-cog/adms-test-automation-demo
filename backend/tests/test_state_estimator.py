"""Unit coverage for measurement conditioning: bad-data detection and convergence."""

from __future__ import annotations

import math

import pytest

from app.models import Measurement
from app.state_estimator import (
    BAD_DATA_THRESHOLD,
    EstimationResult,
    convergence_metric,
    estimate,
)


def measurement(
    mrid: str,
    value: float,
    *,
    kind: str = "P",
    sigma: float = 1.0,
    valid: bool = True,
) -> Measurement:
    return Measurement(mrid=mrid, kind=kind, value=value, sigma=sigma, valid=valid)


def test_no_usable_measurements_is_unobservable():
    result = estimate([])

    assert result.observable is False
    assert result.iterations == 0
    assert result.estimated == {}
    assert result.rejected == []


def test_invalid_and_zero_sigma_measurements_are_discarded():
    result = estimate(
        [
            measurement("BUS.1", 10.0, valid=False),
            measurement("BUS.1", 10.0, sigma=0.0),
        ]
    )

    assert result.observable is False
    assert result.estimated == {}


def test_redundant_measurements_are_averaged_by_inverse_variance():
    result = estimate(
        [
            measurement("BUS.1", 100.0, sigma=1.0),
            measurement("BUS.1", 106.0, sigma=2.0),
        ]
    )

    # weights 1 and 1/4 -> (100 + 106/4) / (1 + 1/4)
    assert result.estimated["BUS.1:P"] == pytest.approx(101.2)
    assert result.rejected == []


def test_measurements_of_different_kinds_form_separate_states():
    result = estimate(
        [
            measurement("BUS.1", 100.0),
            measurement("BUS.1", 100.0, kind="Q"),
            measurement("BUS.1", 100.0, kind="Q"),
        ]
    )

    assert set(result.estimated) == {"BUS.1:P", "BUS.1:Q"}


def test_redundancy_below_the_floor_is_unobservable():
    result = estimate([measurement("BUS.1", 100.0), measurement("BUS.2", 100.0)])

    # one measurement per state: redundancy 1.0 < 1.2
    assert result.observable is False


def test_redundancy_at_or_above_the_floor_is_observable():
    result = estimate(
        [
            measurement("BUS.1", 100.0),
            measurement("BUS.1", 100.5),
            measurement("BUS.2", 50.0),
        ]
    )

    assert result.observable is True


def test_residual_just_below_the_threshold_is_kept():
    # Two symmetric measurements: each sits 2.9 sigma from the mean.
    result = estimate(
        [
            measurement("BUS.1", 100.0 - 2.9, sigma=1.0),
            measurement("BUS.1", 100.0 + 2.9, sigma=1.0),
        ]
    )

    assert result.rejected == []
    assert result.residuals["BUS.1:P"] == pytest.approx(BAD_DATA_THRESHOLD - 0.1)
    assert result.estimated["BUS.1:P"] == pytest.approx(100.0)


def test_residual_above_the_threshold_rejects_the_worst_measurement():
    result = estimate(
        [
            measurement("BUS.1", 100.0, sigma=1.0),
            measurement("BUS.1", 100.5, sigma=1.0),
            measurement("BUS.1", 140.0, sigma=1.0),
        ]
    )

    assert result.rejected == ["BUS.1:P"]
    assert result.estimated["BUS.1:P"] == pytest.approx(100.25)
    assert result.residuals["BUS.1:P"] < BAD_DATA_THRESHOLD


def test_rejection_is_iterative_and_bounded_by_max_iterations():
    measurements = [
        measurement("BUS.1", 100.0),
        measurement("BUS.1", 100.2),
        measurement("BUS.1", 100.4),
        measurement("BUS.1", 400.0),
        measurement("BUS.1", 900.0),
    ]

    result = estimate(measurements, max_iterations=2)

    # One rejection per iteration, and the loop stops at max_iterations without
    # ever accepting a value for the state.
    assert result.rejected == ["BUS.1:P", "BUS.1:P"]
    assert result.iterations == 2
    assert "BUS.1:P" not in result.estimated
    assert "BUS.1:P" not in result.residuals


def test_a_tight_sigma_makes_a_small_deviation_bad_data():
    result = estimate(
        [
            measurement("BUS.1", 100.0, sigma=0.01),
            measurement("BUS.1", 100.0, sigma=0.01),
            measurement("BUS.1", 100.2, sigma=0.01),
        ]
    )

    assert result.rejected == ["BUS.1:P"]
    assert result.estimated["BUS.1:P"] == pytest.approx(100.0)


def test_the_last_survivor_is_accepted_without_a_residual_test():
    result = estimate([measurement("BUS.1", 100.0), measurement("BUS.1", 900.0)])

    # Two equally deviant measurements: the first one found is dropped and the
    # lone survivor becomes the state, however implausible it is.
    assert result.rejected == ["BUS.1:P"]
    assert result.estimated["BUS.1:P"] == pytest.approx(900.0)
    assert result.residuals["BUS.1:P"] == pytest.approx(0.0)


def test_convergence_metric_of_an_empty_result_is_zero():
    assert convergence_metric(EstimationResult({}, {}, [], observable=False, iterations=0)) == 0.0


def test_convergence_metric_is_the_rms_of_the_residuals():
    result = EstimationResult({}, {"a": 3.0, "b": 4.0}, [], observable=True, iterations=1)

    assert convergence_metric(result) == pytest.approx(math.sqrt(12.5))


def test_convergence_metric_of_a_clean_solution_is_small():
    result = estimate(
        [
            measurement("BUS.1", 100.0, sigma=1.0),
            measurement("BUS.1", 100.0, sigma=1.0),
        ]
    )

    assert convergence_metric(result) == pytest.approx(0.0)
