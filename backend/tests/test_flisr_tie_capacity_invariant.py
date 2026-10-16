"""REQ-TIECAP-21 safety invariant over seeded generated feeders (STD-SAFETY-5).

Invariant (REQ-TIECAP-21, amended by Q-DESIGN-3): no plan contains a `close` step for a tie
unless that tie is not held by the DEF-FLISR-7 guard, its capacity is usable and
L <= C + 0.5 kW; every candidate tie not closed appears exactly once in `blocked_ties` with
the reason FAULTED_SECTION > CAPACITY_INVALID > CAPACITY_UNKNOWN > CAPACITY_STALE >
CAPACITY_EXCEEDED gives. Preconditions (Q-DESIGN-2): an invalid load in any candidate tie's
pick-up set, or an out-of-range L for a tie not held, means FlisrError and no plan.

The oracle_* functions restate the specification (section 0 definitions, REQ-TIECAP-3..9,
18) with its literals. They do not import app.flisr, app.network or the models.py threshold
constants (design 6.3, O1, checked below); app.models types are read as plain data only.
Fault location and isolation are restated as today's rules so the oracle can predict a
refusal when no plan is returned; they are oracle inputs, not claims of this test (spec
section 3 keeps locate_fault and _isolation_switches out of scope).
"""

from __future__ import annotations

import ast
import math
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.flisr import FlisrError, build_plan
from app.models import Feeder, Section, Switch, SwitchKind, TieCapacity

pytestmark = pytest.mark.requirement("REQ-TIECAP-21")

INVARIANT_SEED = 20261016
INVARIANT_CASES = 1000
LOCKOUT = "CB"
BASE_AS_OF = datetime(2026, 10, 15, 22, 0, 0, tzinfo=UTC)
OFFSETS = [UTC, timezone(timedelta(hours=2)), timezone(timedelta(hours=-5, minutes=-30))]


# ---------------------------------------------------------------- independent oracle


def oracle_faulted_section(feeder: Feeder) -> str | None:
    """Today's rule: the section after the last indicated one in list order."""
    indicated = [i for i, s in enumerate(feeder.sections) if s.fault_indicator]
    if not indicated:
        return None
    last = indicated[-1]
    return feeder.sections[min(last + 1, len(feeder.sections) - 1)].mrid


def oracle_isolation(feeder: Feeder, faulted_mrid: str) -> set[str]:
    """Today's rule: SCADA non-tie switches touching the faulted section's endpoints."""
    faulted = next(s for s in feeder.sections if s.mrid == faulted_mrid)
    return {
        w.mrid for w in feeder.switches
        if w.scada_controllable and w.kind != SwitchKind.TIE
        and (w.to_node == faulted.from_node or w.from_node == faulted.to_node)
    }


def oracle_bfs(feeder: Feeder, start: str, opened: set[str], closed: str) -> set[str]:
    graph: dict[str, list[str]] = defaultdict(list)
    for s in feeder.sections:
        graph[s.from_node].append(s.to_node)
        graph[s.to_node].append(s.from_node)
    for w in feeder.switches:
        if w.mrid == closed or not (w.open or w.mrid in opened):
            graph[w.from_node].append(w.to_node)
            graph[w.to_node].append(w.from_node)
    seen = {start}
    frontier = [start]
    while frontier:
        nxt = []
        for node in frontier:
            for other in graph[node]:
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    return seen


def oracle_candidate_nodes(feeder: Feeder, tie_mrid: str, opened: set[str]) -> set[str]:
    """Spec 'Candidate tie': nodes reachable from the tie with isolation open and the tie
    closed, minus nodes the feeder's own source still reaches."""
    tie = next(w for w in feeder.switches if w.mrid == tie_mrid)
    return (oracle_bfs(feeder, tie.from_node, opened, tie_mrid)
            - oracle_bfs(feeder, feeder.source_node, opened, tie_mrid))


def oracle_load_kw(feeder: Feeder, nodes: set[str]) -> float:
    return sum(s.load_kw for s in feeder.sections if s.to_node in nodes)


