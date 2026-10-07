"""Pins FLISR plan construction on Cedar Ridge (FDR-1201) for inputs it handles correctly,
and records one confirmed defect as a strict xfail (not fixed in this change)."""

from __future__ import annotations

import pytest

from app.flisr import FlisrError, build_plan, locate_fault
from app.network import get_feeder, load_network, switch_by_mrid

TIE = "TIE-1201-1405"


def cedar_ridge(indicated: tuple[str, ...] | None = None, lockout: str | None = "CB-1201"):
    feeder = get_feeder(load_network(), "FDR-1201")
    if indicated is not None:
        for section in feeder.sections:
            section.fault_indicator = section.mrid in indicated
    if lockout:
        switch_by_mrid(feeder, lockout).open = True
    return feeder


def test_no_indication_asks_for_patrol_and_counts_everyone_downstream():
    plan = build_plan(cedar_ridge(indicated=()), "CB-1201")

    assert plan.faulted_section is None
    assert plan.isolation == [] and plan.restoration == []
    assert plan.notes == ["no fault indication received; manual patrol required"]
    assert plan.customers_remaining == 412 + 268 + 96 + 341


def test_refuses_when_lockout_switch_is_closed():
    with pytest.raises(FlisrError, match="is not in lockout"):
        build_plan(cedar_ridge(lockout=None), "CB-1201")


def test_lockout_closes_first_then_tie_back_feeds_the_tail():
    plan = build_plan(cedar_ridge(), "CB-1201", tie_capacity_kw={TIE: 2000.0})

    assert [(s.switch_mrid, s.action) for s in plan.restoration] == [
        ("CB-1201", "close"),
        (TIE, "close"),
    ]
    assert plan.transferred_load_kw == 1490.0
    assert plan.customers_remaining == 96
    assert plan.notes == []


@pytest.mark.parametrize("capacity", [None, {}, {TIE: 1489.0}])
def test_tie_skipped_without_enough_capacity(capacity):
    plan = build_plan(cedar_ridge(), "CB-1201", tie_capacity_kw=capacity)

    assert [s.switch_mrid for s in plan.restoration] == ["CB-1201"]
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 96 + 341
    assert (
        plan.notes[0].startswith("Hollow Creek Tie 1201-1405 skipped") or "skipped" in plan.notes[0]
    )
    assert "kW exceeds" in plan.notes[0]


def test_manual_lockout_device_is_not_reclosed_by_the_plan():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").scada_controllable = False

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={TIE: 2000.0})

    assert [s.switch_mrid for s in plan.restoration] == [TIE]


def test_refuses_when_no_scada_switch_can_isolate():
    feeder = cedar_ridge()
    for mrid in ("SEC-SW-1201-1", "REC-1201-2"):
        switch_by_mrid(feeder, mrid).scada_controllable = False

    with pytest.raises(FlisrError, match="no SCADA switch can isolate"):
        build_plan(feeder, "CB-1201")


def test_indication_on_the_last_section_locates_that_section():
    feeder = cedar_ridge(indicated=("SEC-1201-01", "SEC-1201-02", "SEC-1201-03", "SEC-1201-04"))

    assert locate_fault(feeder) == "SEC-1201-04"


@pytest.mark.xfail(
    strict=True,
    reason="FLISR-TIE-ONTO-FAULT: with the fault in the tail section the tie switch is not an "
    "isolation point, so the plan closes TIE-1201-1405 and back-feeds the faulted section",
)
def test_tail_fault_must_not_be_back_fed_through_the_tie():
    feeder = cedar_ridge(indicated=("SEC-1201-01", "SEC-1201-02", "SEC-1201-03", "SEC-1201-04"))

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={TIE: 2000.0})

    assert TIE not in {s.switch_mrid for s in plan.restoration if s.action == "close"}
