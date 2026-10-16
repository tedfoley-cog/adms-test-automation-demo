"""build_plan tie-capacity evaluation (U3; REQ-TIECAP-2..12, 15, 16, 18, 20).

Expected values come from the `oracle_*` functions below: an independent closed form over
the test topology with literals from the specification (design section 6.3, Q-DESIGN-1).
They import nothing from app.flisr or app.network and none of the models.py thresholds;
test_req_tiecap_3_oracle_is_independent checks that mechanically (O1).
Shipped FDR-1201 with CB-1201 in lockout: fault on SEC-1201-03, TIE-1201-1405 picks up
SEC-1201-04, L = 1490 kW, 341 customers (design section 6.2).
"""

from __future__ import annotations

import ast
import itertools
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import flisr
from app.flisr import FlisrError, build_plan, tie_capacity_verdict
from app.models import Feeder, Section, Switch, SwitchKind, TieCapacity
from app.network import get_feeder, load_network, switch_by_mrid

TIE = "TIE-1201-1405"
TIE_NAME = "Hollow Creek tie to 1405"
AS_OF = datetime(2026, 10, 15, 22, 0, 0, tzinfo=UTC)
HELD_OPEN_NOTE = (
    "Hollow Creek tie to 1405 (TIE-1201-1405) held open: would back-feed faulted section "
    "Hollow Creek tail (SEC-1201-04)"
)
APP_DIR = Path(__file__).resolve().parents[1] / "app"


# ---------------------------------------------------------------- fixtures (test topology)


def cedar_ridge_in_lockout(indicated: set[str] | None = None) -> Feeder:
    feeder = get_feeder(load_network(), "FDR-1201")
    if indicated is not None:
        for section in feeder.sections:
            section.fault_indicator = section.mrid in indicated
    switch_by_mrid(feeder, "CB-1201").open = True
    return feeder


def cedar_ridge_faulted_on_sec_1201_04() -> Feeder:
    return cedar_ridge_in_lockout({"SEC-1201-01", "SEC-1201-02", "SEC-1201-03"})


def section_named(feeder: Feeder, mrid: str) -> Section:
    return next(s for s in feeder.sections if s.mrid == mrid)


def _section(mrid, from_node, to_node, customers, load_kw, indicated=False) -> Section:
    return Section(mrid=mrid, name=mrid, from_node=from_node, to_node=to_node,
                   customers=customers, load_kw=load_kw, fault_indicator=indicated)


def _switch(mrid, kind, from_node, to_node, is_open=False) -> Switch:
    return Switch(mrid=mrid, name=f"{mrid} name", kind=kind, from_node=from_node,
                  to_node=to_node, open=is_open, normal_open=is_open)


def two_tie_feeder(held_tie: bool = False) -> Feeder:
    """Branched feeder, fault on SEC-B; TIE-T1 picks up SEC-C (300 kW, 30 customers) and
    TIE-T2 picks up SEC-D (150 kW, 20 customers). With held_tie, TIE-H sits on N1A (an
    endpoint of SEC-B) between them in switch order and picks up SEC-B and the healthy
    SEC-E (10 customers), so the DEF-FLISR-7 guard holds it.

    SRC -CB-T- BUS =SEC-A= N1 -REC-T1- N1A =SEC-B= N2 -SW-T2- N2A =SEC-C= N3 -TIE-T1- ALT-1
                                                   N2 -SW-T3- N2B =SEC-D= N4 -TIE-T2- ALT-2
    held_tie only:  N1A =SEC-E= N5,  N1A -TIE-H- ALT-H
    """
    sections = [
        _section("SEC-A", "BUS", "N1", 120, 500.0, indicated=True),
        _section("SEC-B", "N1A", "N2", 50, 200.0),
        _section("SEC-C", "N2A", "N3", 30, 300.0),
        _section("SEC-D", "N2B", "N4", 20, 150.0),
    ]
    switches = [
        _switch("CB-T", SwitchKind.BREAKER, "SRC", "BUS", is_open=True),
        _switch("REC-T1", SwitchKind.RECLOSER, "N1", "N1A"),
        _switch("SW-T2", SwitchKind.SECTIONALIZER, "N2", "N2A"),
        _switch("SW-T3", SwitchKind.SECTIONALIZER, "N2", "N2B"),
        _switch("TIE-T1", SwitchKind.TIE, "N3", "ALT-1", is_open=True),
        _switch("TIE-T2", SwitchKind.TIE, "N4", "ALT-2", is_open=True),
    ]
    if held_tie:
        sections.append(_section("SEC-E", "N1A", "N5", 10, 40.0))
        switches.insert(5, _switch("TIE-H", SwitchKind.TIE, "N1A", "ALT-H", is_open=True))
    return Feeder(mrid="FDR-T", name="Two-tie test feeder", substation="TEST",
                  nominal_kv=12.47, source_node="SRC", rating_amps=600.0,
                  sections=sections, switches=switches)


def cap(kw: float = 2000.0, age_ms: int = 0, quality: str = "GOOD") -> TieCapacity:
    """A TieCapacity aged `age_ms` milliseconds relative to AS_OF (negative = ahead)."""
    return TieCapacity(kw=kw, timestamp=AS_OF - timedelta(milliseconds=age_ms), quality=quality)


def reasons(plan) -> list[tuple[str, str]]:
    return [(b.tie_id, b.reason.value) for b in plan.blocked_ties]


