"""Fault location on feeders with laterals tapped off the main line.

Branched feeder used throughout (switches between every pair of sections):

    SRC -CB- BUS -SEC-M1- -SEC-M2- -SEC-M3- -SEC-M4- ... TIE (normally open)
                              \\
                               -SEC-L1- -SEC-L2-      (lateral tapped at the end of M2)
"""

from __future__ import annotations

import random

import pytest

from app.flisr import FlisrError, build_plan, locate_fault
from app.models import Feeder, Section, Switch, SwitchKind
from app.network import energised_nodes

MAIN_AND_LATERAL = {
    "SEC-M1": None,
    "SEC-M2": "SEC-M1",
    "SEC-M3": "SEC-M2",
    "SEC-M4": "SEC-M3",
    "SEC-L1": "SEC-M2",
    "SEC-L2": "SEC-L1",
}


def build_feeder(
    upstream: dict[str, str | None],
    order: list[str],
    indicated: set[str],
    ties: tuple[str, ...] = (),
) -> Feeder:
    """Radial feeder: every section is fed through its own SCADA switch from the
    end of its upstream section (or from the bus); `order` is the list order."""
    sections = [
        Section(
            mrid=mrid,
            name=mrid,
            from_node=f"{mrid}-IN",
            to_node=f"{mrid}-OUT",
            customers=100,
            load_kw=400.0,
            fault_indicator=mrid in indicated,
        )
        for mrid in order
    ]
    switches = [
        Switch(mrid="CB-1", name="CB-1", kind=SwitchKind.BREAKER, from_node="SRC", to_node="BUS")
    ]
    for mrid in order:
        parent = upstream[mrid]
        switches.append(
            Switch(
                mrid=f"SW-{mrid}",
                name=f"SW-{mrid}",
                kind=SwitchKind.RECLOSER,
                from_node=f"{parent}-OUT" if parent else "BUS",
                to_node=f"{mrid}-IN",
            )
        )
    for index, mrid in enumerate(ties):
        switches.append(
            Switch(
                mrid=f"TIE-{index}",
                name=f"TIE-{index}",
                kind=SwitchKind.TIE,
                normal_open=True,
                open=True,
                from_node=f"{mrid}-OUT",
                to_node=f"ALT-{index}",
            )
        )
    return Feeder(
        mrid="FDR-TEST",
        name="Branched test feeder",
        substation="SUB-TEST",
        nominal_kv=12.47,
        source_node="SRC",
        rating_amps=600.0,
        sections=sections,
        switches=switches,
    )


def in_lockout(feeder: Feeder) -> Feeder:
    next(s for s in feeder.switches if s.mrid == "CB-1").open = True
    return feeder


def opened(plan) -> set[str]:
    return {step.switch_mrid for step in plan.isolation if step.action == "open"}


def test_fault_on_main_line_past_the_lateral_tap():
    # Fault current passed M1, M2, M3; the lateral sits later in the list than M3.
    feeder = in_lockout(
        build_feeder(
            MAIN_AND_LATERAL,
            ["SEC-M1", "SEC-M2", "SEC-M3", "SEC-L1", "SEC-L2", "SEC-M4"],
            {"SEC-M1", "SEC-M2", "SEC-M3"},
        )
    )

    plan = build_plan(feeder, "CB-1")

    assert "SW-SEC-M4" in opened(plan), "plan closes CB-1 onto faulted SEC-M4"
    assert locate_fault(feeder) == "SEC-M4"
    assert plan.restoration[0].switch_mrid == "CB-1"


def test_fault_on_the_lateral():
    # Fault current passed M1, M2, L1; main-line M3/M4 sit between L1 and L2 in the list.
    feeder = in_lockout(
        build_feeder(
            MAIN_AND_LATERAL,
            ["SEC-M1", "SEC-M2", "SEC-L1", "SEC-M3", "SEC-M4", "SEC-L2"],
            {"SEC-M1", "SEC-M2", "SEC-L1"},
        )
    )

    plan = build_plan(feeder, "CB-1")

    assert "SW-SEC-L2" in opened(plan), "plan closes CB-1 onto faulted SEC-L2"
    assert locate_fault(feeder) == "SEC-L2"


def test_list_order_does_not_change_the_located_section():
    indicated = {"SEC-M1", "SEC-M2", "SEC-M3"}
    forward = build_feeder(MAIN_AND_LATERAL, list(MAIN_AND_LATERAL), indicated)
    reverse = build_feeder(MAIN_AND_LATERAL, list(reversed(MAIN_AND_LATERAL)), indicated)

    assert locate_fault(forward) == locate_fault(reverse) == "SEC-M4"


def test_indication_at_the_end_of_a_branch_locates_that_section():
    feeder = build_feeder(
        MAIN_AND_LATERAL, list(MAIN_AND_LATERAL), {"SEC-M1", "SEC-M2", "SEC-L1", "SEC-L2"}
    )

    assert locate_fault(feeder) == "SEC-L2"