def oracle_customers(feeder: Feeder, nodes: set[str], except_mrid: str | None = None) -> int:
    return sum(s.customers for s in feeder.sections
               if s.to_node in nodes and s.mrid != except_mrid)


def oracle_sections_ok(feeder: Feeder, nodes: set[str]) -> bool:
    return all(math.isfinite(s.load_kw) and s.load_kw >= 0
               for s in feeder.sections if s.to_node in nodes)


def oracle_l_in_range(load_kw: float) -> bool:
    return math.isfinite(load_kw) and load_kw >= 0


def oracle_held(feeder: Feeder, nodes: set[str], faulted_mrid: str) -> bool:
    faulted = next(s for s in feeder.sections if s.mrid == faulted_mrid)
    return faulted.from_node in nodes or faulted.to_node in nodes


def oracle_usable(entry, as_of: datetime) -> bool:
    """Spec 'Usable capacity': present, valid, quality GOOD, age <= 20 s."""
    if entry is None:
        return False
    age = as_of - entry.timestamp
    valid = math.isfinite(entry.kw) and entry.kw >= 0 and age >= timedelta(seconds=-2)
    return valid and entry.quality == "GOOD" and age <= timedelta(seconds=20)


def oracle_reason(entry, load_kw: float, as_of: datetime) -> str | None:
    """REQ-TIECAP-9 precedence as a first-true list; None means the tie closes."""
    if entry is None:
        return "CAPACITY_UNKNOWN"
    age = as_of - entry.timestamp
    conditions = [
        ("CAPACITY_INVALID",
         not (math.isfinite(entry.kw) and entry.kw >= 0) or age < timedelta(seconds=-2)),
        ("CAPACITY_UNKNOWN", entry.quality != "GOOD"),
        ("CAPACITY_STALE", age > timedelta(seconds=20)),
        ("CAPACITY_EXCEEDED", not load_kw <= entry.kw + 0.5),
    ]
    return next((reason for reason, applies in conditions if applies), None)


def oracle_expected(feeder: Feeder, capacities: dict, as_of: datetime) -> dict:
    """Expected outcome of build_plan: {'refused': True} or the per-tie decisions."""
    faulted = oracle_faulted_section(feeder)
    opened = oracle_isolation(feeder, faulted)
    ties = []
    refused = False
    for w in feeder.switches:
        if w.kind != SwitchKind.TIE or not w.scada_controllable:
            continue
        nodes = oracle_candidate_nodes(feeder, w.mrid, opened)
        if not nodes:
            continue
        held = oracle_held(feeder, nodes, faulted)
        load_kw = oracle_load_kw(feeder, nodes)
        if not oracle_sections_ok(feeder, nodes) or (not held and not oracle_l_in_range(load_kw)):
            refused = True
        entry = capacities.get(w.mrid)
        reason = "FAULTED_SECTION" if held else (
            oracle_reason(entry, load_kw, as_of) if oracle_l_in_range(load_kw) else None)
        ties.append({"tie": w.mrid, "nodes": nodes, "held": held, "load_kw": load_kw,
                     "entry": entry, "reason": reason})
    restored = 0
    remaining = next(s.customers for s in feeder.sections if s.mrid == faulted)
    transferred = 0.0
    for t in ties:
        if t["reason"] is None:
            restored += oracle_customers(feeder, t["nodes"])
            transferred += t["load_kw"]
        elif t["reason"] == "FAULTED_SECTION":
            remaining += oracle_customers(feeder, t["nodes"], except_mrid=faulted)
        else:
            remaining += oracle_customers(feeder, t["nodes"])
    return {"refused": refused, "faulted": faulted, "isolation": opened, "ties": ties,
            "customers_restored": restored, "customers_remaining": remaining,
            "transferred_load_kw": transferred}


# ---------------------------------------------------------------- seeded generator


