"""Fault Location, Isolation and Service Restoration.

Triggered by a protection lockout on a feeder breaker or recloser. The engine
uses fault-passage indications to locate the faulted section, isolates it with
the nearest SCADA-controllable switches, and restores the healthy sections
downstream through tie switches where the alternate feeder has capacity.
"""

from __future__ import annotations

from collections import deque

from .models import Feeder, IsolationStep, RestorationPlan
from .network import (
    adjacency,
    energised_nodes,
    load_on_nodes,
    sections_downstream_of,
    switch_by_mrid,
)


class FlisrError(RuntimeError):
    """Raised when the engine cannot build a defensible plan."""


def locate_fault(feeder: Feeder) -> str | None:
    """Faulted section = the section just downstream of the farthest fault indication.

    Distance is measured along the feeder's normal topology from the source, so the
    order of `feeder.sections` is irrelevant. Refuses with FlisrError rather than
    guess when the indications do not single out one section: non-radial topology,
    an indication not fed from the source, indications on more than one branch, or
    more than one unindicated section fed from the farthest indication.
    """
    indicated = {section.mrid for section in feeder.sections if section.fault_indicator}
    if not indicated:
        return None

    upstream = _upstream_sections(feeder)
    unfed = indicated - upstream.keys()
    if unfed:
        raise FlisrError(
            f"fault indication on {', '.join(sorted(unfed))} not fed from {feeder.source_node}"
        )

    def path_from_source(mrid: str) -> list[str]:
        path: list[str] = []
        current: str | None = mrid
        while current is not None:
            path.append(current)
            current = upstream[current]
        return path

    farthest = max(indicated, key=lambda mrid: len(path_from_source(mrid)))
    stray = indicated - set(path_from_source(farthest))
    if stray:
        raise FlisrError(
            f"fault indications on more than one branch: {', '.join(sorted(stray))} "
            f"is not upstream of {farthest}"
        )

    beyond = [mrid for mrid, parent in upstream.items() if parent == farthest]
    if not beyond:
        return farthest
    if len(beyond) > 1:
        raise FlisrError(
            f"fault beyond {farthest} could be on any of {', '.join(beyond)}; "
            "manual patrol required"
        )
    return beyond[0]


def _upstream_sections(feeder: Feeder) -> dict[str, str | None]:
    """Section mRID -> nearest upstream section mRID (None at the feeder head), for
    every section fed from the source in the normal switching state."""
    normal = feeder.model_copy(deep=True)
    for switch in normal.switches:
        switch.open = switch.normal_open
    graph = adjacency(normal)
    sections = {section.mrid for section in feeder.sections}

    upstream: dict[str, str | None] = {}
    feeding: dict[str, str | None] = {normal.source_node: None}
    walked: set[str] = set()
    queue = deque([normal.source_node])
    while queue:
        node = queue.popleft()
        for neighbour, element in graph.get(node, []):
            if element in walked:
                continue
            walked.add(element)
            if neighbour in feeding:
                raise FlisrError(f"{feeder.name} is not radial: {element} closes a loop")
            if element in sections:
                upstream[element] = feeding[node]
                feeding[neighbour] = element
            else:
                feeding[neighbour] = feeding[node]
            queue.append(neighbour)
    return upstream


def _isolation_switches(feeder: Feeder, faulted_section_mrid: str) -> list[IsolationStep]:
    section = next(s for s in feeder.sections if s.mrid == faulted_section_mrid)
    steps: list[IsolationStep] = []
    for switch in feeder.switches:
        if not switch.scada_controllable or switch.kind.value == "tie":
            continue
        if switch.to_node == section.from_node:
            steps.append(
                IsolationStep(
                    switch_mrid=switch.mrid,
                    action="open",
                    reason=f"upstream isolation of {section.name}",
                )
            )
        elif switch.from_node == section.to_node:
            steps.append(
                IsolationStep(
                    switch_mrid=switch.mrid,
                    action="open",
                    reason=f"downstream isolation of {section.name}",
                )
            )
    if not steps:
        raise FlisrError(f"no SCADA switch can isolate {section.name}")
    return steps


def build_plan(
    feeder: Feeder,
    lockout_switch_mrid: str,
    tie_capacity_kw: dict[str, float] | None = None,
) -> RestorationPlan:
    tie_capacity_kw = tie_capacity_kw or {}
    lockout = switch_by_mrid(feeder, lockout_switch_mrid)
    if not lockout.open:
        raise FlisrError(f"{lockout.name} is not in lockout")

    faulted = locate_fault(feeder)
    plan = RestorationPlan(feeder_mrid=feeder.mrid, faulted_section=faulted)
    if faulted is None:
        plan.notes.append("no fault indication received; manual patrol required")
        plan.customers_remaining = sum(
            section.customers
            for section in sections_downstream_of(feeder, lockout.to_node)
        )
        return plan

    plan.isolation = _isolation_switches(feeder, faulted)
    isolated_mrids = {step.switch_mrid for step in plan.isolation}

    faulted_section = next(s for s in feeder.sections if s.mrid == faulted)
    plan.customers_remaining = faulted_section.customers

    for switch in feeder.switches:
        if switch.kind.value != "tie" or not switch.scada_controllable:
            continue
        candidate_nodes = _nodes_restored_by(feeder, switch.mrid, isolated_mrids)
        if not candidate_nodes:
            continue
        transferred = load_on_nodes(feeder, candidate_nodes)
        available = tie_capacity_kw.get(switch.mrid, 0.0)
        if transferred > available:
            plan.notes.append(
                f"{switch.name} skipped: {transferred:.0f} kW exceeds "
                f"{available:.0f} kW available capacity"
            )
            plan.customers_remaining += sum(
                section.customers
                for section in feeder.sections
                if section.to_node in candidate_nodes
            )
            continue
        plan.restoration.append(
            IsolationStep(
                switch_mrid=switch.mrid,
                action="close",
                reason=f"back-feed {len(candidate_nodes)} nodes from alternate source",
            )
        )
        plan.transferred_load_kw += transferred
        plan.customers_restored += sum(
            section.customers
            for section in feeder.sections
            if section.to_node in candidate_nodes
        )

    if lockout.scada_controllable:
        plan.restoration.insert(
            0,
            IsolationStep(
                switch_mrid=lockout.mrid,
                action="close",
                reason="re-energise healthy sections upstream of the fault",
            ),
        )
    return plan


def _nodes_restored_by(
    feeder: Feeder, tie_mrid: str, isolated_switches: set[str]
) -> set[str]:
    """Nodes picked up by closing `tie_mrid` after isolation, excluding the
    part of the feeder still fed from its own source."""
    working = feeder.model_copy(deep=True)
    for switch in working.switches:
        if switch.mrid in isolated_switches:
            switch.open = True
        if switch.mrid == tie_mrid:
            switch.open = False

    tie = switch_by_mrid(working, tie_mrid)
    from_tie = energised_nodes(working, tie.from_node)
    from_source = energised_nodes(working, working.source_node)
    return from_tie - from_source