def closed_ties(plan, lockout: str) -> list[str]:
    return [s.switch_mrid for s in plan.restoration
            if s.action == "close" and s.switch_mrid != lockout]


# ---------------------------------------------------------------- independent oracle


def oracle_reachable(feeder: Feeder, start: str, open_mrids: set[str], closed_mrid: str):
    graph: dict[str, set[str]] = defaultdict(set)
    for section in feeder.sections:
        graph[section.from_node].add(section.to_node)
        graph[section.to_node].add(section.from_node)
    for switch in feeder.switches:
        is_open = (switch.open or switch.mrid in open_mrids) and switch.mrid != closed_mrid
        if not is_open:
            graph[switch.from_node].add(switch.to_node)
            graph[switch.to_node].add(switch.from_node)
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(graph[node] - seen)
    return seen


def oracle_candidate_nodes(feeder: Feeder, tie_mrid: str, opened: set[str]) -> set[str]:
    """Spec definition: nodes the tie picks up after isolation, minus those the feeder's own
    source still reaches (the lockout breaker is still open)."""
    tie = next(s for s in feeder.switches if s.mrid == tie_mrid)
    from_tie = oracle_reachable(feeder, tie.from_node, opened, tie_mrid)
    from_source = oracle_reachable(feeder, feeder.source_node, opened, tie_mrid)
    return from_tie - from_source


def oracle_load_kw(feeder: Feeder, nodes: set[str]) -> float:
    return sum(s.load_kw for s in feeder.sections if s.to_node in nodes)


def oracle_customers(feeder: Feeder, nodes: set[str], skip_mrid: str | None = None) -> int:
    return sum(s.customers for s in feeder.sections
               if s.to_node in nodes and s.mrid != skip_mrid)


def oracle_held(feeder: Feeder, nodes: set[str], faulted_mrid: str) -> bool:
    faulted = next(s for s in feeder.sections if s.mrid == faulted_mrid)
    return bool(nodes & {faulted.from_node, faulted.to_node})


def oracle_sections_ok(feeder: Feeder, nodes: set[str]) -> bool:
    return all(math.isfinite(s.load_kw) and s.load_kw >= 0
               for s in feeder.sections if s.to_node in nodes)


def oracle_l_in_range(load_kw: float) -> bool:
    return math.isfinite(load_kw) and load_kw >= 0


def oracle_reason(entry, load_kw: float, as_of: datetime) -> str | None:
    """None = close. Literals from the spec: 0.5 kW, 20 s, 2 s, "GOOD" (REQ-TIECAP-3..9)."""
    if entry is None:
        return "CAPACITY_UNKNOWN"
    age = as_of - entry.timestamp
    kw = entry.kw
    kw_ok = isinstance(kw, int | float) and not isinstance(kw, bool) and math.isfinite(kw)
    if not (kw_ok and kw >= 0) or age < timedelta(seconds=-2):
        return "CAPACITY_INVALID"
    if entry.quality != "GOOD":
        return "CAPACITY_UNKNOWN"
    if age > timedelta(seconds=20):
        return "CAPACITY_STALE"
    if load_kw <= kw + 0.5:
        return None
    return "CAPACITY_EXCEEDED"


def oracle_expected(feeder: Feeder, plan, lockout: str, capacities: dict, as_of: datetime):
    """Expected closes, blocked_ties and accounting for `plan`'s isolation (spec section 0)."""
    opened = {step.switch_mrid for step in plan.isolation}
    faulted = plan.faulted_section
    closes, blocked = [], []
    restored = 0
    remaining = next(s.customers for s in feeder.sections if s.mrid == faulted)
    transferred = 0.0
    for switch in feeder.switches:
        if switch.kind != SwitchKind.TIE or not switch.scada_controllable:
            continue
        nodes = oracle_candidate_nodes(feeder, switch.mrid, opened)
        if not nodes:
            continue
        if oracle_held(feeder, nodes, faulted):
            blocked.append((switch.mrid, "FAULTED_SECTION"))
            remaining += oracle_customers(feeder, nodes, skip_mrid=faulted)
            continue
        load_kw = oracle_load_kw(feeder, nodes)
        reason = oracle_reason(capacities.get(switch.mrid), load_kw, as_of)
        if reason is None:
            closes.append(switch.mrid)
            restored += oracle_customers(feeder, nodes)
            transferred += load_kw
        else:
            blocked.append((switch.mrid, reason))
            remaining += oracle_customers(feeder, nodes)
    return {"closes": closes, "blocked": blocked, "customers_restored": restored,
            "customers_remaining": remaining, "transferred_load_kw": transferred}


def assert_matches_oracle(feeder: Feeder, lockout: str, capacities: dict, as_of=AS_OF):
    plan = build_plan(feeder, lockout, tie_capacity=capacities, as_of=as_of)
    expected = oracle_expected(feeder, plan, lockout, capacities, as_of)
    assert closed_ties(plan, lockout) == expected["closes"]
    assert reasons(plan) == expected["blocked"]
    assert plan.customers_restored == expected["customers_restored"]
    assert plan.customers_remaining == expected["customers_remaining"]
    assert plan.transferred_load_kw == pytest.approx(expected["transferred_load_kw"], abs=1e-9)
    return plan


# ---------------------------------------------------------------- oracle checks (O1, self-check)


