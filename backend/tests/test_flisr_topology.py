"""Fault location must follow the feeder, regardless of serialization order."""

from __future__ import annotations

import random

import pytest
from test_flisr import cedar_ridge

from app.flisr import FlisrError, build_plan, locate_fault
from app.models import Feeder, Section, Switch, SwitchKind
from app.network import energised_nodes, switch_by_mrid


@pytest.mark.characterization
@pytest.mark.parametrize("capacity", [2000.0, 1000.0])
def test_cedar_ridge_complete_plan_is_pinned(capacity: float):
    feeder = cedar_ridge()
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", {"TIE-1201-1405": capacity})

    assert plan.model_dump() == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": "SEC-1201-03",
        "isolation": [
            {
                "switch_mrid": "SEC-SW-1201-1",
                "action": "open",
                "reason": "upstream isolation of Quarry Crossing",
            },
            {
                "switch_mrid": "REC-1201-2",
                "action": "open",
                "reason": "downstream isolation of Quarry Crossing",
            },
        ],
        "restoration": [
            {
                "switch_mrid": "CB-1201",
                "action": "close",
                "reason": "re-energise healthy sections upstream of the fault",
            },
        ] + ([{
            "switch_mrid": "TIE-1201-1405",
            "action": "close",
            "reason": "back-feed 3 nodes from alternate source",
        }] if capacity == 2000.0 else []),
        "customers_restored": 341 if capacity == 2000.0 else 0,
        "customers_remaining": 96 if capacity == 2000.0 else 437,
        "transferred_load_kw": 1490.0 if capacity == 2000.0 else 0.0,
        "notes": [] if capacity == 2000.0 else [
            "Hollow Creek tie to 1405 skipped: 1490 kW exceeds 1000 kW available capacity"
        ],
    }


@pytest.mark.characterization
@pytest.mark.parametrize("indications, expected", [
    (0, None), (2, "SEC-1201-03"), (4, "SEC-1201-04"),
])
def test_cedar_ridge_fault_location_is_pinned(indications: int, expected: str | None):
    feeder = cedar_ridge()
    for index, section in enumerate(feeder.sections):
        section.fault_indicator = index < indications
    assert locate_fault(feeder) == expected


@pytest.fixture
def branched_feeder() -> Feeder:
    feeder = cedar_ridge()
    feeder.sections.insert(2, Section(
        mrid="SEC-LATERAL",
        name="Healthy lateral",
        from_node="N-1201-1A",
        to_node="LATERAL-END",
        customers=50,
        load_kw=100.0,
    ))
    return feeder


def test_lateral_after_last_main_line_indication_is_not_the_fault(branched_feeder: Feeder):
    assert locate_fault(branched_feeder) == "SEC-1201-03"


