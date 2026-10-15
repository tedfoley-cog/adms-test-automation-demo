"""DEF-FLISR-7 review probe (not collected by pytest).

Checks the trigger condition of the confirmed root cause beyond tail ties and
whether a refuse-the-tie guard is sufficient. No production code is changed;
part C patches build_plan's helper in-process only.

Run: PYTHONPATH=backend python backend/tests/rca_def_flisr_7_review_probe.py
"""

from __future__ import annotations

import random

from rca_def_flisr_7_sweep import back_fed, cedar_ridge

from app import flisr
from app.models import Feeder, Section, Switch, SwitchKind


def add_tie(feeder: Feeder, mrid: str, node: str) -> None:
    feeder.switches.append(
        Switch(mrid=mrid, name=mrid, kind=SwitchKind.TIE, normal_open=True, open=True,
               scada_controllable=True, from_node=node, to_node=f"ALT-{mrid}")
    )


def part_a() -> None:
    print("A. Shipped FDR-1201 plus one extra SCADA tie, tie capacity 5000 kW")
    print("case | faulted | tie_node | isolation | restoration | back_fed")
    cases = [
        ("A1 tie on upstream end of faulted section", 3, "N-1201-3A"),
        ("A2 tie on downstream end, recloser also bounds it", 2, "N-1201-3"),
        ("A3 tie on upstream end, both ends bounded by non-ties", 2, "N-1201-2A"),
        ("A4 tie on a healthy node (control)", 2, "N-1201-1"),
    ]
    for label, indicated, node in cases:
        feeder = cedar_ridge(indicated)
        add_tie(feeder, "TIE-X", node)
        caps = {s.mrid: 5000.0 for s in feeder.switches if s.kind == SwitchKind.TIE}
        plan = flisr.build_plan(feeder, "CB-1201", caps)
        print(label, plan.faulted_section, node,
              [s.switch_mrid for s in plan.isolation],
              [s.switch_mrid for s in plan.restoration], back_fed(feeder, plan), sep=" | ")


def random_feeder(rng: random.Random) -> tuple[Feeder, int, dict[str, float]]:
    """Radial feeder, 2-8 sections, 1-3 SCADA ties on any section node."""
    n = rng.randint(2, 8)
    sections, switches = [], [
        Switch(mrid="CB", name="CB", kind=SwitchKind.BREAKER, open=True,
               scada_controllable=True, from_node="SRC", to_node="BUS")
    ]
    for i in range(n):
        start = "BUS" if i == 0 else f"N{i}A"
        if i > 0:
            switches.append(Switch(mrid=f"SW{i}", name=f"SW{i}", kind=SwitchKind.RECLOSER,
                                   scada_controllable=True, from_node=f"N{i}", to_node=start))
        sections.append(Section(mrid=f"S{i}", name=f"S{i}", from_node=start, to_node=f"N{i + 1}",
                                customers=rng.randint(1, 500),
                                load_kw=float(rng.randint(100, 2000)), fault_indicator=False))
    nodes = sorted({s.from_node for s in sections} | {s.to_node for s in sections} - {"BUS"})
    feeder = Feeder(mrid="F", name="F", substation="SUB", nominal_kv=12.47,
                    rating_amps=600.0, source_node="SRC", sections=sections, switches=switches)
    caps = {}
    for t, node in enumerate(rng.sample(nodes, rng.randint(1, min(3, len(nodes))))):
        add_tie(feeder, f"TIE{t}", node)
        caps[f"TIE{t}"] = float(rng.randint(0, 6000))
    faulted = rng.randrange(1, n)
    for i in range(faulted):
        sections[i].fault_indicator = True
    return feeder, faulted, caps


def touches_faulted(feeder: Feeder, plan) -> bool:
    faulted = next(s for s in feeder.sections if s.mrid == plan.faulted_section)
    closed = {s.switch_mrid for s in plan.restoration if s.action == "close"}
    return any(
        sw.mrid in closed and sw.from_node in (faulted.from_node, faulted.to_node)
        for sw in feeder.switches if sw.kind == SwitchKind.TIE
    )


def sweep(cases: int, seed: int) -> dict[tuple[bool, bool, bool], int]:
    rng = random.Random(seed)
    counts: dict[tuple[bool, bool, bool], int] = {}
    for _ in range(cases):
        feeder, faulted, caps = random_feeder(rng)
        section = feeder.sections[faulted]
        tail_tie = any(sw.kind == SwitchKind.TIE and sw.from_node == section.to_node
                       and section.mrid == feeder.sections[-1].mrid for sw in feeder.switches)
        try:
            plan = flisr.build_plan(feeder, "CB", caps)
        except flisr.FlisrError:
            continue
        key = (tail_tie, touches_faulted(feeder, plan), back_fed(feeder, plan))
        counts[key] = counts.get(key, 0) + 1
    return counts


def guarded(cases: int, seed: int) -> None:
    """Counterfactual fix shape: refuse any tie whose pick-up set holds a faulted node."""
    original = flisr._nodes_restored_by
    current: dict[str, set[str]] = {}

    def refuse_faulted(feeder, tie_mrid, isolated):
        nodes = original(feeder, tie_mrid, isolated)
        return set() if nodes & current["faulted"] else nodes

    flisr._nodes_restored_by = refuse_faulted
    try:
        rng = random.Random(seed)
        unsafe = run = 0
        for _ in range(cases):
            feeder, faulted, caps = random_feeder(rng)
            s = feeder.sections[faulted]
            current["faulted"] = {s.from_node, s.to_node}
            try:
                plan = flisr.build_plan(feeder, "CB", caps)
            except flisr.FlisrError:
                continue
            run += 1
            unsafe += back_fed(feeder, plan)
        print(f"guarded: {run} plans, {unsafe} back-fed")

        feeder = cedar_ridge(2)
        s = next(x for x in feeder.sections if x.mrid == "SEC-1201-03")
        current["faulted"] = {s.from_node, s.to_node}
        plan = flisr.build_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
        print("guarded shipped default (test_build_plan_isolates_and_restores_tail inputs):",
              plan.faulted_section, sorted(x.switch_mrid for x in plan.isolation),
              [(x.switch_mrid, x.action) for x in plan.restoration],
              plan.customers_restored, plan.customers_remaining)
        feeder = cedar_ridge(3)
        s = next(x for x in feeder.sections if x.mrid == "SEC-1201-04")
        current["faulted"] = {s.from_node, s.to_node}
        plan = flisr.build_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
        print("guarded DEF-FLISR-7 scenario:", plan.faulted_section,
              [(x.switch_mrid, x.action) for x in plan.restoration],
              plan.customers_restored, plan.customers_remaining, plan.transferred_load_kw)
    finally:
        flisr._nodes_restored_by = original


if __name__ == "__main__":
    part_a()
    print("\nB. Seeded radial feeders, 1-3 ties on any node (seed=11, cases=500), unpatched")
    print("tail_tie_case | closed_tie_on_faulted_node | back_fed | cases")
    for key, value in sorted(sweep(500, 11).items()):
        print(*key, value, sep=" | ")
    print("\nC. Same 500 inputs with the refuse-the-tie guard patched in")
    guarded(500, 11)