def _feeder(rng: random.Random) -> tuple[Feeder, bool]:
    """Radial or branched feeder, 2-10 sections, sections listed parent-first; 1-4 ties on
    any node, about 40 % of cases with one tie on an endpoint of the faulted section."""
    n = rng.randint(2, 10)
    branched = rng.random() < 0.5
    sections: list[Section] = []
    switches = [Switch(mrid=LOCKOUT, name="CB", kind=SwitchKind.BREAKER, open=True,
                       from_node="SRC", to_node="BUS")]
    for i in range(n):
        start = "BUS" if i == 0 else f"N{i}A"
        if i > 0:
            parent = rng.randrange(i) if branched else i - 1
            switches.append(Switch(
                mrid=f"SW{i}", name=f"SW{i}",
                kind=rng.choice([SwitchKind.RECLOSER, SwitchKind.SECTIONALIZER]),
                from_node=f"N{parent}", to_node=start))
        sections.append(Section(mrid=f"S{i}", name=f"S{i}", from_node=start, to_node=f"N{i}",
                                customers=rng.randint(0, 500),
                                load_kw=rng.randint(0, 8000) / 4))
    faulted = rng.randrange(1, n)
    for section in sections[:faulted]:
        section.fault_indicator = True
    nodes = sorted({s.from_node for s in sections} | {s.to_node for s in sections})
    tie_nodes = [rng.choice(nodes) for _ in range(rng.randint(1, 4))]
    if rng.random() < 0.4:
        tie_nodes[rng.randrange(len(tie_nodes))] = rng.choice(
            [sections[faulted].from_node, sections[faulted].to_node])
    for t, node in enumerate(tie_nodes):
        switches.append(Switch(mrid=f"TIE{t}", name=f"TIE{t}", kind=SwitchKind.TIE,
                               normal_open=True, open=True, from_node=node, to_node=f"ALT{t}",
                               scada_controllable=rng.random() < 0.9))
    rng.shuffle(switches)
    return Feeder(mrid="F", name="F", substation="SUB", nominal_kv=12.47, rating_amps=600.0,
                  source_node="SRC", sections=sections, switches=switches), branched


def _inject_load_defect(rng: random.Random, feeder: Feeder) -> str:
    """Mutates section loads for the precondition cases; returns the mode name."""
    mode = rng.choices(["valid", "non_finite", "negative_total", "negative_inside",
                        "overflow", "faulted_invalid"], [64, 6, 4, 14, 4, 8])[0]
    sections = feeder.sections
    if mode == "non_finite":
        rng.choice(sections).load_kw = rng.choice([math.nan, math.inf, -math.inf])
    elif mode == "negative_total":
        rng.choice(sections).load_kw = -1.0e6
    elif mode == "negative_inside":
        for s in sections:
            s.load_kw += 700.0
        rng.choice(sections).load_kw = -rng.choice([1e-9, 0.25, 120.0, 600.0])
    elif mode == "overflow":
        for s in sections:
            s.load_kw = 1.5e308
    elif mode == "faulted_invalid":
        faulted = oracle_faulted_section(feeder)
        next(s for s in sections if s.mrid == faulted).load_kw = rng.choice(
            [math.nan, math.inf, -math.inf, -120.0])
    return mode


_AGES_MS = [0, 5_000, 19_999, 20_000, 20_001, 45_000, 300_000, -1_999, -2_000, -2_001, -30_000]


def _capacity_for(rng: random.Random, load_kw: float, as_of: datetime) -> TieCapacity:
    finite_l = load_kw if math.isfinite(load_kw) and load_kw >= 0 else 1000.0
    kw = rng.choice([
        finite_l - 0.5, finite_l - 0.5, finite_l - 0.4, finite_l - 0.6, finite_l,
        finite_l + rng.randint(1, 3000), rng.randint(0, 24000) / 4, 0.0, -0.0,
        math.nan, math.inf, -math.inf, -1e-9, -100.0,
    ])
    age_ms = rng.choice(_AGES_MS) if rng.random() < 0.6 else rng.randint(-1_999, 20_000)
    quality = rng.choices(["GOOD", "BAD", "SUSPECT", "good", ""], [70, 8, 8, 7, 7])[0]
    timestamp = (as_of - timedelta(milliseconds=age_ms)).astimezone(rng.choice(OFFSETS))
    return TieCapacity(kw=kw, timestamp=timestamp, quality=quality)


