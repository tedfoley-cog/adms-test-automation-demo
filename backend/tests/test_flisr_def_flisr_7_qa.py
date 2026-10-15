"""Independent QA of the DEF-FLISR-7 fix (run rca-backfeed, stage qa).

Written from the brief and the repo contract, not from Coding's tests. The
reference model below re-derives the whole restoration plan for a feeder in
lockout (isolation set, which ties close, customer and load accounting) with
its own breadth-first reachability, and the live-node check energises every
tie's alternate-source node whether or not the tie is closed. Agreement is
exact: 0 customers, 1e-6 kW.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

import pytest

from app.flisr import FlisrError, build_plan
from app.models import Feeder, Section, Switch, SwitchKind
from app.network import get_feeder, load_network, switch_by_mrid

pytestmark = pytest.mark.requirement("DEF-FLISR-7")

QA_SEED = 4242
QA_CASES = 600
KW_TOL = 1e-6


# --------------------------------------------------------------------------- oracle
def reach(feeder: Feeder, start: str, closed_override: dict[str, bool] | None = None) -> set[str]:
    """Nodes connected to `start` through sections and closed switches."""
    closed_override = closed_override or {}
    graph: dict[str, set[str]] = defaultdict(set)
    for section in feeder.sections:
        graph[section.from_node].add(section.to_node)
        graph[section.to_node].add(section.from_node)
    for switch in feeder.switches:
        is_open = closed_override.get(switch.mrid, switch.open)
        if not is_open:
            graph[switch.from_node].add(switch.to_node)
            graph[switch.to_node].add(switch.from_node)
    seen: set[str] = set()
    frontier = [start]
    while frontier:
        node = frontier.pop()
        if node in seen:
            continue
        seen.add(node)
        frontier.extend(graph[node] - seen)
    return seen


def oracle_faulted_section(feeder: Feeder) -> Section | None:
    indicated = [i for i, s in enumerate(feeder.sections) if s.fault_indicator]
    if not indicated:
        return None
    last = max(indicated)
    return feeder.sections[min(last + 1, len(feeder.sections) - 1)]


def oracle_plan(feeder: Feeder, lockout_mrid: str, capacity: dict[str, float] | None) -> dict:
    """Reference restoration contract for a feeder whose `lockout_mrid` is open.

    Refuse before capacity: a tie whose pick-up set touches either endpoint of
    the faulted section is never closed (DEF-FLISR-7, STD-SAFETY-4). The
    faulted section's customers count once in remaining and never in restored
    or transferred (Q-REVIEW-2). Healthy sections in a refused or skipped
    pick-up set are added to remaining per tie, which is the accounting the
    shipped capacity-skip branch already uses.
    """
    capacity = capacity or {}
    lockout = switch_by_mrid(feeder, lockout_mrid)
    faulted = oracle_faulted_section(feeder)
    assert faulted is not None
    isolation = []
    for sw in feeder.switches:
        if not sw.scada_controllable or sw.kind == SwitchKind.TIE:
            continue
        if sw.to_node == faulted.from_node or sw.from_node == faulted.to_node:
            isolation.append(sw.mrid)
    override = {m: True for m in isolation}
    faulted_nodes = {faulted.from_node, faulted.to_node}
    out = {
        "faulted": faulted.mrid,
        "isolation": set(isolation),
        "closed": [],
        "refused": [],
        "skipped": [],
        "restored": 0,
        "remaining": faulted.customers,
        "transferred": 0.0,
    }
    for tie in feeder.switches:
        if tie.kind != SwitchKind.TIE or not tie.scada_controllable:
            continue
        with_tie = {**override, tie.mrid: False}
        from_alt = reach(feeder, tie.to_node, with_tie)
        from_src = reach(feeder, feeder.source_node, with_tie)
        pick_up = from_alt - from_src
        if not pick_up:
            continue
        in_pick_up = [s for s in feeder.sections if s.to_node in pick_up]
        if pick_up & faulted_nodes:
            out["refused"].append(tie.mrid)
            out["remaining"] += sum(s.customers for s in in_pick_up if s.mrid != faulted.mrid)
            continue
        load = sum(s.load_kw for s in in_pick_up)
        if load > capacity.get(tie.mrid, 0.0):
            out["skipped"].append(tie.mrid)
            out["remaining"] += sum(s.customers for s in in_pick_up)
            continue
        out["closed"].append(tie.mrid)
        out["restored"] += sum(s.customers for s in in_pick_up)
        out["transferred"] += load
    out["restoration"] = ([lockout.mrid] if lockout.scada_controllable else []) + out["closed"]
    return out


def switched(feeder: Feeder, plan) -> Feeder:
    after = feeder.model_copy(deep=True)
    by_mrid = {s.mrid: s for s in after.switches}
    for step in plan.isolation + plan.restoration:
        assert step.action in {"open", "close"}, step
        by_mrid[step.switch_mrid].open = step.action == "open"
    return after


def live_after(feeder: Feeder, plan) -> set[str]:
    """Nodes energised after the plan: feeder source plus every alternate source."""
    after = switched(feeder, plan)
    live = reach(after, after.source_node)
    for tie in after.switches:
        if tie.kind == SwitchKind.TIE:
            live |= reach(after, tie.to_node)
    return live


def assert_plan_matches_oracle(feeder: Feeder, lockout: str, capacity, plan) -> dict:
    before = feeder.model_dump()
    expect = oracle_plan(feeder, lockout, capacity)
    assert feeder.model_dump() == before, "build_plan mutated its input feeder"
    assert plan.faulted_section == expect["faulted"]
    assert {s.switch_mrid for s in plan.isolation} == expect["isolation"]
    assert all(s.action == "open" for s in plan.isolation)
    assert [s.switch_mrid for s in plan.restoration] == expect["restoration"]
    assert all(s.action == "close" for s in plan.restoration)
    assert plan.customers_restored == expect["restored"]
    assert plan.customers_remaining == expect["remaining"]
    assert math.isclose(plan.transferred_load_kw, expect["transferred"], abs_tol=KW_TOL)
    for tie in expect["refused"]:
        assert any(tie in n and expect["faulted"] in n for n in plan.notes), (tie, plan.notes)
    faulted = next(s for s in feeder.sections if s.mrid == plan.faulted_section)
    assert not ({faulted.from_node, faulted.to_node} & live_after(feeder, plan)), (
        f"faulted {faulted.mrid} energised by "
        f"{[(s.switch_mrid, s.action) for s in plan.restoration]}"
    )
    return expect


# --------------------------------------------------------------------------- fixtures
def fdr_1201(faulted: str, extra_ties: list[tuple[str, str]] = ()) -> Feeder:
    """FDR-1201 in lockout on CB-1201 with the fault located on `faulted`.

    `extra_ties` adds SCADA ties (mrid, feeder node) to alternate node ALT-<mrid>.
    """
    feeder = get_feeder(load_network(), "FDR-1201")
    order = [s.mrid for s in feeder.sections]
    for section in feeder.sections:
        section.fault_indicator = order.index(section.mrid) < order.index(faulted)
    switch_by_mrid(feeder, "CB-1201").open = True
    for mrid, node in extra_ties:
        feeder.switches.append(
            Switch(mrid=mrid, name=mrid, kind=SwitchKind.TIE, normal_open=True, open=True,
                   from_node=node, to_node=f"ALT-{mrid}")
        )
    return feeder


DEF7_EXPECTED = {
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
    "notes": [
        "Hollow Creek tie to 1405 (TIE-1201-1405) held open: would back-feed faulted section "
        "Hollow Creek tail (SEC-1201-04)"
    ],
}


# --------------------------------------------------------------------------- nominal
def test_qa_def_flisr_7_nominal_drill_14_stand_in():
    feeder = fdr_1201("SEC-1201-04")
    plan = build_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
    assert plan.model_dump() == DEF7_EXPECTED
    assert_plan_matches_oracle(feeder, "CB-1201", {"TIE-1201-1405": 2000.0}, plan)


# --------------------------------------------------------------------------- boundary
@pytest.mark.parametrize("capacity_kw", [0.0, 1489.0, 1490.0, 1491.0, 1.0e12])
def test_qa_def_flisr_7_refusal_is_independent_of_tie_capacity(capacity_kw):
    """Before the fix 1490 kW was the close threshold; the guard must ignore capacity."""
    feeder = fdr_1201("SEC-1201-04")
    plan = build_plan(feeder, "CB-1201", {"TIE-1201-1405": capacity_kw})
    assert plan.model_dump() == DEF7_EXPECTED
    assert_plan_matches_oracle(feeder, "CB-1201", {"TIE-1201-1405": capacity_kw}, plan)


@pytest.mark.parametrize(
    ("capacity_kw", "closes"), [(1489.0, False), (1490.0, True), (1491.0, True)]
)
def test_qa_def_flisr_7_healthy_tail_capacity_boundary_unchanged(capacity_kw, closes):
    """Shipped fault SEC-1201-03: the capacity gate (`>`) must behave exactly as before."""
    feeder = fdr_1201("SEC-1201-03")
    plan = build_plan(feeder, "CB-1201", {"TIE-1201-1405": capacity_kw})
    closed = [s.switch_mrid for s in plan.restoration]
    assert ("TIE-1201-1405" in closed) is closes
    assert plan.customers_restored == (341 if closes else 0)
    assert plan.customers_remaining == (96 if closes else 437)
    assert not any("held open" in n for n in plan.notes)
    assert_plan_matches_oracle(feeder, "CB-1201", {"TIE-1201-1405": capacity_kw}, plan)


# --------------------------------------------------------------------------- missing input
@pytest.mark.parametrize("capacity", [None, {}, {"TIE-9999": 5000.0}])
def test_qa_def_flisr_7_missing_capacity_still_refuses_with_named_note(capacity):
    feeder = fdr_1201("SEC-1201-04")
    plan = build_plan(feeder, "CB-1201", capacity)
    assert plan.model_dump() == DEF7_EXPECTED
    assert_plan_matches_oracle(feeder, "CB-1201", capacity, plan)


def test_qa_def_flisr_7_missing_capacity_on_healthy_tail_is_a_skip_not_a_close():
    """Missing capacity must not become an implicit close (pre-existing branch, re-checked)."""
    feeder = fdr_1201("SEC-1201-03")
    plan = build_plan(feeder, "CB-1201", None)
    assert [s.switch_mrid for s in plan.restoration] == ["CB-1201"]
    assert plan.notes == [
        "Hollow Creek tie to 1405 skipped: 1490 kW exceeds 0 kW available capacity"
    ]
    assert (plan.customers_restored, plan.customers_remaining) == (0, 437)


# --------------------------------------------------------------------------- invalid input
@pytest.mark.parametrize("capacity_kw", [math.nan, math.inf, -1.0])
def test_qa_def_flisr_7_invalid_capacity_cannot_bypass_the_guard(capacity_kw):
    feeder = fdr_1201("SEC-1201-04")
    plan = build_plan(feeder, "CB-1201", {"TIE-1201-1405": capacity_kw})
    assert plan.model_dump() == DEF7_EXPECTED


def test_qa_def_flisr_7_error_paths_retained():
    feeder = get_feeder(load_network(), "FDR-1201")
    with pytest.raises(FlisrError, match="not in lockout"):
        build_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
    with pytest.raises(KeyError, match="unknown switch"):
        build_plan(feeder, "CB-0000", {})
    manual = fdr_1201("SEC-1201-04")
    for sw in manual.switches:
        if sw.kind != SwitchKind.TIE:
            sw.scada_controllable = sw.mrid == "CB-1201"
    with pytest.raises(FlisrError, match="no SCADA switch can isolate Hollow Creek tail"):
        build_plan(manual, "CB-1201", {"TIE-1201-1405": 2000.0})


def test_qa_def_flisr_7_non_scada_tie_is_never_a_candidate():
    feeder = fdr_1201("SEC-1201-03")
    switch_by_mrid(feeder, "TIE-1201-1405").scada_controllable = False
    plan = build_plan(feeder, "CB-1201", {"TIE-1201-1405": 5000.0})
    assert [s.switch_mrid for s in plan.restoration] == ["CB-1201"]
    assert plan.notes == []
    assert (plan.customers_restored, plan.customers_remaining) == (0, 96)


# --------------------------------------------------------------------------- review probe cases
@pytest.mark.parametrize(
    ("faulted", "tie_node", "tie_x_closes"),
    [
        ("SEC-1201-04", "N-1201-3A", False),  # A1 tie on upstream end of the faulted section
        ("SEC-1201-03", "N-1201-3", False),   # A2 tie on downstream end, REC-1201-2 also bounds it
        ("SEC-1201-03", "N-1201-2A", False),  # A3 tie on upstream end, both ends non-tie bounded
        ("SEC-1201-03", "N-1201-1", True),    # A4 control: tie on a healthy node
    ],
)
def test_qa_def_flisr_7_tie_on_any_faulted_endpoint_is_refused(faulted, tie_node, tie_x_closes):
    feeder = fdr_1201(faulted, extra_ties=[("TIE-X", tie_node)])
    capacity = {"TIE-1201-1405": 5000.0, "TIE-X": 5000.0}
    plan = build_plan(feeder, "CB-1201", capacity)
    closed = [s.switch_mrid for s in plan.restoration]
    assert ("TIE-X" in closed) is tie_x_closes
    assert any("TIE-X" in n and faulted in n for n in plan.notes) is not tie_x_closes
    assert_plan_matches_oracle(feeder, "CB-1201", capacity, plan)


def test_qa_def_flisr_7_pick_up_through_non_scada_downstream_switch_is_refused():
    """Fault SEC-1201-03 with REC-1201-2 manual: TIE-1201-1405's pick-up reaches the fault
    through the closed recloser, so the tie is refused and SEC-1201-04 stays dark."""
    feeder = fdr_1201("SEC-1201-03")
    switch_by_mrid(feeder, "REC-1201-2").scada_controllable = False
    plan = build_plan(feeder, "CB-1201", {"TIE-1201-1405": 5000.0})
    assert [s.switch_mrid for s in plan.isolation] == ["SEC-SW-1201-1"]
    assert [s.switch_mrid for s in plan.restoration] == ["CB-1201"]
    assert (plan.customers_restored, plan.customers_remaining) == (0, 96 + 341)
    assert_plan_matches_oracle(feeder, "CB-1201", {"TIE-1201-1405": 5000.0}, plan)


# --------------------------------------------------------------------------- api
def test_qa_def_flisr_7_api_plan_matches_direct_plan(monkeypatch):
    from fastapi.testclient import TestClient

    from app import api

    network = load_network()
    feeder = get_feeder(network, "FDR-1201")
    for section in feeder.sections:
        section.fault_indicator = section.mrid != "SEC-1201-04"
    switch_by_mrid(feeder, "CB-1201").open = True
    monkeypatch.setattr(api, "load_network", lambda: network)
    client = TestClient(api.app)

    ok = client.post("/flisr/plan", json={"feeder_mrid": "FDR-1201",
                                          "lockout_switch_mrid": "CB-1201",
                                          "tie_capacity_kw": {"TIE-1201-1405": 2000.0}})
    assert ok.status_code == 200
    assert ok.json() == DEF7_EXPECTED

    assert client.post("/flisr/plan", json={"feeder_mrid": "FDR-0000",
                                            "lockout_switch_mrid": "CB-1201"}).status_code == 404
    assert client.post("/flisr/plan", json={"feeder_mrid": "FDR-1405",
                                            "lockout_switch_mrid": "CB-1405"}).status_code == 409


# --------------------------------------------------------------------------- seeded invariant
def qa_feeder(rng: random.Random) -> tuple[Feeder, dict[str, float]]:
    """Radial or branched feeder, 2-9 sections, 1-4 ties on arbitrary nodes (including BUS
    and the faulted section's endpoints), a mix of SCADA and manual ties, random capacity
    including 0 and values far above total load. Downstream switches may be manual so a
    tie's pick-up set can reach the fault through healthy sections; the faulted section's
    upstream switch is always SCADA because a manual upstream switch triggers the separate
    lockout-reclose defect that is outside DEF-FLISR-7."""
    n = rng.randint(2, 9)
    branched = rng.random() < 0.5
    faulted = rng.randrange(1, n)
    sections: list[Section] = []
    switches = [Switch(mrid="CB", name="CB", kind=SwitchKind.BREAKER, open=True,
                       from_node="SRC", to_node="BUS")]
    for i in range(n):
        start = "BUS" if i == 0 else f"N{i}A"
        if i > 0:
            parent = rng.randrange(i) if branched else i - 1
            switches.append(Switch(
                mrid=f"SW{i}", name=f"SW{i}",
                kind=rng.choice([SwitchKind.RECLOSER, SwitchKind.SECTIONALIZER]),
                scada_controllable=True if i == faulted else rng.random() < 0.8,
                from_node=f"N{parent}", to_node=start))
        sections.append(Section(mrid=f"S{i}", name=f"S{i}", from_node=start, to_node=f"N{i}",
                                customers=rng.randint(0, 600),
                                load_kw=float(rng.randint(0, 2500))))
    for section in sections[:faulted]:
        section.fault_indicator = True
    nodes = sorted({s.from_node for s in sections} | {s.to_node for s in sections})
    tie_nodes = rng.sample(nodes, rng.randint(1, min(4, len(nodes))))
    if rng.random() < 0.6:
        tie_nodes[0] = rng.choice([sections[faulted].from_node, sections[faulted].to_node])
    capacity: dict[str, float] = {}
    for t, node in enumerate(tie_nodes):
        switches.append(Switch(mrid=f"TIE{t}", name=f"TIE{t}", kind=SwitchKind.TIE,
                               normal_open=True, open=True, scada_controllable=rng.random() < 0.85,
                               from_node=node, to_node=f"ALT{t}"))
        if rng.random() < 0.9:
            capacity[f"TIE{t}"] = float(rng.choice([0, rng.randint(1, 4000), 1e9]))
    feeder = Feeder(mrid="F", name="F", substation="SUB", nominal_kv=12.47, rating_amps=600.0,
                    source_node="SRC", sections=sections, switches=switches)
    return feeder, capacity


def test_qa_def_flisr_7_seeded_plans_agree_with_oracle_and_never_back_feed():
    rng = random.Random(QA_SEED)
    exposed = refused_total = closed_total = 0
    failures = []
    for case in range(QA_CASES):
        feeder, capacity = qa_feeder(rng)
        plan = build_plan(feeder, "CB", capacity)
        try:
            expect = assert_plan_matches_oracle(feeder, "CB", capacity, plan)
        except AssertionError as exc:  # noqa: PERF203 - collect every failing vector
            failures.append((case, str(exc).splitlines()[0]))
            continue
        exposed += bool(expect["refused"])
        refused_total += len(expect["refused"])
        closed_total += len(expect["closed"])
    assert exposed >= 100, f"only {exposed} cases exercised the refusal"
    assert closed_total >= 100, f"only {closed_total} ties closed; guard may be over-refusing"
    assert not failures, f"{len(failures)}/{QA_CASES} vectors disagree: {failures[:5]}"
