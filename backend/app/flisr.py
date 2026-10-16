"""Fault Location, Isolation and Service Restoration.

Triggered by a protection lockout on a feeder breaker or recloser. The engine
uses fault-passage indications to locate the faulted section, isolates it with
the nearest SCADA-controllable switches, and restores the healthy sections
downstream through tie switches where the alternate feeder has capacity.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from .models import (
    TIE_CAPACITY_GOOD_QUALITY,
    TIE_CAPACITY_MAX_AGE,
    TIE_CAPACITY_MAX_LEAD,
    TIE_CAPACITY_TOLERANCE_KW,
    BlockedTie,
    Feeder,
    IsolationStep,
    RestorationPlan,
    Switch,
    TieBlockReason,
    TieCapacity,
)
from .network import (
    energised_nodes,
    load_on_nodes,
    sections_downstream_of,
    switch_by_mrid,
)


class FlisrError(RuntimeError):
    """Raised when the engine cannot build a defensible plan."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _not_finite_nonneg(value: object) -> bool:
    """True when value is not a real number (bool excluded), or is NaN, +/-inf or negative."""
    return not (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _is_aware_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def tie_capacity_verdict(
    entry: TieCapacity | None, transferred_kw: float, as_of: datetime
) -> TieBlockReason | None:
    """The one tie-capacity characteristic: None = the tie may close, else why it may not.

    Preconditions, checked before any comparison; a violation raises ValueError (no verdict):
    transferred_kw is a finite number >= 0; as_of is a timezone-aware datetime; entry is None
    or a TieCapacity with a timezone-aware timestamp.
    Decisions, first match wins (REQ-TIECAP-9): no entry -> CAPACITY_UNKNOWN; kw not a finite
    number >= 0, or timestamp more than TIE_CAPACITY_MAX_LEAD ahead of as_of ->
    CAPACITY_INVALID; quality other than TIE_CAPACITY_GOOD_QUALITY -> CAPACITY_UNKNOWN; older
    than TIE_CAPACITY_MAX_AGE -> CAPACITY_STALE; transferred_kw <= kw +
    TIE_CAPACITY_TOLERANCE_KW -> None; otherwise CAPACITY_EXCEEDED. Never called for a tie the
    DEF-FLISR-7 guard holds. Never substitutes, clamps or defaults a value.
    """
    if _not_finite_nonneg(transferred_kw):
        raise ValueError(
            f"transferred load {transferred_kw!r} kW is not a finite non-negative number"
        )
    if not _is_aware_datetime(as_of):
        raise ValueError(f"as_of {as_of!r} is not a timezone-aware datetime")
    if entry is None:
        return TieBlockReason.CAPACITY_UNKNOWN
    if not isinstance(entry, TieCapacity):
        raise ValueError(f"tie capacity {entry!r} is not a TieCapacity")
    if not _is_aware_datetime(entry.timestamp):
        raise ValueError(f"tie capacity timestamp {entry.timestamp!r} is not timezone-aware")
    age = as_of - entry.timestamp
    if _not_finite_nonneg(entry.kw) or age < -TIE_CAPACITY_MAX_LEAD:
        return TieBlockReason.CAPACITY_INVALID
    if entry.quality != TIE_CAPACITY_GOOD_QUALITY:
        return TieBlockReason.CAPACITY_UNKNOWN
    if age > TIE_CAPACITY_MAX_AGE:
        return TieBlockReason.CAPACITY_STALE
    if transferred_kw <= entry.kw + TIE_CAPACITY_TOLERANCE_KW:
        return None
    return TieBlockReason.CAPACITY_EXCEEDED


def _legacy_to_tie_capacity(
    tie_capacity_kw: dict[str, float], as_of: datetime
) -> dict[str, TieCapacity]:
    """Deprecated map: each value is a GOOD reading taken at as_of (REQ-TIECAP-16).

    model_construct skips validation so NaN, inf, negative or non-numeric values reach the
    verdict and are reported CAPACITY_INVALID instead of being coerced.
    """
    return {
        mrid: TieCapacity.model_construct(
            kw=kw, timestamp=as_of, quality=TIE_CAPACITY_GOOD_QUALITY
        )
        for mrid, kw in tie_capacity_kw.items()
    }


def _blocked_note(
    switch: Switch,
    reason: TieBlockReason,
    entry: TieCapacity | None,
    transferred_kw: float,
    as_of: datetime,
) -> str:
    """Operator note for a capacity-blocked tie; formats the verdict's reason, decides nothing."""
    prefix = f"{switch.name} blocked ({reason.value})"
    if entry is None:
        return f"{prefix}: no capacity value"
    if reason is TieBlockReason.CAPACITY_EXCEEDED:
        return (
            f"{prefix}: {transferred_kw:.1f} kW to transfer exceeds {entry.kw:.1f} kW "
            f"available capacity (+{TIE_CAPACITY_TOLERANCE_KW:g} kW tolerance)"
        )
    if reason is TieBlockReason.CAPACITY_STALE:
        age_s = (as_of - entry.timestamp).total_seconds()
        return (
            f"{prefix}: capacity value is {age_s:.3f} s old "
            f"(limit {TIE_CAPACITY_MAX_AGE.total_seconds():g} s)"
        )
    if reason is TieBlockReason.CAPACITY_UNKNOWN:
        return (
            f"{prefix}: capacity quality {entry.quality!r} is not {TIE_CAPACITY_GOOD_QUALITY}"
        )
    if _not_finite_nonneg(entry.kw):
        return f"{prefix}: capacity {entry.kw} kW is not a finite non-negative number"
    lead_s = (entry.timestamp - as_of).total_seconds()
    return (
        f"{prefix}: capacity timestamp is {lead_s:.3f} s ahead of as_of "
        f"(limit {TIE_CAPACITY_MAX_LEAD.total_seconds():g} s)"
    )


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
    *,
    tie_capacity: dict[str, TieCapacity] | None = None,
    as_of: datetime | None = None,
) -> RestorationPlan:
    """Isolation and restoration plan for a feeder in lockout.

    tie_capacity: alternate-feeder spare capacity per tie mRID. A candidate tie without a
    usable entry is never closed; it is listed in plan.blocked_ties (tie_capacity_verdict).
    tie_capacity_kw: deprecated plain-kW map, read as GOOD readings taken at as_of; mutually
    exclusive with tie_capacity (both given -> ValueError, no plan).
    as_of: timezone-aware evaluation instant, read from the UTC clock once when None; a naive
    or non-datetime value -> ValueError, no plan.
    A candidate section load that is not a finite number >= 0 means the network model is
    invalid: FlisrError, no plan.
    """
    if tie_capacity is not None and tie_capacity_kw is not None:
        raise ValueError("tie_capacity and tie_capacity_kw are mutually exclusive")
    if as_of is None:
        as_of = _utc_now()
    if not _is_aware_datetime(as_of):
        raise ValueError(f"as_of {as_of!r} is not a timezone-aware datetime")
    as_of = as_of.astimezone(UTC)
    deprecations: list[str] = []
    if tie_capacity_kw is not None:
        capacities = _legacy_to_tie_capacity(tie_capacity_kw, as_of)
        deprecations.append("tie_capacity_kw")
    elif tie_capacity is not None:
        capacities = tie_capacity
    else:
        capacities = {}

    lockout = switch_by_mrid(feeder, lockout_switch_mrid)
    if not lockout.open:
        raise FlisrError(f"{lockout.name} is not in lockout")

    faulted = locate_fault(feeder)
    plan = RestorationPlan(
        feeder_mrid=feeder.mrid,
        faulted_section=faulted,
        as_of=as_of,
        deprecations=deprecations,
    )
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
        for section in feeder.sections:
            if section.to_node in candidate_nodes and _not_finite_nonneg(section.load_kw):
                raise FlisrError(
                    f"{section.name}: load_kw {section.load_kw} kW is not a finite non-negative "
                    "number; network model invalid, no plan"
                )
        if candidate_nodes & {faulted_section.from_node, faulted_section.to_node}:
            plan.notes.append(
                f"{switch.name} ({switch.mrid}) held open: would back-feed faulted section "
                f"{faulted_section.name} ({faulted_section.mrid})"
            )
            plan.blocked_ties.append(
                BlockedTie(tie_id=switch.mrid, reason=TieBlockReason.FAULTED_SECTION)
            )
            plan.customers_remaining += sum(
                section.customers
                for section in feeder.sections
                if section.to_node in candidate_nodes and section.mrid != faulted_section.mrid
            )
            continue
        transferred = load_on_nodes(feeder, candidate_nodes)
        if _not_finite_nonneg(transferred):
            raise FlisrError(
                f"{switch.name}: transferred load {transferred} kW is not a finite non-negative "
                "number; network model invalid, no plan"
            )
        entry = capacities.get(switch.mrid)
        reason = tie_capacity_verdict(entry, transferred, as_of)
        if reason is not None:
            plan.blocked_ties.append(BlockedTie(tie_id=switch.mrid, reason=reason))
            plan.notes.append(_blocked_note(switch, reason, entry, transferred, as_of))
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