def _forbidden_oracle_refs(source: str) -> list[str]:
    """O1 (design 6.3): names an oracle_* function must not reach."""
    tree = ast.parse(source)
    logic_names: set[str] = set()
    logic_modules: set[str] = set()
    models_modules: set[str] = set()
    threshold_names: set[str] = set()

    def is_threshold(name: str) -> bool:
        return name.startswith(("TIE_CAPACITY_", "AS_OF_"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in ("app.flisr", "app.network"):
                logic_names |= {a.asname or a.name for a in node.names}
            elif node.module == "app":
                for alias in node.names:
                    if alias.name in ("flisr", "network"):
                        logic_modules.add(alias.asname or alias.name)
                    if alias.name == "models":
                        models_modules.add(alias.asname or alias.name)
            elif node.module == "app.models":
                threshold_names |= {a.asname or a.name for a in node.names if is_threshold(a.name)}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("app.flisr", "app.network"):
                    logic_modules.add(alias.asname or alias.name)
                if alias.name == "app.models":
                    models_modules.add(alias.asname or alias.name)
    found = []
    for func in tree.body:
        if not (isinstance(func, ast.FunctionDef) and func.name.startswith("oracle_")):
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Name) and (
                node.id in logic_names | logic_modules | threshold_names or is_threshold(node.id)
            ):
                found.append(f"{func.name}: {node.id}")
            if isinstance(node, ast.Attribute):
                root = ast.unparse(node.value)
                if root in logic_modules or root.startswith(("app.flisr", "app.network")):
                    found.append(f"{func.name}: {ast.unparse(node)}")
                if is_threshold(node.attr):
                    found.append(f"{func.name}: {ast.unparse(node)}")
    return found


@pytest.mark.requirement("REQ-TIECAP-3")
def test_req_tiecap_3_oracle_is_independent():
    assert _forbidden_oracle_refs(Path(__file__).read_text(encoding="utf-8")) == []


@pytest.mark.requirement("REQ-TIECAP-3")
def test_req_tiecap_3_oracle_independence_check_detects_violations():
    bad = (
        "from app.flisr import tie_capacity_verdict\n"
        "from app import models as mm\n"
        "from app.models import TIE_CAPACITY_MAX_AGE\n"
        "def oracle_x(e, L, t):\n"
        "    return tie_capacity_verdict(e, L, t) or mm.TIE_CAPACITY_TOLERANCE_KW "
        "or TIE_CAPACITY_MAX_AGE\n"
    )
    assert len(_forbidden_oracle_refs(bad)) == 3


@pytest.mark.requirement("REQ-TIECAP-3")
def test_req_tiecap_3_oracle_self_check_on_shipped_model():
    feeder = cedar_ridge_in_lockout()
    nodes = oracle_candidate_nodes(feeder, TIE, {"SEC-SW-1201-1", "REC-1201-2"})
    assert nodes == {"N-1201-3A", "N-1201-4", "ALT-1405"}
    assert oracle_load_kw(feeder, nodes) == 1490.0
    assert oracle_customers(feeder, nodes) == 341
    assert not oracle_held(feeder, nodes, "SEC-1201-03")
    assert oracle_reason(cap(1490.0), 1490.0, AS_OF) is None
    assert oracle_reason(cap(1489.5), 1490.0, AS_OF) is None
    assert oracle_reason(cap(1489.4), 1490.0, AS_OF) == "CAPACITY_EXCEEDED"
    assert oracle_reason(cap(age_ms=20_000), 1490.0, AS_OF) is None
    assert oracle_reason(cap(age_ms=20_001), 1490.0, AS_OF) == "CAPACITY_STALE"
    assert oracle_reason(cap(age_ms=-2_000), 1490.0, AS_OF) is None
    assert oracle_reason(cap(age_ms=-2_001), 1490.0, AS_OF) == "CAPACITY_INVALID"
    held = cedar_ridge_faulted_on_sec_1201_04()
    held_nodes = oracle_candidate_nodes(held, TIE, {"REC-1201-2"})
    assert oracle_held(held, held_nodes, "SEC-1201-04")
    assert oracle_customers(held, held_nodes, skip_mrid="SEC-1201-04") == 0


# ---------------------------------------------------------------- REQ-TIECAP-2 / 20: as_of


@pytest.mark.requirement("REQ-TIECAP-2")
def test_req_tiecap_2_utc_and_offset_as_of_give_identical_plans():
    offset = AS_OF.astimezone(timezone(timedelta(hours=2)))
    capacities = {TIE: cap(1489.5, age_ms=19_999)}
    in_utc = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity=capacities, as_of=AS_OF)
    in_offset = build_plan(
        cedar_ridge_in_lockout(), "CB-1201", tie_capacity=capacities, as_of=offset
    )
    assert in_offset.model_dump() == in_utc.model_dump()
    assert in_offset.as_of == AS_OF
    assert in_offset.as_of.utcoffset() == timedelta(0)
    assert closed_ties(in_offset, "CB-1201") == [TIE]


@pytest.mark.requirement("REQ-TIECAP-2")
@pytest.mark.parametrize(
    "as_of",
    [datetime(2026, 10, 15, 22, 0, 0), "2026-10-15T22:00:00Z", 1790000000.0],
    ids=["naive", "string", "number"],
)
def test_req_tiecap_2_naive_or_non_datetime_as_of_raises(as_of):
    with pytest.raises(ValueError, match="as_of"):
        build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity={TIE: cap()}, as_of=as_of)


