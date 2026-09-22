"""The only automated coverage the distribution services have today."""

from __future__ import annotations

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