def _case(rng: random.Random):
    feeder, branched = _feeder(rng)
    mode = _inject_load_defect(rng, feeder)
    as_of = (BASE_AS_OF + timedelta(milliseconds=rng.randint(0, 86_400_000))).astimezone(
        rng.choice(OFFSETS))
    preview = oracle_expected(feeder, {}, as_of)
    capacity_mode = rng.choices(["tie_capacity", "legacy", "none", "empty"], [80, 12, 4, 4])[0]
    capacities: dict[str, TieCapacity] = {}
    kwargs: dict = {"as_of": as_of}
    if capacity_mode in ("tie_capacity", "legacy"):
        for t in preview["ties"]:
            if rng.random() < 0.12:
                continue
            capacities[t["tie"]] = _capacity_for(rng, t["load_kw"], as_of)
        if rng.random() < 0.1:
            capacities["TIE-NOT-ON-FEEDER"] = _capacity_for(rng, 0.0, as_of)
    if capacity_mode == "tie_capacity":
        kwargs["tie_capacity"] = capacities
    elif capacity_mode == "legacy":
        kwargs["tie_capacity_kw"] = {k: v.kw for k, v in capacities.items()}
        capacities = {k: TieCapacity(kw=v.kw, timestamp=as_of, quality="GOOD")
                      for k, v in capacities.items()}
    elif capacity_mode == "empty":
        kwargs["tie_capacity"] = {}
    return feeder, branched, mode, capacity_mode, capacities, as_of, kwargs


def _check_case(feeder, capacities, as_of, kwargs, stats: Counter, lockout=LOCKOUT) -> list[str]:
    expected = oracle_expected(feeder, capacities, as_of)
    try:
        plan = build_plan(feeder.model_copy(deep=True), lockout, **kwargs)
    except FlisrError as error:
        if expected["refused"]:
            stats["refused"] += 1
            return []
        return [f"unexpected FlisrError: {error}"]
    if expected["refused"]:
        return [f"plan returned although the oracle refuses: {plan.restoration}"]
    problems = []
    if plan.faulted_section != expected["faulted"] or (
            {s.switch_mrid for s in plan.isolation} != expected["isolation"]):
        return ["oracle precondition: fault location / isolation differ from today's rules"]
    closes = [s.switch_mrid for s in plan.restoration
              if s.action == "close" and s.switch_mrid != lockout]
    blocked = [(b.tie_id, b.reason.value) for b in plan.blocked_ties]
    by_tie = {t["tie"]: t for t in expected["ties"]}
    for tie_id in closes:
        t = by_tie.get(tie_id)
        if t is None:
            problems.append(f"{tie_id} closed but is not a candidate tie")
            continue
        if t["held"] or not oracle_usable(t["entry"], as_of) or not (
                t["load_kw"] <= t["entry"].kw + 0.5):
            problems.append(f"{tie_id} closed without usable capacity and L <= C + 0.5: {t}")
    if len(closes) != len(set(closes)):
        problems.append(f"duplicate close steps {closes}")
    expected_blocked = [(t["tie"], t["reason"]) for t in expected["ties"] if t["reason"]]
    if blocked != expected_blocked:
        problems.append(f"blocked_ties {blocked} != oracle {expected_blocked}")
    expected_closes = [t["tie"] for t in expected["ties"] if t["reason"] is None]
    if closes != expected_closes:
        problems.append(f"closes {closes} != oracle {expected_closes}")
    not_closed = {t["tie"] for t in expected["ties"]} - set(closes)
    if Counter(tie for tie, _ in blocked) != Counter(not_closed):
        problems.append(f"candidate ties not closed {sorted(not_closed)} vs blocked {blocked}")
    if (plan.customers_restored, plan.customers_remaining) != (
            expected["customers_restored"], expected["customers_remaining"]):
        problems.append("customer accounting differs from oracle (REQ-TIECAP-18)")
    if not math.isclose(plan.transferred_load_kw, expected["transferred_load_kw"],
                        rel_tol=1e-12, abs_tol=1e-9):
        problems.append("transferred_load_kw differs from oracle")
    for t in expected["ties"]:
        stats[t["reason"] or "CLOSED"] += 1
        if t["reason"] is None and t["entry"].kw < t["load_kw"]:
            stats["closed_within_tolerance"] += 1
            if t["load_kw"] == t["entry"].kw + 0.5:
                stats["closed_at_L_eq_C_plus_tol"] += 1
    if expected_closes and expected_blocked:
        stats["plans_with_closed_and_blocked_ties"] += 1
    if len(expected["ties"]) > 1:
        stats["plans_with_several_candidate_ties"] += 1
    return problems


