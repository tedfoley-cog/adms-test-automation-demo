"""Fault Location, Isolation and Service Restoration.

Triggered by a protection lockout on a feeder breaker or recloser. The engine
uses fault-passage indications to locate the faulted section, isolates it with
the nearest SCADA-controllable switches, and restores the healthy sections
downstream through tie switches where the alternate feeder has capacity.
"""

from __future__ import annotations

from .models import Feeder, IsolationStep, RestorationPlan
from .network import (
    energised_nodes,
    load_on_nodes,
    sections_downstream_of,
    switch_by_mrid,
)


class FlisrError(RuntimeError):
    """Raised when the engine cannot build a defensible plan."""


def locate_fault(feeder: Feeder) -> str | None:
    """Faulted section = the first section beyond the last fault indication."""
    indicated = [section for section in feeder.sections if section.fault_indicator]
    if not indicated:
        return None

    order = {section.mrid: index for index, section in enumerate(feeder.sections)}
    last_indicated = max(indicated, key=lambda section: order[section.mrid])
    index = order[last_indicated.mrid]
    if index + 1 < len(feeder.sections):
        return feeder.sections[index + 1].mrid
    return last_indicated.mrid


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
            section.customers for section in sections_downstream_of(feeder, lockout.to_node)
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
            section.customers for section in feeder.sections if section.to_node in candidate_nodes
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


def _nodes_restored_by(feeder: Feeder, tie_mrid: str, isolated_switches: set[str]) -> set[str]:
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
