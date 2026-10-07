"""Pins the unmodified legacy RTGENACE output (spec §3, §4, §6, §7)."""

from __future__ import annotations

import math

import pytest
from legacy_harness import run_legacy
from rtgenace_cases import LEGACY, RTGENACE_CASES

pytestmark = pytest.mark.characterization


def same_number(observed: float | None, pinned: float | None) -> bool:
    if observed is None or pinned is None:
        return observed is pinned
    if math.isnan(pinned):
        return math.isnan(observed)
    return observed == pinned


@pytest.mark.parametrize("case", RTGENACE_CASES, ids=lambda case: f"{case.id}-{case.requirements}")
def test_legacy_rtgenace_output_is_pinned(case):
    pinned = LEGACY[case.id]
    observed = run_legacy(case.text)

    assert observed.returncode == pinned.rc, observed.stdout
    assert observed.name == pinned.name
    assert same_number(observed.ace, pinned.ace), f"ACE {observed.ace} != pinned {pinned.ace}"
    assert [unit for unit, _ in observed.setpoints] == [unit for unit, _ in pinned.setpoints]
    for (unit, mw), (_, pinned_mw) in zip(observed.setpoints, pinned.setpoints, strict=True):
        assert same_number(mw, pinned_mw), f"{unit}: {mw} != pinned {pinned_mw}"