@pytest.mark.requirement("REQ-TIECAP-2")
def test_req_tiecap_2_absent_as_of_is_utc_now():
    before = datetime.now(UTC)
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity={})
    after = datetime.now(UTC)
    assert before <= plan.as_of <= after
    assert plan.as_of.utcoffset() == timedelta(0)


@pytest.mark.requirement("REQ-TIECAP-20")
def test_req_tiecap_20_clock_read_once_per_call(monkeypatch):
    reads = []

    def fake_now():
        reads.append(1)
        return AS_OF + timedelta(seconds=len(reads) * 30)

    monkeypatch.setattr(flisr, "_utc_now", fake_now)
    capacities = {"TIE-T1": cap(300.0, age_ms=-30_000), "TIE-T2": cap(150.0, age_ms=-30_000)}
    plan = build_plan(two_tie_feeder(), "CB-T", tie_capacity=capacities)
    assert len(reads) == 1
    # Both entries aged against the one instant (age 0 s): both fresh, both close.
    assert plan.as_of == AS_OF + timedelta(seconds=30)
    assert closed_ties(plan, "CB-T") == ["TIE-T1", "TIE-T2"]

    reads.clear()
    build_plan(two_tie_feeder(), "CB-T", tie_capacity=capacities, as_of=AS_OF)
    assert reads == []


@pytest.mark.requirement("REQ-TIECAP-20")
def test_req_tiecap_20_no_clock_read_inside_the_tie_loop():
    tree = ast.parse((APP_DIR / "flisr.py").read_text(encoding="utf-8"))
    build = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_plan")
    calls = [n for n in ast.walk(build) if isinstance(n, ast.Call)
             and ast.unparse(n.func) in ("_utc_now", "datetime.now", "datetime.utcnow")]
    assert len(calls) == 1
    for loop in (n for n in ast.walk(build) if isinstance(n, ast.For)):
        assert not any(c in ast.walk(loop) for c in calls)


# ------------------------------------------------------ REQ-TIECAP-3 / 4: close iff L <= C + 0.5


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.requirement("REQ-TIECAP-4")
@pytest.mark.parametrize(
    ("capacity_kw", "expected"),
    [(1_000_000.0, None), (2000.0, None), (1490.0, None), (1489.5, None),
     (1489.4, "CAPACITY_EXCEEDED"), (1000.0, "CAPACITY_EXCEEDED"), (0.0, "CAPACITY_EXCEEDED")],
)
def test_req_tiecap_3_4_shipped_boundaries_against_oracle(capacity_kw, expected):
    capacities = {TIE: cap(capacity_kw)}
    assert oracle_reason(capacities[TIE], 1490.0, AS_OF) == expected
    plan = assert_matches_oracle(cedar_ridge_in_lockout(), "CB-1201", capacities)
    if expected is None:
        assert plan.restoration[-1].model_dump() == {
            "switch_mrid": TIE, "action": "close",
            "reason": "back-feed 3 nodes from alternate source",
        }
        assert (plan.customers_restored, plan.customers_remaining) == (341, 96)
        assert plan.transferred_load_kw == 1490.0
        assert plan.blocked_ties == []
    else:
        assert closed_ties(plan, "CB-1201") == []
        assert reasons(plan) == [(TIE, expected)]
        assert (plan.customers_restored, plan.customers_remaining) == (0, 437)
        assert plan.transferred_load_kw == 0.0  # no partial pick-up (Q-SPEC-6)


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.requirement("REQ-TIECAP-4")
@pytest.mark.parametrize("c1", [300.0, 299.5, 299.4, 0.0])
@pytest.mark.parametrize("c2", [150.0, 149.5, 149.4, 10_000.0])
def test_req_tiecap_3_4_two_tie_boundaries_against_oracle(c1, c2):
    assert_matches_oracle(two_tie_feeder(), "CB-T", {"TIE-T1": cap(c1), "TIE-T2": cap(c2)})


@pytest.mark.requirement("REQ-TIECAP-3")
def test_req_tiecap_3_zero_load_tie_closes_on_zero_capacity():
    feeder = cedar_ridge_in_lockout()
    section_named(feeder, "SEC-1201-04").load_kw = 0.0
    plan = assert_matches_oracle(feeder, "CB-1201", {TIE: cap(0.0)})
    assert closed_ties(plan, "CB-1201") == [TIE]


# ---------------------------------------------------------------- REQ-TIECAP-5: missing / non-GOOD


@pytest.mark.requirement("REQ-TIECAP-5")
@pytest.mark.parametrize(
    "capacities", [None, {}, {"TIE-ELSEWHERE": cap()}], ids=["none", "empty", "missing-key"]
)
def test_req_tiecap_5_missing_capacity_is_unknown(capacities):
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity=capacities, as_of=AS_OF)
    assert closed_ties(plan, "CB-1201") == []
    assert reasons(plan) == [(TIE, "CAPACITY_UNKNOWN")]
    assert (plan.customers_restored, plan.customers_remaining) == (0, 437)
    assert plan.notes == [f"{TIE_NAME} blocked (CAPACITY_UNKNOWN): no capacity value"]