def _case_kinds(feeder: Feeder, as_of: datetime) -> set[str]:
    """Which precondition / hold classes a case exercises, judged on the oracle's own L."""
    expected = oracle_expected(feeder, {}, as_of)
    kinds = set()
    for t in expected["ties"]:
        sections_ok = oracle_sections_ok(feeder, t["nodes"])
        if not oracle_l_in_range(t["load_kw"]):
            kinds.add("out_of_range_L")
        elif not sections_ok:
            kinds.add("negative_section_inside_positive_L")
        if t["held"]:
            kinds.add("held_tie_invalid_load" if not sections_ok else "held_tie")
    return kinds


@pytest.mark.requirement("REQ-TIECAP-21")
def test_req_tiecap_21_no_tie_closed_without_usable_capacity_over_seeded_feeders():
    rng = random.Random(INVARIANT_SEED)
    stats: Counter = Counter()
    violations = []
    for case in range(INVARIANT_CASES):
        feeder, branched, mode, capacity_mode, capacities, as_of, kwargs = _case(rng)
        stats["branched" if branched else "radial"] += 1
        stats[f"load_mode={mode}"] += 1
        stats[f"capacity_mode={capacity_mode}"] += 1
        for kind in _case_kinds(feeder, as_of):
            stats[f"cases_{kind}"] += 1
        problems = _check_case(feeder, capacities, as_of, kwargs, stats)
        if problems:
            violations.append((case, problems))
    print(f"\nREQ-TIECAP-21 invariant: seed={INVARIANT_SEED} cases={INVARIANT_CASES} "
          f"violations={len(violations)}")
    for key in sorted(stats):
        print(f"  {key}: {stats[key]}")

    assert not violations, f"{len(violations)}/{INVARIANT_CASES} cases: {violations[:5]}"
    five_percent = INVARIANT_CASES // 20
    for kind in ("out_of_range_L", "negative_section_inside_positive_L", "held_tie",
                 "held_tie_invalid_load"):
        assert stats[f"cases_{kind}"] >= five_percent, f"generator: {kind} {stats}"
    assert stats["radial"] >= five_percent and stats["branched"] >= five_percent
    for reason in ("CLOSED", "FAULTED_SECTION", "CAPACITY_INVALID", "CAPACITY_UNKNOWN",
                   "CAPACITY_STALE", "CAPACITY_EXCEEDED", "closed_within_tolerance",
                   "closed_at_L_eq_C_plus_tol", "plans_with_closed_and_blocked_ties", "refused"):
        assert stats[reason] >= 20, f"generator exercised {reason} only {stats[reason]} times"


# ---------------------------------------------------------------- oracle self-checks (O1)


def _hollow_creek() -> Feeder:
    from app.network import get_feeder, load_network

    feeder = get_feeder(load_network(), "FDR-1201")
    next(w for w in feeder.switches if w.mrid == "CB-1201").open = True
    return feeder


@pytest.mark.requirement("REQ-TIECAP-21")
def test_req_tiecap_21_oracle_reproduces_shipped_model_hand_values():
    feeder = _hollow_creek()
    as_of = BASE_AS_OF
    entry = TieCapacity(kw=1489.5, timestamp=as_of - timedelta(seconds=20), quality="GOOD")
    expected = oracle_expected(feeder, {"TIE-1201-1405": entry}, as_of)
    (tie,) = expected["ties"]
    assert expected["faulted"] == "SEC-1201-03"
    assert expected["isolation"] == {"SEC-SW-1201-1", "REC-1201-2"}
    assert (tie["load_kw"], oracle_customers(feeder, tie["nodes"])) == (1490.0, 341)
    assert tie["reason"] is None and not tie["held"]
    assert oracle_reason(entry.model_copy(update={"kw": 1489.4}), 1490.0, as_of) == (
        "CAPACITY_EXCEEDED")
    stale = entry.model_copy(update={"timestamp": as_of - timedelta(seconds=20, microseconds=1)})
    assert oracle_reason(stale, 1490.0, as_of) == "CAPACITY_STALE"
    bad_stale_nan = stale.model_copy(update={"kw": math.nan, "quality": "BAD"})
    assert oracle_reason(bad_stale_nan, 1490.0, as_of) == "CAPACITY_INVALID"
    assert oracle_reason(stale.model_copy(update={"quality": "BAD"}), 1490.0, as_of) == (
        "CAPACITY_UNKNOWN")


