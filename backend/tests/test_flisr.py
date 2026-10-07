"""The only automated coverage the distribution services have today."""

from __future__ import annotations

import pytest

from app.flisr import build_plan, locate_fault
from app.network import get_feeder, load_network, switch_by_mrid


def cedar_ridge():
    return get_feeder(load_network(), "FDR-1201")


def test_locate_fault_picks_section_beyond_last_indication():
    feeder = cedar_ridge()

    assert locate_fault(feeder) == "SEC-1201-03"


def test_build_plan_isolates_and_restores_tail():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert plan.faulted_section == "SEC-1201-03"
    assert {step.switch_mrid for step in plan.isolation} == {
        "SEC-SW-1201-1",
        "REC-1201-2",
    }
    assert plan.customers_restored == 341


def _plan_for(indications, tie_capacity_kw):
    feeder = cedar_ridge()
    for section, indicated in zip(feeder.sections, indications, strict=True):
        section.fault_indicator = indicated
    switch_by_mrid(feeder, "CB-1201").open = True
    return locate_fault(feeder), build_plan(
        feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": tie_capacity_kw}
    )


def _steps(steps):
    return [(step.switch_mrid, step.action, step.reason) for step in steps]


@pytest.mark.characterization
@pytest.mark.parametrize(
    ("indications", "expected"),
    [
        ((False, False, False, False), None),
        ((True, False, False, False), "SEC-1201-02"),
        ((True, True, False, False), "SEC-1201-03"),
        ((True, True, True, False), "SEC-1201-04"),
        ((True, True, True, True), "SEC-1201-04"),
        ((True, False, True, False), "SEC-1201-04"),
    ],
)
def test_pinned_linear_fault_location(indications, expected):
    located, plan = _plan_for(indications, 2000.0)

    assert located == expected
    assert plan.faulted_section == expected


@pytest.mark.characterization
def test_pinned_plan_without_indication():
    _, plan = _plan_for((False, False, False, False), 2000.0)

    assert plan.isolation == []
    assert plan.restoration == []
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 1117
    assert plan.transferred_load_kw == 0.0
    assert plan.notes == ["no fault indication received; manual patrol required"]


@pytest.mark.characterization
def test_pinned_plan_fault_on_mill_road_with_tie_capacity():
    _, plan = _plan_for((True, False, False, False), 2000.0)

    assert _steps(plan.isolation) == [
        ("REC-1201-1", "open", "upstream isolation of Mill Road lateral"),
        ("SEC-SW-1201-1", "open", "downstream isolation of Mill Road lateral"),
    ]
    assert _steps(plan.restoration) == [
        ("CB-1201", "close", "re-energise healthy sections upstream of the fault"),
        ("TIE-1201-1405", "close", "back-feed 5 nodes from alternate source"),
    ]
    assert plan.customers_restored == 437
    assert plan.customers_remaining == 268
    assert plan.transferred_load_kw == 1920.0
    assert plan.notes == []


@pytest.mark.characterization
def test_pinned_plan_fault_on_mill_road_without_tie_capacity():
    _, plan = _plan_for((True, False, False, False), 100.0)

    assert _steps(plan.isolation) == [
        ("REC-1201-1", "open", "upstream isolation of Mill Road lateral"),
        ("SEC-SW-1201-1", "open", "downstream isolation of Mill Road lateral"),
    ]
    assert _steps(plan.restoration) == [
        ("CB-1201", "close", "re-energise healthy sections upstream of the fault"),
    ]
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 705
    assert plan.transferred_load_kw == 0.0
    assert plan.notes == [
        "Hollow Creek tie to 1405 skipped: 1920 kW exceeds 100 kW available capacity"
    ]


@pytest.mark.characterization
def test_pinned_plan_fault_on_quarry_crossing_with_tie_capacity():
    _, plan = _plan_for((True, True, False, False), 2000.0)

    assert _steps(plan.isolation) == [
        ("SEC-SW-1201-1", "open", "upstream isolation of Quarry Crossing"),
        ("REC-1201-2", "open", "downstream isolation of Quarry Crossing"),
    ]
    assert _steps(plan.restoration) == [
        ("CB-1201", "close", "re-energise healthy sections upstream of the fault"),
        ("TIE-1201-1405", "close", "back-feed 3 nodes from alternate source"),
    ]
    assert plan.customers_restored == 341
    assert plan.customers_remaining == 96
    assert plan.transferred_load_kw == 1490.0
    assert plan.notes == []


@pytest.mark.characterization
def test_pinned_plan_fault_on_quarry_crossing_without_tie_capacity():
    _, plan = _plan_for((True, True, False, False), 100.0)

    assert _steps(plan.isolation) == [
        ("SEC-SW-1201-1", "open", "upstream isolation of Quarry Crossing"),
        ("REC-1201-2", "open", "downstream isolation of Quarry Crossing"),
    ]
    assert _steps(plan.restoration) == [
        ("CB-1201", "close", "re-energise healthy sections upstream of the fault"),
    ]
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 437
    assert plan.transferred_load_kw == 0.0
    assert plan.notes == [
        "Hollow Creek tie to 1405 skipped: 1490 kW exceeds 100 kW available capacity"
    ]


@pytest.mark.characterization
def test_pinned_plan_fault_on_hollow_creek_tail_without_tie_capacity():
    _, plan = _plan_for((True, True, True, False), 100.0)

    assert _steps(plan.isolation) == [
        ("REC-1201-2", "open", "upstream isolation of Hollow Creek tail"),
    ]
    assert _steps(plan.restoration) == [
        ("CB-1201", "close", "re-energise healthy sections upstream of the fault"),
    ]
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 682
    assert plan.transferred_load_kw == 0.0
    assert plan.notes == [
        "Hollow Creek tie to 1405 skipped: 1490 kW exceeds 100 kW available capacity"
    ]
