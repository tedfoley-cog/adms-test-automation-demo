"""FLISR: fault location, isolation and service restoration plans."""

from __future__ import annotations

import pytest

from app.flisr import FlisrError, build_plan, locate_fault
from app.models import Switch, SwitchKind
from app.network import energised_nodes, get_feeder, load_network, switch_by_mrid


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


def indicate(feeder, *section_mrids):
    for section in feeder.sections:
        section.fault_indicator = section.mrid in section_mrids


def test_locate_fault_without_indications_returns_none():
    feeder = cedar_ridge()
    indicate(feeder)

    assert locate_fault(feeder) is None


def test_locate_fault_on_last_section_when_every_section_indicates():
    feeder = cedar_ridge()
    indicate(feeder, *(section.mrid for section in feeder.sections))

    assert locate_fault(feeder) == "SEC-1201-04"


def test_build_plan_refuses_when_lockout_switch_is_closed():
    with pytest.raises(FlisrError, match="not in lockout"):
        build_plan(cedar_ridge(), "CB-1201")


def test_build_plan_rejects_unknown_lockout_switch():
    with pytest.raises(KeyError, match="unknown switch"):
        build_plan(cedar_ridge(), "CB-9999")


def test_no_indication_requests_patrol_and_counts_everyone_downstream():
    feeder = cedar_ridge()
    indicate(feeder)
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 5000.0})

    assert plan.faulted_section is None
    assert plan.isolation == [] and plan.restoration == []
    assert plan.notes == ["no fault indication received; manual patrol required"]
    assert plan.customers_remaining == 412 + 268 + 96 + 341


def test_full_plan_closes_lockout_first_then_back_feeds_tail():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert [(s.switch_mrid, s.action) for s in plan.restoration] == [
        ("CB-1201", "close"),
        ("TIE-1201-1405", "close"),
    ]
    assert plan.transferred_load_kw == 1490.0
    assert plan.customers_remaining == 96
    assert plan.notes == []


def test_tie_without_capacity_is_skipped_and_tail_stays_out():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 1000.0})

    assert [s.switch_mrid for s in plan.restoration] == ["CB-1201"]
    tie = switch_by_mrid(feeder, "TIE-1201-1405")
    assert plan.notes == [f"{tie.name} skipped: 1490 kW exceeds 1000 kW available capacity"]
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 96 + 341
    assert plan.transferred_load_kw == 0.0


def test_missing_tie_capacity_defaults_to_zero():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201")

    assert "exceeds 0 kW available capacity" in plan.notes[0]
    assert plan.customers_remaining == 96 + 341


def test_non_scada_tie_is_never_operated():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True
    switch_by_mrid(feeder, "TIE-1201-1405").scada_controllable = False

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 5000.0})

    assert [s.switch_mrid for s in plan.restoration] == ["CB-1201"]
    assert plan.customers_restored == 0


def test_non_scada_lockout_device_is_not_reclosed_by_the_plan():
    feeder = cedar_ridge()
    lockout = switch_by_mrid(feeder, "CB-1201")
    lockout.open = True
    lockout.scada_controllable = False

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 5000.0})

    assert [s.switch_mrid for s in plan.restoration] == ["TIE-1201-1405"]


def test_tie_that_picks_up_nothing_new_is_ignored():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "REC-1201-1").open = True
    feeder.switches.append(
        Switch(
            mrid="TIE-1201-CBBYPASS",
            name="CB-1201 bypass",
            kind=SwitchKind.TIE,
            normal_open=True,
            open=True,
            from_node="SRC-1201",
            to_node="BUS-1201",
        )
    )

    plan = build_plan(
        feeder,
        "REC-1201-1",
        tie_capacity_kw={"TIE-1201-1405": 5000.0, "TIE-1201-CBBYPASS": 1e6},
    )

    assert "TIE-1201-CBBYPASS" not in {s.switch_mrid for s in plan.restoration}
    assert not any("bypass" in note for note in plan.notes)
    assert [s.switch_mrid for s in plan.restoration] == ["REC-1201-1", "TIE-1201-1405"]


def test_fault_that_no_scada_switch_can_isolate_raises():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True
    for mrid in ("SEC-SW-1201-1", "REC-1201-2"):
        switch_by_mrid(feeder, mrid).scada_controllable = False

    with pytest.raises(FlisrError, match="no SCADA switch can isolate"):
        build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 5000.0})


def faulted_section_reenergised(feeder, plan) -> bool:
    """Apply the plan to a copy of the feeder and trace whether the faulted section is live."""
    after = feeder.model_copy(deep=True)
    for step in [*plan.isolation, *plan.restoration]:
        switch_by_mrid(after, step.switch_mrid).open = step.action == "open"
    faulted = next(s for s in after.sections if s.mrid == plan.faulted_section)
    live = energised_nodes(after)
    for switch in after.switches:
        if switch.kind is SwitchKind.TIE and not switch.open:
            live |= energised_nodes(after, switch.to_node)
    return faulted.from_node in live or faulted.to_node in live


def test_plan_never_reenergises_the_faulted_section_on_the_reference_case():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 5000.0})

    assert not faulted_section_reenergised(feeder, plan)


@pytest.mark.xfail(
    strict=True,
    reason="known defect: tie switches are never isolation points, so FLISR back-feeds a "
    "fault on the last section through the tie (reported, fix tracked separately)",
)
def test_plan_never_reenergises_a_fault_on_the_last_section():
    feeder = cedar_ridge()
    indicate(feeder, "SEC-1201-01", "SEC-1201-02", "SEC-1201-03")
    switch_by_mrid(feeder, "REC-1201-2").open = True

    plan = build_plan(feeder, "REC-1201-2", tie_capacity_kw={"TIE-1201-1405": 5000.0})

    assert not faulted_section_reenergised(feeder, plan)


@pytest.mark.xfail(
    strict=True,
    reason="known defect: with the downstream isolator not SCADA-controllable, FLISR closes "
    "the tie onto the faulted section (reported, fix tracked separately)",
)
def test_plan_never_reenergises_fault_when_downstream_isolator_is_manual():
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True
    switch_by_mrid(feeder, "REC-1201-2").scada_controllable = False

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 5000.0})

    assert not faulted_section_reenergised(feeder, plan)
