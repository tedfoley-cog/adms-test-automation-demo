"""Measurement conditioning: bad-data detection and convergence reporting."""

from __future__ import annotations

import pytest

from app.models import Measurement
from app.state_estimator import (
    BAD_DATA_THRESHOLD,
    EstimationResult,
    convergence_metric,
    estimate,
)


def measurement(value: float, sigma: float = 1.0, mrid: str = "MEAS-1201", **kwargs):
    return Measurement(mrid=mrid, kind="P", value=value, sigma=sigma, **kwargs)


def test_no_usable_measurements_is_unobservable():
    result = estimate([measurement(10.0, valid=False), measurement(11.0, sigma=0.0)])

    assert result == EstimationResult({}, {}, [], observable=False, iterations=0)


def test_consistent_measurements_are_averaged_and_observable():
    result = estimate([measurement(100.0), measurement(100.5), measurement(99.5)])

    assert result.observable is True
    assert result.estimated["MEAS-1201:P"] == pytest.approx(100.0)
    assert result.rejected == []
    assert result.iterations == 1


def test_weighted_mean_favours_the_tighter_sigma():
    result = estimate([measurement(100.0, sigma=0.5), measurement(101.0, sigma=1.0)])

    # weights 4 and 1: (4*100 + 1*101) / 5
    assert result.estimated["MEAS-1201:P"] == pytest.approx(100.2)
    assert result.rejected == []


def test_single_measurement_per_state_is_not_observable():
    result = estimate([measurement(100.0), measurement(50.0, mrid="MEAS-1405")])

    assert result.observable is False
    assert set(result.estimated) == {"MEAS-1201:P", "MEAS-1405:P"}


def test_bad_data_is_rejected_above_the_threshold():
    result = estimate(
        [
            measurement(100.0),
            measurement(100.0),
            measurement(100.0),
            measurement(140.0),
        ]
    )

    assert result.rejected == ["MEAS-1201:P"]
    assert result.estimated["MEAS-1201:P"] == pytest.approx(100.0)
    assert result.residuals["MEAS-1201:P"] == pytest.approx(0.0)
    assert result.iterations == 2


def test_residual_at_the_threshold_is_kept():
    """A normalised residual of exactly 3.0 sigma passes the chi-square screen."""
    result = estimate([measurement(0.0), measurement(6.0)])

    assert result.residuals["MEAS-1201:P"] == pytest.approx(BAD_DATA_THRESHOLD)
    assert result.rejected == []


def test_residual_just_above_the_threshold_is_rejected():
    result = estimate([measurement(0.0), measurement(6.02)])

    assert result.rejected == ["MEAS-1201:P"]
    # one survivor left, so the estimate collapses onto it
    assert result.residuals["MEAS-1201:P"] == pytest.approx(0.0)


def test_rejection_stops_when_one_measurement_remains():
    result = estimate([measurement(0.0), measurement(100.0)])

    assert len(result.rejected) == 1
    assert result.iterations == 2


def test_iterations_are_capped():
    values = [measurement(100.0), measurement(100.0)] + [
        measurement(100.0 + 50.0 * i) for i in range(1, 8)
    ]

    result = estimate(values, max_iterations=3)

    assert result.iterations == 3
    assert len(result.rejected) == 3
    # the screen ran out of iterations before it converged, so no estimate is reported
    assert result.estimated == {}


def test_measurements_are_grouped_by_mrid_and_kind():
    result = estimate(
        [
            Measurement(mrid="MEAS-1201", kind="P", value=100.0, sigma=1.0),
            Measurement(mrid="MEAS-1201", kind="P", value=102.0, sigma=1.0),
            Measurement(mrid="MEAS-1201", kind="Q", value=30.0, sigma=1.0),
            Measurement(mrid="MEAS-1201", kind="Q", value=32.0, sigma=1.0),
        ]
    )

    assert result.estimated == {
        "MEAS-1201:P": pytest.approx(101.0),
        "MEAS-1201:Q": pytest.approx(31.0),
    }
    assert result.observable is True


def test_redundancy_floor_controls_observability():
    measurements = [measurement(100.0), measurement(100.5), measurement(99.5)]

    assert estimate(measurements, redundancy_floor=3.0).observable is True
    assert estimate(measurements, redundancy_floor=3.5).observable is False


def test_convergence_metric_is_rms_of_residuals():
    result = EstimationResult(
        estimated={},
        residuals={"a": 3.0, "b": 4.0},
        rejected=[],
        observable=True,
        iterations=1,
    )

    assert convergence_metric(result) == pytest.approx(3.5355339)


def test_convergence_metric_without_residuals_is_zero():
    assert convergence_metric(EstimationResult({}, {}, [], observable=False, iterations=0)) == 0.0