@pytest.mark.requirement("REQ-TIECAP-5")
@pytest.mark.parametrize("quality", ["BAD", "SUSPECT", "good", "", " GOOD"])
def test_req_tiecap_5_non_good_quality_is_unknown(quality):
    capacities = {TIE: cap(quality=quality)}
    plan = assert_matches_oracle(cedar_ridge_in_lockout(), "CB-1201", capacities)
    assert reasons(plan) == [(TIE, "CAPACITY_UNKNOWN")]
    assert plan.notes == [
        f"{TIE_NAME} blocked (CAPACITY_UNKNOWN): capacity quality {quality!r} is not GOOD"
    ]


@pytest.mark.requirement("REQ-TIECAP-5")
def test_req_tiecap_5_no_default_capacity_left_in_flisr():
    """Inspection: no `.get(key, default)` and no `x or {}` / `or 0` left in flisr.py."""
    tree = ast.parse((APP_DIR / "flisr.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get":
                assert len(node.args) == 1 and not node.keywords, ast.unparse(node)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for value in node.values:
                assert not isinstance(value, ast.Constant | ast.Dict), ast.unparse(node)


# ---------------------------------------------------------------- REQ-TIECAP-6 / 7: age


@pytest.mark.requirement("REQ-TIECAP-6")
@pytest.mark.parametrize(
    ("age_ms", "expected"), [(19_999, None), (20_000, None), (20_001, "CAPACITY_STALE")]
)
def test_req_tiecap_6_stale_boundary(age_ms, expected):
    capacities = {TIE: cap(age_ms=age_ms)}
    assert oracle_reason(capacities[TIE], 1490.0, AS_OF) == expected
    plan = assert_matches_oracle(cedar_ridge_in_lockout(), "CB-1201", capacities)
    if expected:
        assert plan.notes == [
            f"{TIE_NAME} blocked (CAPACITY_STALE): capacity value is 20.001 s old (limit 20 s)"
        ]


@pytest.mark.requirement("REQ-TIECAP-7")
@pytest.mark.parametrize(
    ("age_ms", "expected"),
    [(-1, None), (-1_999, None), (-2_000, None), (-2_001, "CAPACITY_INVALID")],
)
def test_req_tiecap_7_future_dated_boundary(age_ms, expected):
    capacities = {TIE: cap(age_ms=age_ms)}
    assert oracle_reason(capacities[TIE], 1490.0, AS_OF) == expected
    plan = assert_matches_oracle(cedar_ridge_in_lockout(), "CB-1201", capacities)
    if expected:
        assert plan.notes == [
            f"{TIE_NAME} blocked (CAPACITY_INVALID): capacity timestamp is 2.001 s ahead of "
            "as_of (limit 2 s)"
        ]


# ---------------------------------------------------------------- REQ-TIECAP-8: invalid kw


@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.parametrize("kw", [math.nan, math.inf, -math.inf, -1.0, -1e-9])
def test_req_tiecap_8_non_finite_or_negative_capacity_is_invalid(kw):
    capacities = {TIE: cap(kw)}
    plan = assert_matches_oracle(cedar_ridge_in_lockout(), "CB-1201", capacities)
    assert closed_ties(plan, "CB-1201") == []
    assert reasons(plan) == [(TIE, "CAPACITY_INVALID")]
    assert plan.notes == [
        f"{TIE_NAME} blocked (CAPACITY_INVALID): capacity {kw} kW is not a finite "
        "non-negative number"
    ]


@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.parametrize("kw", [0.0, -0.0])
def test_req_tiecap_8_zero_capacity_is_valid(kw):
    plan = assert_matches_oracle(cedar_ridge_in_lockout(), "CB-1201", {TIE: cap(kw)})
    assert reasons(plan) == [(TIE, "CAPACITY_EXCEEDED")]


@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.parametrize("kw", ["2000", None, True])
def test_req_tiecap_8_non_real_kw_via_model_construct_is_invalid(kw):
    entry = TieCapacity.model_construct(kw=kw, timestamp=AS_OF, quality="GOOD")
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity={TIE: entry}, as_of=AS_OF)
    assert reasons(plan) == [(TIE, "CAPACITY_INVALID")]
    assert closed_ties(plan, "CB-1201") == []


# ---------------------------------------------------------------- REQ-TIECAP-9: precedence


def _entry_for(invalid_kw: bool, future: bool, non_good: bool, stale: bool, exceeded: bool):
    kw = math.nan if invalid_kw else (10.0 if exceeded else 2000.0)
    age_ms = -2_500 if future else (30_000 if stale else 0)
    return cap(kw, age_ms=age_ms, quality="BAD" if non_good else "GOOD")


PRECEDENCE_CASES = [
    flags for flags in itertools.product([False, True], repeat=5)
    if not (flags[1] and flags[3])  # a timestamp cannot be both ahead and stale
]


@pytest.mark.requirement("REQ-TIECAP-9")
@pytest.mark.parametrize("flags", PRECEDENCE_CASES)
def test_req_tiecap_9_first_reason_in_precedence_order(flags):
    invalid_kw, future, non_good, stale, exceeded = flags
    entry = _entry_for(*flags)
    if invalid_kw or future:
        expected = "CAPACITY_INVALID"
    elif non_good:
        expected = "CAPACITY_UNKNOWN"
    elif stale:
        expected = "CAPACITY_STALE"
    elif exceeded:
        expected = "CAPACITY_EXCEEDED"
    else:
        expected = None
    assert oracle_reason(entry, 1490.0, AS_OF) == expected
    plan = assert_matches_oracle(cedar_ridge_in_lockout(), "CB-1201", {TIE: entry})
    assert reasons(plan) == ([] if expected is None else [(TIE, expected)])
    assert len(plan.notes) == (0 if expected is None else 1)


HELD_CAPACITY_STATES = {
    "good-2000": {TIE: cap(2000.0)},
    "nan": {TIE: cap(math.nan)},
    "bad": {TIE: cap(quality="BAD")},
    "stale-30s": {TIE: cap(age_ms=30_000)},
    "future-3s": {TIE: cap(age_ms=-3_000)},
    "short-10kw": {TIE: cap(10.0)},
    "missing": {},
    "no-map": None,
}


@pytest.mark.requirement("REQ-TIECAP-9")
@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.requirement("REQ-TIECAP-18")
@pytest.mark.parametrize("capacities", HELD_CAPACITY_STATES.values(), ids=HELD_CAPACITY_STATES)
def test_req_tiecap_9_held_tie_is_faulted_section_whatever_the_capacity(capacities):
    feeder = cedar_ridge_faulted_on_sec_1201_04()
    plan = build_plan(feeder, "CB-1201", tie_capacity=capacities, as_of=AS_OF)
    assert plan.faulted_section == "SEC-1201-04"
    assert closed_ties(plan, "CB-1201") == []
    assert reasons(plan) == [(TIE, "FAULTED_SECTION")]
    assert plan.notes == [HELD_OPEN_NOTE]
    assert (plan.customers_restored, plan.customers_remaining) == (0, 341)
    assert plan.transferred_load_kw == 0.0
    expected = oracle_expected(feeder, plan, "CB-1201", capacities or {}, AS_OF)
    assert reasons(plan) == expected["blocked"]
    assert plan.customers_remaining == expected["customers_remaining"]


@pytest.mark.requirement("REQ-TIECAP-9")
@pytest.mark.requirement("REQ-TIECAP-16")
def test_req_tiecap_9_held_tie_legacy_map_is_faulted_section():
    plan = build_plan(cedar_ridge_faulted_on_sec_1201_04(), "CB-1201",
                      tie_capacity_kw={TIE: 2000.0}, as_of=AS_OF)
    assert reasons(plan) == [(TIE, "FAULTED_SECTION")]
    assert plan.deprecations == ["tie_capacity_kw"]


# ---------------------------------------------------------- REQ-TIECAP-10 / 11: per tie, order


BLOCKING_ENTRIES = {
    "missing": None,
    "bad": cap(150.0, quality="BAD"),
    "stale": cap(150.0, age_ms=25_000),
    "nan": cap(math.nan),
    "exceeded": cap(149.4),
}


@pytest.mark.requirement("REQ-TIECAP-10")
@pytest.mark.parametrize("blocking", BLOCKING_ENTRIES.values(), ids=BLOCKING_ENTRIES)
def test_req_tiecap_10_blocked_tie_does_not_change_the_rest_of_the_plan(blocking):
    capacities = {"TIE-T1": cap(300.0)}
    if blocking is not None:
        capacities["TIE-T2"] = blocking
    plan = assert_matches_oracle(two_tie_feeder(), "CB-T", capacities)
    reference = build_plan(two_tie_feeder(), "CB-T",
                           tie_capacity={"TIE-T1": cap(300.0), "TIE-T2": cap(149.4)}, as_of=AS_OF)
    assert plan.isolation == reference.isolation
    assert plan.restoration == reference.restoration
    assert closed_ties(plan, "CB-T") == ["TIE-T1"]
    assert [b.tie_id for b in plan.blocked_ties] == ["TIE-T2"]
    assert (plan.customers_restored, plan.customers_remaining, plan.transferred_load_kw) == (
        reference.customers_restored, reference.customers_remaining,
        reference.transferred_load_kw,
    )


@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.requirement("REQ-TIECAP-12")
@pytest.mark.requirement("REQ-TIECAP-18")
def test_req_tiecap_11_blocked_ties_in_switch_order_with_held_and_capacity_blocked():
    feeder = two_tie_feeder(held_tie=True)
    capacities = {"TIE-T1": cap(299.4), "TIE-H": cap(10_000.0)}
    plan = assert_matches_oracle(feeder, "CB-T", capacities)
    assert reasons(plan) == [
        ("TIE-T1", "CAPACITY_EXCEEDED"),
        ("TIE-H", "FAULTED_SECTION"),
        ("TIE-T2", "CAPACITY_UNKNOWN"),
    ]
    assert closed_ties(plan, "CB-T") == []
    # Faulted SEC-B (50) + TIE-T1 SEC-C (30) + TIE-H's healthy SEC-E (10) + TIE-T2 SEC-D (20).
    assert (plan.customers_restored, plan.customers_remaining) == (0, 110)
    assert plan.notes == [
        "TIE-T1 name blocked (CAPACITY_EXCEEDED): 300.0 kW to transfer exceeds 299.4 kW "
        "available capacity (+0.5 kW tolerance)",
        "TIE-H name (TIE-H) held open: would back-feed faulted section SEC-B (SEC-B)",
        "TIE-T2 name blocked (CAPACITY_UNKNOWN): no capacity value",
    ]


# ---------------------------------------------------------------- REQ-TIECAP-12: notes


@pytest.mark.requirement("REQ-TIECAP-12")
def test_req_tiecap_12_exceeded_note_states_load_and_capacity():
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity={TIE: cap(1489.4)},
                      as_of=AS_OF)
    assert plan.notes == [
        f"{TIE_NAME} blocked (CAPACITY_EXCEEDED): 1490.0 kW to transfer exceeds 1489.4 kW "
        "available capacity (+0.5 kW tolerance)"
    ]


