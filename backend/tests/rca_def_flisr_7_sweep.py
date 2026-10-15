"""DEF-FLISR-7 diagnostic sweep (not collected by pytest).

Run: PYTHONPATH=backend python backend/tests/rca_def_flisr_7_sweep.py
"""

from __future__ import annotations

import random

from app import flisr
from app.models import Feeder, Section, Switch, SwitchKind
from app.network import energised_nodes, get_feeder, load_network, switch_by_mrid


def back_fed(feeder: Feeder, plan) -> bool:
    work = feeder.model_copy(deep=True)
    for step in plan.isolation + plan.restoration:
        switch_by_mrid(work, step.switch_mrid).open = step.action == "open"
    faulted = next(s for s in work.sections if s.mrid == plan.faulted_section)
    live = energised_nodes(work)
    for sw in work.switches:
        if sw.kind == SwitchKind.TIE and not sw.open:
            live |= energised_nodes(work, sw.to_node)
    return bool({faulted.from_node, faulted.to_node} & live)


def cedar_ridge(indicated: int) -> Feeder:
    feeder = get_feeder(load_network(), "FDR-1201")
    for i, section in enumerate(feeder.sections):
        section.fault_indicator = i < indicated
    switch_by_mrid(feeder, "CB-1201").open = True
    return feeder


def part_a() -> None:
    print("A. FDR-1201, every locatable faulted section x tie capacity")
    print("faulted | cap_kw | isolation | restoration | tie_candidates | back_fed")
    for indicated in (1, 2, 3):
        for cap in (0.0, 1489.0, 1490.0, 2000.0):
            feeder = cedar_ridge(indicated)
            plan = flisr.build_plan(feeder, "CB-1201", {"TIE-1201-1405": cap})
            iso = {s.switch_mrid for s in plan.isolation}
            cand = sorted(flisr._nodes_restored_by(feeder, "TIE-1201-1405", iso))
            print(
                plan.faulted_section, cap, sorted(iso),
                [(s.switch_mrid, s.action) for s in plan.restoration], cand,
                back_fed(feeder, plan), sep=" | ",
            )


def part_b() -> None:
    print("\nB. Counterfactual: include ties in isolation (flisr.py:42 only), keep the rest")
    original = flisr._isolation_switches

    def with_ties(feeder: Feeder, faulted: str):
        section = next(s for s in feeder.sections if s.mrid == faulted)
        steps = original(feeder, faulted)
        for sw in feeder.switches:
            if sw.kind == SwitchKind.TIE and section.to_node in (sw.from_node, sw.to_node):
                steps.append(flisr.IsolationStep(switch_mrid=sw.mrid, action="open", reason="tie"))
        return steps

    flisr._isolation_switches = with_ties
    try:
        feeder = cedar_ridge(3)
        plan = flisr.build_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
        print("isolation", [(s.switch_mrid, s.action) for s in plan.isolation])
        print("restoration", [(s.switch_mrid, s.action) for s in plan.restoration])
        print("back_fed", back_fed(feeder, plan))
    finally:
        flisr._isolation_switches = original


def random_feeder(rng: random.Random) -> tuple[Feeder, int, float]:
    n = rng.randint(2, 8)
    sections, switches = [], [
        Switch(mrid="CB", name="CB", kind=SwitchKind.BREAKER, open=True,
               scada_controllable=True, from_node="SRC", to_node="BUS")
    ]
    node = "BUS"
    for i in range(n):
        start = node if i == 0 else f"N{i}A"
        if i > 0:
            switches.append(Switch(mrid=f"SW{i}", name=f"SW{i}", kind=SwitchKind.RECLOSER,
                                   scada_controllable=True, from_node=f"N{i}", to_node=start))
        sections.append(Section(mrid=f"S{i}", name=f"S{i}", from_node=start, to_node=f"N{i + 1}",
                                customers=rng.randint(1, 500),
                                load_kw=float(rng.randint(100, 2000)), fault_indicator=False))
    switches.append(Switch(mrid="TIE", name="TIE", kind=SwitchKind.TIE, normal_open=True,
                           open=True, scada_controllable=True, from_node=f"N{n}", to_node="ALT"))
    faulted = rng.randrange(1, n)
    for i in range(faulted):
        sections[i].fault_indicator = True
    feeder = Feeder(mrid="F", name="F", substation="SUB", nominal_kv=12.47,
                    rating_amps=600.0, source_node="SRC", sections=sections, switches=switches)
    return feeder, faulted, float(rng.randint(0, 6000))


def part_c(cases: int = 500, seed: int = 7) -> None:
    print(f"\nC. Seeded radial feeders with a tail tie (seed={seed}, cases={cases})")
    rng = random.Random(seed)
    counts: dict[tuple[bool, bool, bool], int] = {}
    for _ in range(cases):
        feeder, faulted, cap = random_feeder(rng)
        try:
            plan = flisr.build_plan(feeder, "CB", {"TIE": cap})
        except flisr.FlisrError:
            continue
        adjacent = feeder.sections[faulted].to_node == "N" + str(len(feeder.sections))
        tie_closed = ("TIE", "close") in [(s.switch_mrid, s.action) for s in plan.restoration]
        key = (adjacent, tie_closed, back_fed(feeder, plan))
        counts[key] = counts.get(key, 0) + 1
    print("faulted_adjacent_to_tie | tie_closed | back_fed | cases")
    for key in sorted(counts):
        print(*key, counts[key], sep=" | ")


if __name__ == "__main__":
    part_a()
    part_b()
    part_c()