def test_branched_plan_opens_the_fault_boundaries(branched_feeder: Feeder):
    switch_by_mrid(branched_feeder, "CB-1201").open = True
    plan = build_plan(branched_feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
    assert plan.faulted_section == "SEC-1201-03"
    assert {step.switch_mrid for step in plan.isolation} == {
        "SEC-SW-1201-1", "REC-1201-2",
    }


@pytest.mark.parametrize("indications, message", [
    ({"SEC-1201-02"}, "not contiguous"),
    ({"SEC-1201-01", "SEC-1201-03"}, "not contiguous"),
    ({"SEC-1201-01", "SEC-1201-02", "SEC-LATERAL"}, "multiple branches"),
    ({"SEC-1201-01"}, "branch cannot be determined"),
])
def test_ambiguous_indications_refuse_a_switching_plan(
    branched_feeder: Feeder, indications: set[str], message: str,
):
    for section in branched_feeder.sections:
        section.fault_indicator = section.mrid in indications
    switch_by_mrid(branched_feeder, "CB-1201").open = True
    before = branched_feeder.model_dump()
    with pytest.raises(FlisrError, match=message):
        locate_fault(branched_feeder)
    with pytest.raises(FlisrError, match=message):
        build_plan(branched_feeder, "CB-1201")
    assert branched_feeder.model_dump() == before


def test_disconnected_indication_refuses_to_locate(branched_feeder: Feeder):
    branched_feeder.sections[2].from_node = "DISCONNECTED"
    branched_feeder.sections[2].fault_indicator = True
    with pytest.raises(FlisrError, match="not reachable"):
        locate_fault(branched_feeder)


def test_looped_topology_refuses_to_locate(branched_feeder: Feeder):
    branched_feeder.sections[2].to_node = "N-1201-4"
    with pytest.raises(FlisrError, match="radial topology"):
        locate_fault(branched_feeder)


def test_node_orientation_and_list_permutations_do_not_change_location(branched_feeder: Feeder):
    branched_feeder.sections.reverse()
    branched_feeder.switches.reverse()
    for element in [*branched_feeder.sections, *branched_feeder.switches]:
        element.from_node, element.to_node = element.to_node, element.from_node
    assert locate_fault(branched_feeder) == "SEC-1201-03"


def test_seeded_radial_and_branched_plans_never_reenergise_the_fault():
    rng = random.Random(1201)
    for case in range(500):
        length = rng.randint(4, 12)
        indicated_count = rng.randint(2, length - 2)
        sections = [Section(
            mrid=f"SEC-{i}", name=f"Section {i}",
            from_node=f"IN-{i}", to_node=f"OUT-{i}",
            fault_indicator=i < indicated_count,
            customers=rng.randint(1, 500), load_kw=rng.uniform(10.0, 2000.0),
        ) for i in range(length)]
        switches = [Switch(
            mrid="CB", name="Source breaker", kind=SwitchKind.BREAKER,
            from_node="SRC", to_node="IN-0", open=True,
        )] + [Switch(
            mrid=f"SW-{i}", name=f"Recloser {i}", kind=SwitchKind.RECLOSER,
            from_node=f"OUT-{i}", to_node=f"IN-{i + 1}",
        ) for i in range(length - 1)] + [Switch(
            mrid="TIE", name="Alternate supply", kind=SwitchKind.TIE,
            from_node=f"OUT-{length - 1}", to_node="ALT", normal_open=True, open=True,
        )]
        if case % 2:
            for branch in range(rng.randint(1, 4)):
                tap = rng.randrange(indicated_count - 1)
                sections.append(Section(
                    mrid=f"LATERAL-{branch}", name=f"Lateral {branch}",
                    from_node=f"OUT-{tap}", to_node=f"LEAF-{branch}",
                    customers=rng.randint(1, 100), load_kw=rng.uniform(10.0, 500.0),
                ))
        rng.shuffle(sections)
        rng.shuffle(switches)
        feeder = Feeder(
            mrid=f"FDR-{case}", name="Generated feeder", substation="Test",
            nominal_kv=12.47, rating_amps=600.0, source_node="SRC",
            sections=sections, switches=switches,
        )
        before = feeder.model_dump()
        faulted = next(s for s in sections if s.mrid == f"SEC-{indicated_count}")
        assert locate_fault(feeder) == faulted.mrid
        plan = build_plan(feeder, "CB", {"TIE": 1_000_000.0})
        assert plan.faulted_section == faulted.mrid
        assert {step.switch_mrid for step in plan.isolation} == {
            f"SW-{indicated_count - 1}", f"SW-{indicated_count}",
        }
        assert feeder.model_dump() == before
        replay = feeder.model_copy(deep=True)
        for step in [*plan.isolation, *plan.restoration]:
            switch_by_mrid(replay, step.switch_mrid).open = step.action == "open"
            live = energised_nodes(replay) | energised_nodes(replay, "ALT")
            assert faulted.from_node not in live
            assert faulted.to_node not in live

        for section in feeder.sections:
            if section.mrid == "SEC-0":
                section.fault_indicator = False
        with pytest.raises(FlisrError, match="not contiguous"):
            build_plan(feeder, "CB")