@pytest.mark.requirement("REQ-TIECAP-12")
def test_req_tiecap_12_one_note_per_blocked_tie():
    feeder = two_tie_feeder()
    plan = build_plan(feeder, "CB-T", tie_capacity={"TIE-T1": cap(age_ms=21_500)}, as_of=AS_OF)
    assert reasons(plan) == [("TIE-T1", "CAPACITY_STALE"), ("TIE-T2", "CAPACITY_UNKNOWN")]
    assert plan.notes == [
        "TIE-T1 name blocked (CAPACITY_STALE): capacity value is 21.500 s old (limit 20 s)",
        "TIE-T2 name blocked (CAPACITY_UNKNOWN): no capacity value",
    ]


# ---------------------------------------------------------------- REQ-TIECAP-15 / 16: legacy map


@pytest.mark.requirement("REQ-TIECAP-15")
@pytest.mark.parametrize(
    ("new", "legacy"), [({}, {}), ({TIE: cap()}, {TIE: 2000.0})], ids=["both-empty", "both-set"]
)
def test_req_tiecap_15_both_maps_raise(new, legacy):
    with pytest.raises(ValueError, match="mutually exclusive"):
        build_plan(cedar_ridge_in_lockout(), "CB-1201", legacy, tie_capacity=new, as_of=AS_OF)