@pytest.mark.requirement("REQ-TIECAP-21")
def test_req_tiecap_21_plan_on_shipped_model_matches_oracle():
    feeder = _hollow_creek()
    entry = TieCapacity(kw=1489.5, timestamp=BASE_AS_OF, quality="GOOD")
    assert _check_case(feeder, {"TIE-1201-1405": entry}, BASE_AS_OF,
                       {"tie_capacity": {"TIE-1201-1405": entry}, "as_of": BASE_AS_OF},
                       Counter(), lockout="CB-1201") == []


def _forbidden_oracle_refs(source: str) -> list[str]:
    """O1 (design 6.3): oracle_* functions reach no app.flisr / app.network name and no
    TIE_CAPACITY_* / AS_OF_* constant, through any import form or alias."""
    tree = ast.parse(source)
    logic_names: set[str] = set()
    logic_aliases: set[str] = set()
    threshold_aliases: set[str] = set()

    def threshold(name: str) -> bool:
        return name.startswith(("TIE_CAPACITY_", "AS_OF_"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("app.flisr", "app.network"):
            logic_names |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module == "app.models":
            threshold_aliases |= {a.asname or a.name for a in node.names if threshold(a.name)}
        elif isinstance(node, ast.ImportFrom) and node.module == "app":
            logic_aliases |= {a.asname or a.name for a in node.names
                              if a.name in ("flisr", "network")}
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name in ("app.flisr", "app.network"):
                    logic_aliases.add(a.asname or a.name)
    found = []
    for func in ast.walk(tree):
        if not (isinstance(func, ast.FunctionDef) and func.name.startswith("oracle_")):
            continue
        for node in ast.walk(func):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                found.append(f"{func.name}: import inside oracle")
            forbidden = logic_names | logic_aliases | threshold_aliases
            if isinstance(node, ast.Name) and (node.id in forbidden or threshold(node.id)):
                found.append(f"{func.name}: {node.id}")
            if isinstance(node, ast.Attribute) and (
                    threshold(node.attr)
                    or ast.unparse(node.value).split(".")[0] in logic_aliases
                    or ast.unparse(node.value).startswith(("app.flisr", "app.network"))):
                found.append(f"{func.name}: {ast.unparse(node)}")
    return found


@pytest.mark.requirement("REQ-TIECAP-21")
def test_req_tiecap_21_oracle_is_independent_of_production_code():
    assert _forbidden_oracle_refs(Path(__file__).read_text(encoding="utf-8")) == []


@pytest.mark.requirement("REQ-TIECAP-21")
def test_req_tiecap_21_oracle_independence_check_detects_violations():
    bad = (
        "from app.flisr import tie_capacity_verdict\n"
        "from app import network as nw\n"
        "import app.models as m\n"
        "from app.models import TIE_CAPACITY_TOLERANCE_KW as tol\n"
        "def oracle_a(e, L, t):\n    return tie_capacity_verdict(e, L, t)\n"
        "def oracle_b(f):\n    return nw.energised_nodes(f)\n"
        "def oracle_c(L, C):\n    return L <= C + m.TIE_CAPACITY_TOLERANCE_KW\n"
        "def oracle_d(L, C):\n    return L <= C + tol\n"
        "def oracle_e():\n    from app import flisr\n    return flisr\n"
    )
    found = _forbidden_oracle_refs(bad)
    for name in ("oracle_a", "oracle_b", "oracle_c", "oracle_d", "oracle_e"):
        assert any(item.startswith(name) for item in found), (name, found)
