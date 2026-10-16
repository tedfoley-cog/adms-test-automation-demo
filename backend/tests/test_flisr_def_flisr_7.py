"""DEF-FLISR-7: restoration must never back-feed the faulted section.

FDR-1201 with the fault on SEC-1201-04, lockout CB-1201 and tie TIE-1201-1405
stands in for drill 14 (Q-EXPLORE-1); build_plan is the function under test
(Q-EXPLORE-2).
"""

from __future__ import annotations

import random
from collections import defaultdict

import pytest

from app.flisr import build_plan
from app.models import Feeder, Section, Switch, SwitchKind
from app.network import get_feeder, load_network, switch_by_mrid

pytestmark = pytest.mark.requirement("DEF-FLISR-7")

INVARIANT_SEED = 20261015
INVARIANT_CASES = 500
HELD_OPEN_NOTE = (
    "Hollow Creek tie to 1405 (TIE-1201-1405) held open: would back-feed faulted section "
    "Hollow Creek tail (SEC-1201-04)"
)


def cedar_ridge_faulted_on_sec_1201_04():
    network = load_network()
    feeder = get_feeder(network, "FDR-1201")
    for section in feeder.sections:
        section.fault_indicator = section.mrid != "SEC-1201-04"
    switch_by_mrid(feeder, "CB-1201").open = True
    return network, feeder


def reachable(feeder: Feeder, start: str) -> set[str]:
    """Independent oracle: nodes connected to `start` through sections and closed switches."""
    graph: dict[str, set[str]] = defaultdict(set)
    for section in feeder.sections:
        graph[section.from_node].add(section.to_node)
        graph[section.to_node].add(section.from_node)
    for switch in feeder.switches:
        if not switch.open:
            graph[switch.from_node].add(switch.to_node)
            graph[switch.to_node].add(switch.from_node)
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(graph[node] - seen)
    return seen


def apply_plan(feeder: Feeder, plan) -> Feeder:
    after = feeder.model_copy(deep=True)
    by_mrid = {switch.mrid: switch for switch in after.switches}
    for step in plan.isolation + plan.restoration:
        by_mrid[step.switch_mrid].open = step.action == "open"
    return after


def live_nodes(feeder: Feeder) -> set[str]:
    """Nodes fed by the feeder source or by any tie's alternate source."""
    live = reachable(feeder, feeder.source_node)
    for switch in feeder.switches:
        if switch.kind == SwitchKind.TIE:
            live |= reachable(feeder, switch.to_node)
    return live


def test_def_flisr_7_tie_does_not_back_feed_faulted_tail_section():
    _, feeder = cedar_ridge_faulted_on_sec_1201_04()

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert plan.faulted_section == "SEC-1201-04"
    faulted = next(s for s in feeder.sections if s.mrid == plan.faulted_section)
    live = live_nodes(apply_plan(feeder, plan))
    assert not ({faulted.from_node, faulted.to_node} & live), (
        f"plan re-energises {faulted.mrid}: "
        f"restoration={[(s.switch_mrid, s.action) for s in plan.restoration]}"
    )


def test_def_flisr_7_plan_holds_tie_open_and_counts_faulted_customers_once():
    _, feeder = cedar_ridge_faulted_on_sec_1201_04()

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    # REQ-TIECAP-11/14/16 (U2, U3): blocked_ties is asserted in the test below; as_of and
    # deprecations are new response fields; every other field as pinned.
    assert plan.model_dump(exclude={"as_of", "blocked_ties", "deprecations"}) == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": "SEC-1201-04",
        "isolation": [
            {"switch_mrid": "REC-1201-2", "action": "open",
             "reason": "upstream isolation of Hollow Creek tail"},
        ],
        "restoration": [
            {"switch_mrid": "CB-1201", "action": "close",
             "reason": "re-energise healthy sections upstream of the fault"},
        ],
        "customers_restored": 0,
        "customers_remaining": 341,
        "transferred_load_kw": 0.0,
        "notes": [HELD_OPEN_NOTE],
    }


@pytest.mark.requirement("REQ-TIECAP-11")
def test_req_tiecap_11_held_tie_reported_as_faulted_section():
    _, feeder = cedar_ridge_faulted_on_sec_1201_04()

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert plan.model_dump(mode="json")["blocked_ties"] == [
        {"tie_id": "TIE-1201-1405", "reason": "FAULTED_SECTION"}
    ]

def test_def_flisr_7_short_tie_capacity_still_counts_faulted_customers_once():
    _, feeder = cedar_ridge_faulted_on_sec_1201_04()

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 1000.0})

    assert plan.model_dump(mode="json")["blocked_ties"] == [
        {"tie_id": "TIE-1201-1405", "reason": "FAULTED_SECTION"}
    ]
    assert [(s.switch_mrid, s.action) for s in plan.restoration] == [("CB-1201", "close")]
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 341
    assert plan.transferred_load_kw == 0.0
    assert plan.notes == [HELD_OPEN_NOTE]


def test_def_flisr_7_tie_refused_when_pick_up_reaches_unisolated_faulted_section():
    feeder = get_feeder(load_network(), "FDR-1201")
    switch_by_mrid(feeder, "REC-1201-2").scada_controllable = False
    switch_by_mrid(feeder, "CB-1201").open = True

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert plan.faulted_section == "SEC-1201-03"
    assert plan.model_dump(mode="json")["blocked_ties"] == [
        {"tie_id": "TIE-1201-1405", "reason": "FAULTED_SECTION"}
    ]
    assert [(s.switch_mrid, s.action) for s in plan.isolation] == [("SEC-SW-1201-1", "open")]
    assert [(s.switch_mrid, s.action) for s in plan.restoration] == [("CB-1201", "close")]
    assert plan.customers_restored == 0
    assert plan.customers_remaining == 96 + 341
    assert plan.transferred_load_kw == 0.0
    assert plan.notes == [
        "Hollow Creek tie to 1405 (TIE-1201-1405) held open: would back-feed faulted section "
        "Quarry Crossing (SEC-1201-03)"
    ]