@pytest.mark.requirement("REQ-TIECAP-16")
@pytest.mark.parametrize("capacity_kw", [2000.0, 1490.0, 1489.5, 1489.4, 0.0])
def test_req_tiecap_16_legacy_map_matches_good_entry_at_as_of(capacity_kw):
    legacy = build_plan(cedar_ridge_in_lockout(), "CB-1201", {TIE: capacity_kw}, as_of=AS_OF)
    new = build_plan(cedar_ridge_in_lockout(), "CB-1201",
                     tie_capacity={TIE: TieCapacity(kw=capacity_kw, timestamp=AS_OF,
                                                    quality="GOOD")}, as_of=AS_OF)
    assert legacy.model_dump(exclude={"deprecations"}) == new.model_dump(exclude={"deprecations"})
    assert legacy.deprecations == ["tie_capacity_kw"]
    assert new.deprecations == []


@pytest.mark.requirement("REQ-TIECAP-16")
@pytest.mark.parametrize(
    ("legacy", "expected"),
    [({}, "CAPACITY_UNKNOWN"), ({"TIE-ELSEWHERE": 2000.0}, "CAPACITY_UNKNOWN"),
     ({TIE: math.nan}, "CAPACITY_INVALID"), ({TIE: math.inf}, "CAPACITY_INVALID"),
     ({TIE: -math.inf}, "CAPACITY_INVALID"), ({TIE: -1.0}, "CAPACITY_INVALID"),
     ({TIE: "2000"}, "CAPACITY_INVALID")],
)
def test_req_tiecap_16_legacy_missing_or_invalid_values(legacy, expected):
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity_kw=legacy, as_of=AS_OF)
    assert reasons(plan) == [(TIE, expected)]
    assert plan.deprecations == ["tie_capacity_kw"]


@pytest.mark.requirement("REQ-TIECAP-16")
def test_req_tiecap_16_no_legacy_map_no_deprecation():
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", as_of=AS_OF)
    assert plan.deprecations == []
    assert reasons(plan) == [(TIE, "CAPACITY_UNKNOWN")]


# ---------------------------------------------------------------- REQ-TIECAP-18: accounting


@pytest.mark.requirement("REQ-TIECAP-18")
@pytest.mark.parametrize(("c1", "c2"), [(300.0, 150.0), (300.0, None), (None, 150.0), (None, None)])
def test_req_tiecap_18_blocked_ties_add_only_to_customers_remaining(c1, c2):
    capacities = {k: cap(v) for k, v in (("TIE-T1", c1), ("TIE-T2", c2)) if v is not None}
    plan = assert_matches_oracle(two_tie_feeder(), "CB-T", capacities)
    restored = (30 if c1 else 0) + (20 if c2 else 0)
    assert plan.customers_restored == restored
    assert plan.customers_remaining == 50 + (50 - restored)
    assert plan.transferred_load_kw == (300.0 if c1 else 0.0) + (150.0 if c2 else 0.0)


