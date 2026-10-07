"""Safety invariants of the service's allocation over seeded fleets (spec §8)."""

from __future__ import annotations

import random

import pytest

from ace_service.ace import CONTROL_CYCLE_S, DEADBAND_MW, allocate_regulation, participates
from ace_service.schemas import Unit

FLEETS = 600
EPSILON = 1e-9


def random_fleet(rng: random.Random) -> list[Unit]:
    fleet = []
    for index in range(rng.randint(1, 16)):
        low = rng.uniform(0.0, 400.0)
        high = low + rng.uniform(0.0, 500.0)
        output = rng.uniform(low - 30.0, high + 30.0) if rng.random() < 0.1 else rng.uniform(low, high)
        fleet.append(
            Unit(
                id=f"GEN.{index}",
                output_mw=output,
                min_mw=low,
                max_mw=high,
                ramp_mw_per_min=rng.choice([0.0, rng.uniform(0.1, 60.0)]),
                participation=rng.choice([0.0, -0.2, rng.uniform(0.0, 1.0), rng.uniform(0.0, 1.0)]),
                on_agc=rng.random() < 0.85,
            )
        )
    return fleet


@pytest.mark.parametrize("seed", range(FLEETS))
def test_allocation_invariants(seed):
    rng = random.Random(seed)
    fleet = random_fleet(rng)
    ace = rng.choice([rng.uniform(-DEADBAND_MW, DEADBAND_MW), rng.uniform(-1500.0, 1500.0), DEADBAND_MW])

    deltas = allocate_regulation(fleet, ace)

    assert len(deltas) == len(fleet)
    if abs(ace) <= DEADBAND_MW:
        assert all(delta == 0.0 for delta in deltas)
        return
    for unit, delta in zip(fleet, deltas, strict=True):
        if not participates(unit):
            assert delta == 0.0
            continue
        target = unit.output_mw + delta
        if unit.min_mw <= unit.output_mw <= unit.max_mw:
            assert unit.min_mw - EPSILON <= target <= unit.max_mw + EPSILON
            assert abs(delta) <= unit.ramp_mw_per_min * CONTROL_CYCLE_S / 60.0 + EPSILON
            assert delta * ace <= EPSILON, "an in-limit unit must never move with ACE"
        else:
            assert target == pytest.approx(min(max(target, unit.min_mw), unit.max_mw))
