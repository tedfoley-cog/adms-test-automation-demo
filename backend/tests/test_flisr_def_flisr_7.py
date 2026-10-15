"""DEF-FLISR-7: restoration must not back-feed the faulted section."""

from __future__ import annotations

from app.flisr import build_plan
from app.network import energised_nodes, get_feeder, load_network, switch_by_mrid


def test_def_flisr_7_tie_does_not_back_feed_faulted_tail_section():
    feeder = get_feeder(load_network(), "FDR-1201")
    for section in feeder.sections:
        section.fault_indicator = section.mrid != "SEC-1201-04"
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert plan.faulted_section == "SEC-1201-04"
    for step in plan.isolation + plan.restoration:
        switch_by_mrid(feeder, step.switch_mrid).open = step.action == "open"
    faulted = next(s for s in feeder.sections if s.mrid == plan.faulted_section)
    live = energised_nodes(feeder) | energised_nodes(feeder, "ALT-1405")
    assert not ({faulted.from_node, faulted.to_node} & live), (
        f"plan re-energises {faulted.mrid}: "
        f"restoration={[(s.switch_mrid, s.action) for s in plan.restoration]}"
    )