# ---------------------------------------------------------------- Q-DESIGN-2: invalid section load


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.parametrize("load_kw", [math.nan, math.inf, -math.inf, -120.0, -1e-9])
@pytest.mark.parametrize(
    "capacities", [{}, {TIE: cap(0.0)}, {TIE: cap(2000.0)}], ids=["missing", "good-0", "good-2000"]
)
def test_req_tiecap_3_invalid_section_load_refuses_the_plan(load_kw, capacities):
    feeder = cedar_ridge_in_lockout()
    section_named(feeder, "SEC-1201-04").load_kw = load_kw
    assert not oracle_sections_ok(feeder, {"N-1201-3A", "N-1201-4", "ALT-1405"})
    with pytest.raises(FlisrError, match="Hollow Creek tail: load_kw .* no plan"):
        build_plan(feeder, "CB-1201", tie_capacity=capacities, as_of=AS_OF)


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.parametrize("capacity_kw", [1000.0, 2000.0])
def test_req_tiecap_3_negative_spur_inside_positive_total_refuses_the_plan(capacity_kw):
    feeder = cedar_ridge_in_lockout()
    feeder.sections.append(_section("SPUR", "N-1201-4", "N-1201-5", 10, -600.0))
    nodes = oracle_candidate_nodes(feeder, TIE, {"SEC-SW-1201-1", "REC-1201-2"})
    assert oracle_load_kw(feeder, nodes) == 890.0 and oracle_l_in_range(890.0)
    assert not oracle_sections_ok(feeder, nodes)
    with pytest.raises(FlisrError, match="SPUR: load_kw -600.0 kW"):
        build_plan(feeder, "CB-1201", tie_capacity={TIE: cap(capacity_kw)}, as_of=AS_OF)


@pytest.mark.requirement("REQ-TIECAP-9")
@pytest.mark.parametrize("load_kw", [math.nan, math.inf, -math.inf, -120.0])
def test_req_tiecap_9_held_tie_with_invalid_load_refuses_the_plan(load_kw):
    feeder = cedar_ridge_faulted_on_sec_1201_04()
    section_named(feeder, "SEC-1201-04").load_kw = load_kw
    with pytest.raises(FlisrError, match="no plan"):
        build_plan(feeder, "CB-1201", tie_capacity={TIE: cap()}, as_of=AS_OF)


@pytest.mark.requirement("REQ-TIECAP-3")
def test_req_tiecap_3_overflowing_transferred_load_refuses_the_plan():
    feeder = cedar_ridge_in_lockout()
    section_named(feeder, "SEC-1201-04").load_kw = 1e308
    feeder.sections.append(_section("SPUR", "N-1201-4", "N-1201-5", 10, 1e308))
    assert not oracle_l_in_range(1e308 + 1e308)
    with pytest.raises(FlisrError, match="transferred load inf kW"):
        build_plan(feeder, "CB-1201", tie_capacity={TIE: cap(math.inf)}, as_of=AS_OF)


# ---------------------------------------------------------- tie_capacity_verdict preconditions


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.parametrize("load_kw", [math.nan, math.inf, -math.inf, -120.0, -1e-9, True, "1"])
def test_req_tiecap_3_verdict_refuses_out_of_range_load(load_kw):
    with pytest.raises(ValueError, match="transferred load"):
        tie_capacity_verdict(cap(), load_kw, AS_OF)


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.parametrize("load_kw", [0.0, -0.0, 0])
def test_req_tiecap_3_verdict_accepts_zero_load(load_kw):
    assert tie_capacity_verdict(cap(0.0), load_kw, AS_OF) is None


@pytest.mark.requirement("REQ-TIECAP-2")
@pytest.mark.parametrize(
    "as_of",
    [datetime(2026, 10, 15, 22), "2026-10-15T22:00:00Z", None],
    ids=["naive", "str", "none"],
)
def test_req_tiecap_2_verdict_refuses_naive_or_non_datetime_as_of(as_of):
    with pytest.raises(ValueError, match="as_of"):
        tie_capacity_verdict(cap(), 1490.0, as_of)


@pytest.mark.requirement("REQ-TIECAP-8")
def test_req_tiecap_8_verdict_refuses_naive_entry_timestamp_and_wrong_type():
    naive = TieCapacity.model_construct(kw=2000.0, timestamp=datetime(2026, 10, 15, 22),
                                        quality="GOOD")
    with pytest.raises(ValueError, match="timestamp"):
        tie_capacity_verdict(naive, 1490.0, AS_OF)
    with pytest.raises(ValueError, match="TieCapacity"):
        tie_capacity_verdict({"kw": 2000.0, "timestamp": AS_OF, "quality": "GOOD"}, 1490.0, AS_OF)
    with pytest.raises(ValueError, match="TieCapacity"):
        build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity={TIE: 2000.0}, as_of=AS_OF)
    assert tie_capacity_verdict(None, 1490.0, AS_OF).value == "CAPACITY_UNKNOWN"


# ---------------------------------------------------------------- P2: one production source


P2_FUNCTIONS = {
    "flisr.py": ["tie_capacity_verdict", "_not_finite_nonneg", "_blocked_note",
                 "_legacy_to_tie_capacity"],
    "api.py": ["_check_as_of_bound", "_flisr_plan_description"],
}


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.requirement("REQ-TIECAP-12")
@pytest.mark.requirement("REQ-TIECAP-23")
def test_req_tiecap_3_production_threshold_code_restates_no_literal():
    """P2 (design 6.3): thresholds come only from models.py constants."""
    for filename, names in P2_FUNCTIONS.items():
        tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in names:
            assert name in functions, f"{filename}:{name} missing"
            for node in ast.walk(functions[name]):
                if isinstance(node, ast.Constant):
                    value = node.value
                    if isinstance(value, int | float) and not isinstance(value, bool):
                        assert value == 0, f"{filename}:{name} restates {value!r}"
                    assert value != "GOOD", f"{filename}:{name} restates 'GOOD'"
                if isinstance(node, ast.Call):
                    assert "timedelta" not in ast.unparse(node.func), f"{filename}:{name}"