def test_def_flisr_7_post_flisr_plan_does_not_close_tie_onto_faulted_section(monkeypatch):
    from fastapi.testclient import TestClient

    from app import api

    network, _ = cedar_ridge_faulted_on_sec_1201_04()
    monkeypatch.setattr(api, "load_network", lambda: network)

    response = TestClient(api.app).post(
        "/flisr/plan",
        json={
            "feeder_mrid": "FDR-1201",
            "lockout_switch_mrid": "CB-1201",
            "tie_capacity_kw": {"TIE-1201-1405": 2000.0},
        },
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["faulted_section"] == "SEC-1201-04"
    assert ("TIE-1201-1405", "close") not in [
        (step["switch_mrid"], step["action"]) for step in plan["restoration"]
    ], f"POST /flisr/plan closes TIE-1201-1405 onto SEC-1201-04: {plan}"
    assert (plan["customers_restored"], plan["customers_remaining"]) == (0, 341)
    assert plan["transferred_load_kw"] == 0.0


def random_feeder(rng: random.Random) -> tuple[Feeder, dict[str, float]]:
    """Radial or branched feeder, 2-10 sections, all switches SCADA, 1-3 ties on any node.

    Sections are listed parent-first, so indicating sections[0:k] makes
    locate_fault return sections[k]. With probability 0.5 one tie is placed on
    an endpoint of that section so the DEF-FLISR-7 trigger is exercised often.
    """
    n = rng.randint(2, 10)
    branched = rng.random() < 0.5
    sections: list[Section] = []
    switches = [
        Switch(mrid="CB", name="CB", kind=SwitchKind.BREAKER, open=True,
               from_node="SRC", to_node="BUS")
    ]
    for i in range(n):
        start = "BUS" if i == 0 else f"N{i}A"
        if i > 0:
            parent = rng.randrange(i) if branched else i - 1
            switches.append(
                Switch(mrid=f"SW{i}", name=f"SW{i}",
                       kind=rng.choice([SwitchKind.RECLOSER, SwitchKind.SECTIONALIZER]),
                       from_node=f"N{parent}", to_node=start)
            )
        sections.append(
            Section(mrid=f"S{i}", name=f"S{i}", from_node=start, to_node=f"N{i}",
                    customers=rng.randint(1, 500), load_kw=float(rng.randint(100, 2000)))
        )
    faulted = rng.randrange(1, n)
    for section in sections[:faulted]:
        section.fault_indicator = True

    nodes = sorted({s.from_node for s in sections} | {s.to_node for s in sections} - {"BUS"})
    tie_nodes = rng.sample(nodes, rng.randint(1, min(3, len(nodes))))
    if rng.random() < 0.5:
        tie_nodes[0] = rng.choice([sections[faulted].from_node, sections[faulted].to_node])
    capacity = {}
    for t, node in enumerate(tie_nodes):
        switches.append(
            Switch(mrid=f"TIE{t}", name=f"TIE{t}", kind=SwitchKind.TIE, normal_open=True,
                   open=True, from_node=node, to_node=f"ALT{t}")
        )
        capacity[f"TIE{t}"] = float(rng.randint(0, 6000))
    feeder = Feeder(mrid="F", name="F", substation="SUB", nominal_kv=12.47, rating_amps=600.0,
                    source_node="SRC", sections=sections, switches=switches)
    return feeder, capacity


def test_def_flisr_7_invariant_faulted_section_never_back_fed_over_seeded_feeders():
    """Invariant: after isolation and restoration, neither endpoint of the faulted
    section is reachable from the feeder source or from any tie's alternate source.
    Also: every tie whose pick-up excludes the faulted section and fits the capacity
    is still closed, so the guard refuses nothing else."""
    rng = random.Random(INVARIANT_SEED)
    exposed = 0
    violations = []
    for case in range(INVARIANT_CASES):
        feeder, capacity = random_feeder(rng)
        plan = build_plan(feeder, "CB", tie_capacity_kw=capacity)
        faulted = next(s for s in feeder.sections if s.mrid == plan.faulted_section)
        faulted_nodes = {faulted.from_node, faulted.to_node}

        isolated = apply_plan(feeder, plan.model_copy(update={"restoration": []}))
        expected_closed = set()
        for tie in (s for s in isolated.switches if s.kind == SwitchKind.TIE):
            pick_up = reachable(isolated, tie.from_node) | {tie.to_node}
            load = sum(s.load_kw for s in isolated.sections if s.to_node in pick_up)
            if load > capacity[tie.mrid]:
                continue
            if pick_up & faulted_nodes:
                exposed += 1
            else:
                expected_closed.add(tie.mrid)

        closed_ties = {s.switch_mrid for s in plan.restoration if s.switch_mrid != "CB"}
        back_fed = faulted_nodes & live_nodes(apply_plan(feeder, plan))
        if back_fed or closed_ties != expected_closed:
            violations.append((case, plan.faulted_section, sorted(closed_ties),
                               sorted(expected_closed), sorted(back_fed)))

    assert exposed >= 100, f"generator exercised the trigger in only {exposed} cases"
    assert not violations, f"{len(violations)}/{INVARIANT_CASES} cases: {violations[:5]}"
