"""Characterization of build_plan on FDR-1201 inputs it already handles correctly.

Pinned before the DEF-FLISR-7 fix (STD-SAFETY-2): these plans must not change.
"""

from __future__ import annotations

import pytest

from app.flisr import FlisrError, build_plan
from app.network import get_feeder, load_network, switch_by_mrid

pytestmark = [pytest.mark.characterization, pytest.mark.requirement("DEF-FLISR-7")]

TIE_2000 = {"TIE-1201-1405": 2000.0}
# REQ-TIECAP-11 (U2): blocked_ties is compared on its own, every other field as pinned.
NEW_FIELDS = {"blocked_ties"}


def cedar_ridge_in_lockout(indicated: set[str] | None = None):
    feeder = get_feeder(load_network(), "FDR-1201")
    if indicated is not None:
        for section in feeder.sections:
            section.fault_indicator = section.mrid in indicated
    switch_by_mrid(feeder, "CB-1201").open = True
    return feeder


def test_def_flisr_7_char_shipped_fault_sec_1201_03_full_plan():
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity_kw=TIE_2000)

    assert plan.blocked_ties == []
    assert plan.model_dump(exclude=NEW_FIELDS) == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": "SEC-1201-03",
        "isolation": [
            {"switch_mrid": "SEC-SW-1201-1", "action": "open",
             "reason": "upstream isolation of Quarry Crossing"},
            {"switch_mrid": "REC-1201-2", "action": "open",
             "reason": "downstream isolation of Quarry Crossing"},
        ],
        "restoration": [
            {"switch_mrid": "CB-1201", "action": "close",
             "reason": "re-energise healthy sections upstream of the fault"},
            {"switch_mrid": "TIE-1201-1405", "action": "close",
             "reason": "back-feed 3 nodes from alternate source"},
        ],
        "customers_restored": 341,
        "customers_remaining": 96,
        "transferred_load_kw": 1490.0,
        "notes": [],
    }


def test_def_flisr_7_char_fault_sec_1201_02_full_plan():
    plan = build_plan(
        cedar_ridge_in_lockout({"SEC-1201-01"}), "CB-1201", tie_capacity_kw=TIE_2000
    )

    assert plan.blocked_ties == []
    assert plan.model_dump(exclude=NEW_FIELDS) == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": "SEC-1201-02",
        "isolation": [
            {"switch_mrid": "REC-1201-1", "action": "open",
             "reason": "upstream isolation of Mill Road lateral"},
            {"switch_mrid": "SEC-SW-1201-1", "action": "open",
             "reason": "downstream isolation of Mill Road lateral"},
        ],
        "restoration": [
            {"switch_mrid": "CB-1201", "action": "close",
             "reason": "re-energise healthy sections upstream of the fault"},
            {"switch_mrid": "TIE-1201-1405", "action": "close",
             "reason": "back-feed 5 nodes from alternate source"},
        ],
        "customers_restored": 437,
        "customers_remaining": 268,
        "transferred_load_kw": 1920.0,
        "notes": [],
    }


def test_def_flisr_7_char_fault_sec_1201_03_tie_capacity_short():
    plan = build_plan(
        cedar_ridge_in_lockout(), "CB-1201", tie_capacity_kw={"TIE-1201-1405": 1000.0}
    )

    assert plan.blocked_ties == []
    assert plan.model_dump(exclude=NEW_FIELDS) == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": "SEC-1201-03",
        "isolation": [
            {"switch_mrid": "SEC-SW-1201-1", "action": "open",
             "reason": "upstream isolation of Quarry Crossing"},
            {"switch_mrid": "REC-1201-2", "action": "open",
             "reason": "downstream isolation of Quarry Crossing"},
        ],
        "restoration": [
            {"switch_mrid": "CB-1201", "action": "close",
             "reason": "re-energise healthy sections upstream of the fault"},
        ],
        "customers_restored": 0,
        "customers_remaining": 437,
        "transferred_load_kw": 0.0,
        "notes": ["Hollow Creek tie to 1405 skipped: 1490 kW exceeds 1000 kW available capacity"],
    }


def test_def_flisr_7_char_no_fault_indication_requires_patrol():
    plan = build_plan(cedar_ridge_in_lockout(set()), "CB-1201", tie_capacity_kw=TIE_2000)

    assert plan.blocked_ties == []
    assert plan.model_dump(exclude=NEW_FIELDS) == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": None,
        "isolation": [],
        "restoration": [],
        "customers_restored": 0,
        "customers_remaining": 1117,
        "transferred_load_kw": 0.0,
        "notes": ["no fault indication received; manual patrol required"],
    }


def test_def_flisr_7_char_refuses_when_lockout_switch_closed():
    feeder = get_feeder(load_network(), "FDR-1201")

    with pytest.raises(FlisrError, match="Cedar Ridge 1201 breaker is not in lockout"):
        build_plan(feeder, "CB-1201", tie_capacity_kw=TIE_2000)
