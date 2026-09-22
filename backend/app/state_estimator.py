"""Weighted least-squares style state estimation support.

The production estimator solves the full WLS problem; this service exposes the
measurement conditioning that feeds it: bad-data detection with the normalised
residual test, observability screening and per-feeder residual reporting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Measurement

BAD_DATA_THRESHOLD = 3.0  # normalised residual, chi-square screening


@dataclass
class EstimationResult:
    estimated: dict[str, float]
    residuals: dict[str, float]
    rejected: list[str]
    observable: bool
    iterations: int


def _weighted_mean(values: list[tuple[float, float]]) -> float:
    numerator = sum(value / (sigma**2) for value, sigma in values)
    denominator = sum(1.0 / (sigma**2) for _, sigma in values)
    return numerator / denominator


def estimate(
    measurements: list[Measurement],
    redundancy_floor: float = 1.2,
    max_iterations: int = 5,
) -> EstimationResult:
    """Iteratively reconcile redundant measurements of the same quantity."""
    usable = [m for m in measurements if m.valid and m.sigma > 0.0]
    if not usable:
        return EstimationResult({}, {}, [], observable=False, iterations=0)

    groups: dict[str, list[Measurement]] = {}
    for measurement in usable:
        groups.setdefault(f"{measurement.mrid}:{measurement.kind}", []).append(measurement)

    states = len(groups)
    observable = (len(usable) / states) >= redundancy_floor if states else False

    estimated: dict[str, float] = {}
    residuals: dict[str, float] = {}
    rejected: list[str] = []
    iterations = 0

    for key, group in groups.items():
        active = list(group)
        for iteration in range(1, max_iterations + 1):
            iterations = max(iterations, iteration)
            value = _weighted_mean([(m.value, m.sigma) for m in active])
            worst: Measurement | None = None
            worst_residual = 0.0
            for measurement in active:
                normalised = abs(measurement.value - value) / measurement.sigma
                if normalised > worst_residual:
                    worst, worst_residual = measurement, normalised
            if worst is None or worst_residual <= BAD_DATA_THRESHOLD or len(active) <= 1:
                estimated[key] = value
                residuals[key] = worst_residual
                break
            active = [m for m in active if m is not worst]
            rejected.append(f"{worst.mrid}:{worst.kind}")

    return EstimationResult(estimated, residuals, rejected, observable, iterations)


def convergence_metric(result: EstimationResult) -> float:
    """Root-mean-square of the reported normalised residuals."""
    if not result.residuals:
        return 0.0
    total = sum(value**2 for value in result.residuals.values())
    return math.sqrt(total / len(result.residuals))