def test_refuses_when_the_fault_could_be_on_the_main_line_or_the_lateral():
    # Last indication is M2, which feeds both M3 and L1: either could be faulted.
    feeder = in_lockout(
        build_feeder(MAIN_AND_LATERAL, list(MAIN_AND_LATERAL), {"SEC-M1", "SEC-M2"})
    )

    with pytest.raises(FlisrError, match="could be on any of SEC-M3, SEC-L1"):
        locate_fault(feeder)
    with pytest.raises(FlisrError):
        build_plan(feeder, "CB-1")


def test_refuses_indications_on_two_branches():
    feeder = build_feeder(
        MAIN_AND_LATERAL, list(MAIN_AND_LATERAL), {"SEC-M1", "SEC-M2", "SEC-M3", "SEC-L1"}
    )

    with pytest.raises(FlisrError, match="more than one branch"):
        locate_fault(feeder)


def test_refuses_a_looped_feeder_without_hanging():
    feeder = build_feeder(MAIN_AND_LATERAL, list(MAIN_AND_LATERAL), {"SEC-M1"})
    feeder.switches.append(
        Switch(
            mrid="SW-LOOP",
            name="SW-LOOP",
            kind=SwitchKind.SECTIONALIZER,
            from_node="SEC-L2-OUT",
            to_node="SEC-M4-OUT",
        )
    )

    with pytest.raises(FlisrError, match="not radial"):
        locate_fault(feeder)


def test_refuses_an_indication_not_fed_from_the_source():
    feeder = build_feeder(MAIN_AND_LATERAL, list(MAIN_AND_LATERAL), {"SEC-M1"})
    feeder.sections.append(
        Section(
            mrid="SEC-ISLAND",
            name="island",
            from_node="X-IN",
            to_node="X-OUT",
            fault_indicator=True,
        )
    )

    with pytest.raises(FlisrError, match="SEC-ISLAND not fed from SRC"):
        locate_fault(feeder)


def test_normally_open_tie_is_not_treated_as_a_downstream_branch():
    feeder = build_feeder(
        MAIN_AND_LATERAL, list(MAIN_AND_LATERAL), {"SEC-M1", "SEC-M2", "SEC-M3"}, ties=("SEC-M4",)
    )

    assert locate_fault(feeder) == "SEC-M4"


def _random_radial_feeder(rng: random.Random):
    count = rng.randint(1, 12)
    names = [f"SEC-{index:02d}" for index in range(count)]
    linear = rng.random() < 0.3
    upstream: dict[str, str | None] = {}
    for index, mrid in enumerate(names):
        if index == 0:
            upstream[mrid] = None
        elif linear:
            upstream[mrid] = names[index - 1]
        elif rng.random() < 0.1:
            upstream[mrid] = rng.choice([None] + names[:index])
        else:
            upstream[mrid] = rng.choice(names[:index])
    leaves = [m for m in names if m not in upstream.values()]
    ties = tuple(rng.sample(leaves, rng.randint(0, min(2, len(leaves)))))

    faulted = rng.choice(names)
    ancestors = []
    parent = upstream[faulted]
    while parent is not None:
        ancestors.append(parent)
        parent = upstream[parent]
    # Fault current passes every section upstream of the fault; non-adjacent
    # indicators may have failed to operate.
    indicated = {m for i, m in enumerate(ancestors) if i == 0 or rng.random() < 0.8}

    order = names[:]
    rng.shuffle(order)
    return upstream, build_feeder(upstream, order, indicated, ties), faulted


def test_invariant_reclosing_the_breaker_never_energises_the_faulted_section():
    """Over random radial and branched feeders in random list order, the engine
    either locates the true faulted section, or refuses; and closing the lockout
    breaker after isolation never re-energises the fault."""
    rng = random.Random(1201)
    located = refused = 0
    for _ in range(1000):
        upstream, feeder, faulted = _random_radial_feeder(rng)
        in_lockout(feeder)
        siblings = [m for m, p in upstream.items() if p == upstream[faulted]]

        if upstream[faulted] is None:
            assert locate_fault(feeder) is None
            continue
        if len(siblings) > 1:
            with pytest.raises(FlisrError):
                build_plan(feeder, "CB-1")
            refused += 1
            continue

        plan = build_plan(feeder, "CB-1", {s.mrid: 1e9 for s in feeder.switches})
        assert plan.faulted_section == faulted
        assert plan.restoration[0].switch_mrid == "CB-1"
        for switch in feeder.switches:
            if switch.mrid in opened(plan):
                switch.open = True
            if switch.mrid == "CB-1":
                switch.open = False
        section = next(s for s in feeder.sections if s.mrid == faulted)
        live = energised_nodes(feeder)
        assert section.from_node not in live and section.to_node not in live, (
            f"closing CB-1 re-energises faulted {faulted}"
        )
        located += 1
    assert located > 300 and refused > 50
