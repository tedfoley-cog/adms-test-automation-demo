"""Pins the legacy HDB_READ_EXPORT reader as RTGENACE sees it (spec §2.1)."""

from __future__ import annotations

import pytest
from legacy_harness import run_legacy, run_legacy_path
from rtgenace_cases import HAB_SAVECASE_CASES, LEGACY

pytestmark = pytest.mark.characterization


@pytest.mark.parametrize("case", HAB_SAVECASE_CASES, ids=lambda case: f"{case.id}-{case.requirements}")
def test_legacy_reader_outcome_is_pinned(case):
    pinned = LEGACY[case.id]
    observed = run_legacy(case.text)

    assert observed.returncode == pinned.rc, observed.stdout
    assert observed.ierr == pinned.ierr
    assert observed.name == pinned.name
    assert observed.ace == pinned.ace
    assert observed.setpoints == pinned.setpoints


def test_h01_missing_export_is_ierr_1_exit_3():
    observed = run_legacy_path("/nonexistent/rtnet.export")
    assert (observed.returncode, observed.ierr) == (3, 1)


def test_h09_no_argument_prints_usage_exit_2():
    observed = run_legacy_path()
    assert observed.returncode == 2
    assert "usage: rtgenace <savecase-export>" in observed.stdout
