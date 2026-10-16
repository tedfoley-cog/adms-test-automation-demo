"""Independent QA of U4 (REQ-TIECAP-21): the seeded tie-capacity safety invariant.

QA re-tests the invariant with its own oracle and its own generator, and then tests the
Coding unit's test itself: does ``test_flisr_tie_capacity_invariant.py`` fail when the planner
is broken in each of the ways the specification forbids?

The ``oracle_*`` functions restate the specification literals (0.5 kW, 20 s, -2 s, "GOOD")
and run their own breadth-first search over the test topology; they import nothing from
``app.flisr`` or ``app.network`` and use none of the ``models.py`` threshold constants
(design 6.3, Q-DESIGN-1). ``build_plan`` is imported only as the subject under test.
Tolerance 0.5 kW engineering units; per-unit statement waived by Q-SPEC-4 (STD-SAFETY-6).
"""

from __future__ import annotations

import ast
import importlib.util
import math
import random
import types
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.flisr import FlisrError, build_plan
from app.models import Feeder, Section, Switch, SwitchKind, TieCapacity

pytestmark = pytest.mark.requirement("REQ-TIECAP-21")

QA_SEED = 7_041_016
QA_CASES = 800
QA_AS_OF = datetime(2026, 10, 16, 1, 30, 0, tzinfo=UTC)
QA_OFFSETS = [UTC, timezone(timedelta(hours=10)), timezone(timedelta(hours=-3, minutes=-30))]
TESTS_DIR = Path(__file__).resolve().parent
U4_FILE = TESTS_DIR / "test_flisr_tie_capacity_invariant.py"
FLISR_SRC = TESTS_DIR.parent / "app" / "flisr.py"

# ---------------------------------------------------------------- QA oracle (spec literals)


def oracle_graph(feeder: Feeder, opened: set[str], closed: set[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for s in feeder.sections:
        graph.setdefault(s.from_node, set()).add(s.to_node)
        graph.setdefault(s.to_node, set()).add(s.from_node)
    for w in feeder.switches:
        is_open = (w.open or w.mrid in opened) and w.mrid not in closed
        if is_open:
            continue
        graph.setdefault(w.from_node, set()).add(w.to_node)
        graph.setdefault(w.to_node, set()).add(w.from_node)
    return graph


def oracle_reach(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    queue = [start]
    while queue:
        node = queue.pop()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(graph.get(node, ()))
    return seen


def oracle_faulted(feeder: Feeder) -> Section | None:
    """Today's rule (spec section 0): the section after the last indicated one, else the last."""
    last = None
    for index, s in enumerate(feeder.sections):
        if s.fault_indicator:
            last = index
    if last is None:
        return None
    return feeder.sections[min(last + 1, len(feeder.sections) - 1)]


def oracle_isolation(feeder: Feeder, faulted: Section) -> set[str]:
    """Today's rule: SCADA non-tie switches bounding the faulted section."""
    return {
        w.mrid for w in feeder.switches
        if w.scada_controllable and w.kind is not SwitchKind.TIE
        and (w.to_node == faulted.from_node or w.from_node == faulted.to_node)
    }


def oracle_pickup(feeder: Feeder, tie: Switch, opened: set[str]) -> set[str]:
    """Spec 'Candidate tie': reachable from the tie with isolation open and the tie closed,
    minus what the feeder's own source still reaches."""
    graph = oracle_graph(feeder, opened, {tie.mrid})
    return oracle_reach(graph, tie.from_node) - oracle_reach(graph, feeder.source_node)


def oracle_sections(feeder: Feeder, nodes: set[str]) -> list[Section]:
    return [s for s in feeder.sections if s.to_node in nodes]


def oracle_number_ok(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def oracle_reason(entry: TieCapacity | None, load_kw: float, as_of: datetime) -> str | None:
    """REQ-TIECAP-9 precedence for a tie the guard does not hold; None = may close."""
    if entry is None:
        return "CAPACITY_UNKNOWN"
    age = as_of - entry.timestamp
    if not oracle_number_ok(entry.kw) or age < timedelta(seconds=-2):
        return "CAPACITY_INVALID"
    if entry.quality != "GOOD":
        return "CAPACITY_UNKNOWN"
    if age > timedelta(seconds=20):
        return "CAPACITY_STALE"
    if load_kw <= entry.kw + 0.5:
        return None
    return "CAPACITY_EXCEEDED"


def oracle_plan(feeder: Feeder, lockout_mrid: str, capacities: dict[str, TieCapacity],
                as_of: datetime):
    """Expected outcome: the string 'FlisrError' (no plan) or a dict of the plan facts."""
    faulted = oracle_faulted(feeder)
    assert faulted is not None, "QA generator always places a fault indication"
    opened = oracle_isolation(feeder, faulted)
    if not opened:
        return "FlisrError"
    lockout = next(w for w in feeder.switches if w.mrid == lockout_mrid)
    out = {
        "faulted": faulted.mrid,
        "isolation": opened,
        "closes": [lockout_mrid] if lockout.scada_controllable else [],
        "blocked": [],
        "ties": {},
        "restored": 0,
        "remaining": faulted.customers,
        "transferred": 0.0,
    }
    for w in feeder.switches:
        if w.kind is not SwitchKind.TIE or not w.scada_controllable:
            continue
        nodes = oracle_pickup(feeder, w, opened)
        if not nodes:
            continue
        sections = oracle_sections(feeder, nodes)
        if not all(oracle_number_ok(s.load_kw) for s in sections):
            return "FlisrError"
        held = bool(nodes & {faulted.from_node, faulted.to_node})
        load_kw = sum(s.load_kw for s in sections)
        entry = capacities.get(w.mrid)
        if held:
            reason = "FAULTED_SECTION"
            out["remaining"] += sum(s.customers for s in sections if s.mrid != faulted.mrid)
        else:
            if not oracle_number_ok(load_kw):
                return "FlisrError"
            reason = oracle_reason(entry, load_kw, as_of)
            if reason is None:
                out["closes"].append(w.mrid)
                out["restored"] += sum(s.customers for s in sections)
                out["transferred"] += load_kw
            else:
                out["remaining"] += sum(s.customers for s in sections)
        if reason is not None:
            out["blocked"].append((w.mrid, reason))
        out["ties"][w.mrid] = {"load_kw": load_kw, "entry": entry, "held": held,
                               "reason": reason, "nodes": nodes}
    return out


# ---------------------------------------------------------------- observation and checks


def observe(plan) -> dict:
    return {
        "faulted": plan.faulted_section,
        "isolation": {s.switch_mrid for s in plan.isolation},
        "closes": [s.switch_mrid for s in plan.restoration if s.action == "close"],
        "blocked": [(b.tie_id, b.reason.value) for b in plan.blocked_ties],
        "restored": plan.customers_restored,
        "remaining": plan.customers_remaining,
        "transferred": plan.transferred_load_kw,
    }


def qa_check(feeder: Feeder, lockout: str, capacities: dict[str, TieCapacity],
             as_of: datetime, kwargs: dict, plan_fn=None) -> list[str]:
    """REQ-TIECAP-21 as a list of problems; [] means the plan satisfies the invariant."""
    plan_fn = plan_fn or build_plan
    expected = oracle_plan(feeder, lockout, capacities, as_of)
    try:
        plan = plan_fn(feeder.model_copy(deep=True), lockout, **kwargs)
    except FlisrError as error:
        return [] if expected == "FlisrError" else [f"unexpected FlisrError: {error}"]
    except Exception as error:  # noqa: BLE001 - any other exception is a finding
        return [f"{type(error).__name__} instead of a plan or FlisrError: {error}"]
    if expected == "FlisrError":
        return [f"plan produced where the oracle expects FlisrError: {observe(plan)}"]
    got = observe(plan)
    problems = []
    if (got["faulted"], got["isolation"]) != (expected["faulted"], expected["isolation"]):
        return [f"oracle precondition: fault/isolation differ: {got} vs {expected}"]
    tie_closes = [m for m in got["closes"] if m != lockout]
    for mrid in tie_closes:
        tie = expected["ties"].get(mrid)
        if tie is None:
            problems.append(f"{mrid} closed but is not a candidate tie")
        elif tie["held"]:
            problems.append(f"{mrid} closed although it back-feeds the faulted section")
        elif oracle_reason(tie["entry"], tie["load_kw"], as_of) is not None:
            problems.append(f"{mrid} closed without usable capacity and L <= C + 0.5 kW: {tie}")
    if got["closes"] != expected["closes"]:
        problems.append(f"close steps {got['closes']} != oracle {expected['closes']}")
    if got["blocked"] != expected["blocked"]:
        problems.append(f"blocked_ties {got['blocked']} != oracle {expected['blocked']}")
    not_closed = set(expected["ties"]) - set(tie_closes)
    if Counter(mrid for mrid, _ in got["blocked"]) != Counter(not_closed):
        problems.append(f"not-closed ties {sorted(not_closed)} vs blocked {got['blocked']}")
    if (got["restored"], got["remaining"]) != (expected["restored"], expected["remaining"]):
        problems.append(f"customer totals {got} != oracle {expected}")
    if not math.isclose(got["transferred"], expected["transferred"], rel_tol=0, abs_tol=1e-6):
        problems.append(f"transferred_load_kw {got['transferred']} != {expected['transferred']}")
    return problems


# ---------------------------------------------------------------- QA generator


def qa_feeder(rng: random.Random) -> tuple[Feeder, str, dict]:
    """Radial or branched feeder with 1-12 sections, 1-5 ties on any node (either switch
    orientation), some non-SCADA sectionalising switches, fault on any section incl. S0."""
    n = rng.randint(1, 12)
    branched = rng.random() < 0.5
    switches = [Switch(mrid="CB", name="CB", kind=SwitchKind.BREAKER, open=True,
                       from_node="SRC", to_node="BUS")]
    sections: list[Section] = []
    for i in range(n):
        head = "BUS" if i == 0 else f"H{i}"
        if i > 0:
            parent = rng.randrange(i) if branched else i - 1
            switches.append(Switch(
                mrid=f"SW{i}", name=f"SW{i}",
                kind=rng.choice([SwitchKind.RECLOSER, SwitchKind.SECTIONALIZER]),
                scada_controllable=rng.random() < 0.9, from_node=f"N{parent}", to_node=head))
        sections.append(Section(mrid=f"S{i}", name=f"S{i}", from_node=head, to_node=f"N{i}",
                                customers=rng.randint(0, 900),
                                load_kw=round(rng.uniform(0.0, 3000.0), 3)))
    faulted = rng.randrange(n) if n == 1 or rng.random() < 0.06 else rng.randrange(1, n)
    for i in range(faulted):
        sections[i].fault_indicator = i == faulted - 1 or rng.random() < 0.5
    if faulted == 0:
        sections[0].fault_indicator = True if n == 1 else False
        if n > 1:  # fault on S0 needs an indication on S0 and none after it in list order
            sections[0].fault_indicator = True
            faulted = 1 if n > 1 else 0
    load_mode = rng.choices(["valid", "nan", "inf", "neg_inf", "negative", "overflow"],
                            [76, 5, 4, 3, 9, 3])[0]
    if load_mode != "valid":
        victim = rng.choice(sections)
        victim.load_kw = {"nan": math.nan, "inf": math.inf, "neg_inf": -math.inf,
                          "negative": -rng.choice([1e-9, 0.001, 75.0, 2000.0]),
                          "overflow": 1.5e308}[load_mode]
        if load_mode == "overflow":
            for s in sections:
                s.load_kw = 1.5e308
    nodes = ["BUS"] + [s.to_node for s in sections] + [s.from_node for s in sections]
    tie_nodes = [rng.choice(nodes) for _ in range(rng.randint(1, 5))]
    if rng.random() < 0.35:
        target = sections[faulted]
        tie_nodes[rng.randrange(len(tie_nodes))] = rng.choice([target.from_node, target.to_node])
    for t, node in enumerate(tie_nodes):
        ends = (node, f"ALT{t}") if rng.random() < 0.5 else (f"ALT{t}", node)
        switches.append(Switch(mrid=f"T{t}", name=f"Tie {t}", kind=SwitchKind.TIE,
                               normal_open=True, open=True, from_node=ends[0], to_node=ends[1],
                               scada_controllable=rng.random() < 0.85))
    rng.shuffle(switches)
    feeder = Feeder(mrid="QA", name="QA", substation="QA", nominal_kv=12.47, rating_amps=600.0,
                    source_node="SRC", sections=sections, switches=switches)
    return feeder, "CB", {"branched": branched, "load_mode": load_mode, "sections": n}


_AGE_US = [0, 1, 20_000_000, 20_000_001, 19_999_999, -2_000_000, -2_000_001, -1_999_999,
           10_000_000, 30_000_000, 120_000_000, -1_000_000]
_QUALITIES = (["GOOD"] * 13) + ["BAD", "SUSPECT", "good", "GOOD ", "", "UNCERTAIN", "Good"]


def qa_capacity(rng: random.Random, load_kw: float, as_of: datetime) -> TieCapacity:
    ref = load_kw if oracle_number_ok(load_kw) else 1234.5
    kw = rng.choice([
        ref - 0.5, ref - 0.5, math.nextafter(ref - 0.5, -math.inf), ref - 0.4, ref - 0.6,
        ref - 1.0, ref, ref + rng.uniform(0.0, 5000.0), rng.uniform(0.0, 4000.0),
        0.0, -0.0, math.nan, math.inf, -math.inf, -1e-12, -50.0, 1e308,
    ])
    age_us = rng.choice(_AGE_US) if rng.random() < 0.55 else rng.randint(-5_000_000, 60_000_000)
    timestamp = (as_of - timedelta(microseconds=age_us)).astimezone(rng.choice(QA_OFFSETS))
    return TieCapacity(kw=kw, timestamp=timestamp, quality=rng.choice(_QUALITIES))


def qa_case(rng: random.Random):
    feeder, lockout, meta = qa_feeder(rng)
    as_of = (QA_AS_OF + timedelta(seconds=rng.randint(-3_600, 3_600))).astimezone(
        rng.choice(QA_OFFSETS))
    preview = oracle_plan(feeder, lockout, {}, as_of)
    tie_loads = {} if preview == "FlisrError" else {
        mrid: t["load_kw"] for mrid, t in preview["ties"].items()}
    if preview == "FlisrError":
        tie_loads = {w.mrid: 1000.0 for w in feeder.switches if w.kind is SwitchKind.TIE}
    mode = rng.choices(["new", "legacy", "none", "empty"], [75, 15, 5, 5])[0]
    entries: dict[str, TieCapacity] = {}
    if mode in ("new", "legacy"):
        for mrid, load_kw in tie_loads.items():
            if rng.random() >= 0.1:
                entries[mrid] = qa_capacity(rng, load_kw, as_of)
        if rng.random() < 0.15:
            entries["NOT-A-TIE"] = qa_capacity(rng, 0.0, as_of)
    kwargs: dict = {"as_of": as_of}
    if mode == "new":
        kwargs["tie_capacity"] = entries
    elif mode == "legacy":
        kwargs["tie_capacity_kw"] = {k: v.kw for k, v in entries.items()}
        entries = {k: TieCapacity(kw=v.kw, timestamp=as_of, quality="GOOD")
                   for k, v in entries.items()}
    elif mode == "empty":
        kwargs["tie_capacity"] = {}
    meta["capacity_mode"] = mode
    return feeder, lockout, entries, as_of, kwargs, meta


def run_qa_sweep(seed: int, cases: int, plan_fn=None) -> tuple[list, Counter]:
    rng = random.Random(seed)
    stats: Counter = Counter()
    violations = []
    for index in range(cases):
        feeder, lockout, entries, as_of, kwargs, meta = qa_case(rng)
        stats["branched" if meta["branched"] else "radial"] += 1
        stats[f"load_mode={meta['load_mode']}"] += 1
        stats[f"capacity_mode={meta['capacity_mode']}"] += 1
        expected = oracle_plan(feeder, lockout, entries, as_of)
        if expected == "FlisrError":
            stats["expected_refusal"] += 1
        else:
            reasons = [t["reason"] or "CLOSED" for t in expected["ties"].values()]
            stats.update(reasons)
            if len(set(reasons)) > 1:
                stats["plans_with_mixed_tie_outcomes"] += 1
            if len(reasons) > 1:
                stats["plans_with_several_candidate_ties"] += 1
            for t in expected["ties"].values():
                if t["reason"] is None and t["entry"].kw < t["load_kw"]:
                    stats["closed_inside_tolerance"] += 1
                if t["reason"] is None and t["entry"].kw + 0.5 == t["load_kw"]:
                    stats["closed_at_L_eq_C_plus_0.5"] += 1
                if t["reason"] == "CAPACITY_STALE" and (
                        as_of - t["entry"].timestamp == timedelta(seconds=20, microseconds=1)):
                    stats["stale_by_one_microsecond"] += 1
        problems = qa_check(feeder, lockout, entries, as_of, kwargs, plan_fn)
        if problems:
            violations.append((index, problems))
    return violations, stats


# ---------------------------------------------------------------- the Coding unit under test


@pytest.fixture(scope="module")
def u4():
    spec = importlib.util.spec_from_file_location("qa_subject_u4_invariant", U4_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mutant_flisr(replacements: list[tuple[str, str]]) -> types.ModuleType:
    """app.flisr compiled from source with text substitutions; raises the real FlisrError."""
    source = FLISR_SRC.read_text(encoding="utf-8")
    for old, new in replacements:
        assert source.count(old) == 1, f"mutation anchor not unique or absent: {old!r}"
        source = source.replace(old, new)
    module = types.ModuleType("app.flisr_qa_mutant")
    module.__package__ = "app"
    module.__file__ = str(FLISR_SRC)
    exec(compile(source, str(FLISR_SRC), "exec"), module.__dict__)
    module.FlisrError = FlisrError
    return module


MUTATIONS = {
    "identity (control)": [],
    "tolerance 0.6 kW": [("entry.kw + TIE_CAPACITY_TOLERANCE_KW:", "entry.kw + 0.6:")],
    "tolerance 0.4 kW": [("entry.kw + TIE_CAPACITY_TOLERANCE_KW:", "entry.kw + 0.4:")],
    "no tolerance (pre-feature strict compare)": [
        ("entry.kw + TIE_CAPACITY_TOLERANCE_KW:", "entry.kw:")],
    "max age 21 s": [("if age > TIE_CAPACITY_MAX_AGE:", "if age > TIE_CAPACITY_MAX_AGE * 1.05:")],
    "max age 19 s": [("if age > TIE_CAPACITY_MAX_AGE:", "if age > TIE_CAPACITY_MAX_AGE * 0.95:")],
    "max lead 3 s": [("or age < -TIE_CAPACITY_MAX_LEAD:",
                      "or age < -TIE_CAPACITY_MAX_LEAD * 1.5:")],
    "quality compared case-insensitively": [
        ("if entry.quality != TIE_CAPACITY_GOOD_QUALITY:",
         "if entry.quality.strip().upper() != TIE_CAPACITY_GOOD_QUALITY:")],
    "missing capacity read as 0 kW GOOD": [
        ("entry = capacities.get(switch.mrid)",
         "entry = capacities.get(switch.mrid, TieCapacity.model_construct("
         "kw=0.0, timestamp=as_of, quality=TIE_CAPACITY_GOOD_QUALITY))")],
    "kw validity check deleted (NaN/inf/negative compared numerically)": [
        ("if _not_finite_nonneg(entry.kw) or age < -TIE_CAPACITY_MAX_LEAD:",
         "if age < -TIE_CAPACITY_MAX_LEAD:")],
    "future-dated check deleted": [
        ("if _not_finite_nonneg(entry.kw) or age < -TIE_CAPACITY_MAX_LEAD:",
         "if _not_finite_nonneg(entry.kw):")],
    "CAPACITY_EXCEEDED closes the tie": [
        ("    return TieBlockReason.CAPACITY_EXCEEDED", "    return None")],
    "STALE evaluated before UNKNOWN": [
        ("    if entry.quality != TIE_CAPACITY_GOOD_QUALITY:\n"
         "        return TieBlockReason.CAPACITY_UNKNOWN\n"
         "    if age > TIE_CAPACITY_MAX_AGE:\n"
         "        return TieBlockReason.CAPACITY_STALE\n",
         "    if age > TIE_CAPACITY_MAX_AGE:\n"
         "        return TieBlockReason.CAPACITY_STALE\n"
         "    if entry.quality != TIE_CAPACITY_GOOD_QUALITY:\n"
         "        return TieBlockReason.CAPACITY_UNKNOWN\n")],
    "DEF-FLISR-7 hold removed": [
        ("if candidate_nodes & {faulted_section.from_node, faulted_section.to_node}:",
         "if False:")],
    "candidate section-load check deleted": [
        ("if section.to_node in candidate_nodes and _not_finite_nonneg(section.load_kw):",
         "if False:")],
    "L range check deleted": [("        if _not_finite_nonneg(transferred):", "        if False:")],
    "blocked tie noted but not listed": [
        ("            plan.blocked_ties.append(BlockedTie(tie_id=switch.mrid, reason=reason))\n",
         "")],
    "blocked tie listed twice": [
        ("            plan.blocked_ties.append(BlockedTie(tie_id=switch.mrid, reason=reason))\n",
         "            plan.blocked_ties.append(BlockedTie(tie_id=switch.mrid, reason=reason))\n"
         "            plan.blocked_ties.append(BlockedTie(tie_id=switch.mrid, reason=reason))\n")],
    "blocked tie's customers counted as restored": [
        ("            plan.customers_remaining += sum(\n"
         "                section.customers\n"
         "                for section in feeder.sections\n"
         "                if section.to_node in candidate_nodes\n"
         "            )\n"
         "            continue\n",
         "            plan.customers_restored += sum(\n"
         "                section.customers\n"
         "                for section in feeder.sections\n"
         "                if section.to_node in candidate_nodes\n"
         "            )\n"
         "            continue\n")],
}


# ---------------------------------------------------------------- oracle self-checks


def _forbidden_names(source: str) -> list[str]:
    tree = ast.parse(source)
    logic: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("app.flisr", "app.network"):
            logic |= {a.asname or a.name for a in node.names}
        if isinstance(node, ast.ImportFrom) and node.module == "app":
            logic |= {a.asname or a.name for a in node.names if a.name in ("flisr", "network")}
        if isinstance(node, ast.Import):
            logic |= {a.asname or a.name for a in node.names
                      if a.name in ("app.flisr", "app.network")}
    found = []
    for func in ast.walk(tree):
        if not (isinstance(func, ast.FunctionDef) and func.name.startswith("oracle_")):
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Name) and (
                    node.id in logic or node.id.startswith(("TIE_CAPACITY_", "AS_OF_"))):
                found.append(f"{func.name}: {node.id}")
            if isinstance(node, ast.Attribute) and (
                    node.attr.startswith(("TIE_CAPACITY_", "AS_OF_"))
                    or ast.unparse(node.value).split(".")[0] in logic):
                found.append(f"{func.name}: {ast.unparse(node)}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                found.append(f"{func.name}: import")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
                    node.func.attr == "get" and len(node.args) + len(node.keywords) > 1
                    and "capacit" in ast.unparse(node.func.value)):
                found.append(f"{func.name}: defaulted capacity lookup {ast.unparse(node)}")
    return found


def test_qa_u4_both_oracles_are_independent_and_never_default_a_missing_value():
    """O1 for the QA file and for the Coding file (STD-QA-4: missing input is never read as
    a value; STD-SAFETY-6: oracle shares no code with the planner)."""
    assert _forbidden_names(Path(__file__).read_text(encoding="utf-8")) == []
    assert _forbidden_names(U4_FILE.read_text(encoding="utf-8")) == []


def _shipped(hold_tie: bool = False) -> Feeder:
    from app.network import get_feeder, load_network

    feeder = get_feeder(load_network(), "FDR-1201")
    next(w for w in feeder.switches if w.mrid == "CB-1201").open = True
    if hold_tie:
        for s in feeder.sections:
            s.fault_indicator = s.mrid != "SEC-1201-04"
    return feeder


def _cap(kw: float, age_s: float = 0.0, quality: str = "GOOD") -> TieCapacity:
    return TieCapacity(kw=kw, timestamp=QA_AS_OF - timedelta(seconds=age_s), quality=quality)


def test_qa_u4_oracle_reproduces_shipped_model_hand_values():
    out = oracle_plan(_shipped(), "CB-1201", {"TIE-1201-1405": _cap(1489.5)}, QA_AS_OF)
    assert out["faulted"] == "SEC-1201-03"
    assert out["isolation"] == {"SEC-SW-1201-1", "REC-1201-2"}
    tie = out["ties"]["TIE-1201-1405"]
    assert (tie["load_kw"], tie["held"], tie["reason"]) == (1490.0, False, None)
    assert (out["restored"], out["remaining"], out["transferred"]) == (341, 96, 1490.0)
    assert out["closes"] == ["CB-1201", "TIE-1201-1405"]
    for kw, reason in [(1490.0, None), (1489.5, None), (1489.4, "CAPACITY_EXCEEDED"),
                       (0.0, "CAPACITY_EXCEEDED"), (-0.0, "CAPACITY_EXCEEDED"),
                       (math.nan, "CAPACITY_INVALID"), (math.inf, "CAPACITY_INVALID"),
                       (-math.inf, "CAPACITY_INVALID"), (-1e-12, "CAPACITY_INVALID")]:
        assert oracle_reason(_cap(kw), 1490.0, QA_AS_OF) == reason, kw
    assert oracle_reason(None, 0.0, QA_AS_OF) == "CAPACITY_UNKNOWN"
    held = oracle_plan(_shipped(hold_tie=True), "CB-1201", {"TIE-1201-1405": _cap(2000.0)},
                       QA_AS_OF)
    assert held["blocked"] == [("TIE-1201-1405", "FAULTED_SECTION")]
    assert held["closes"] == ["CB-1201"] and held["remaining"] == 341


@pytest.mark.parametrize("hold_tie", [False, True])
@pytest.mark.parametrize("entry", [None, _cap(1489.5), _cap(1489.4), _cap(2000.0, 20.001),
                                   _cap(math.nan, 30.0, "BAD"), _cap(5000.0, -2.5)])
def test_qa_u4_shipped_model_plan_agrees_with_qa_oracle(hold_tie, entry):
    caps = {} if entry is None else {"TIE-1201-1405": entry}
    assert qa_check(_shipped(hold_tie), "CB-1201", caps, QA_AS_OF,
                    {"tie_capacity": caps, "as_of": QA_AS_OF}) == []


# ---------------------------------------------------------------- hand vectors


def _two_tie_feeder() -> Feeder:
    """SRC -CB- BUS =S0(FI)= N0 -SW1- H1 =S1(faulted)= N1, branching at N1 into
    N1 -SW2- H2 =S2= N2 (tie B on N2: 600.25 kW, 30 customers) and
    N1 -SW3- H3 =S3= N3 (tie A on N3: 1000.125 kW, 40 customers).
    Isolation opens SW1, SW2 and SW3, so each tie has its own island and its own L.
    Loads are exactly representable so that L - 0.5 + 0.5 == L; inexact loads are covered by
    the seeded sweep, where oracle and planner evaluate the same float expression."""
    sections = [
        Section(mrid="S0", name="S0", from_node="BUS", to_node="N0", customers=10,
                load_kw=100.0, fault_indicator=True),
        Section(mrid="S1", name="S1", from_node="H1", to_node="N1", customers=20, load_kw=200.0),
        Section(mrid="S2", name="S2", from_node="H2", to_node="N2", customers=30,
                load_kw=600.25),
        Section(mrid="S3", name="S3", from_node="H3", to_node="N3", customers=40,
                load_kw=1000.125),
    ]
    switches = [
        Switch(mrid="TB", name="Tie B", kind=SwitchKind.TIE, normal_open=True, open=True,
               from_node="ALTB", to_node="N2"),
        Switch(mrid="CB", name="CB", kind=SwitchKind.BREAKER, open=True, from_node="SRC",
               to_node="BUS"),
        Switch(mrid="SW1", name="SW1", kind=SwitchKind.RECLOSER, from_node="N0", to_node="H1"),
        Switch(mrid="SW2", name="SW2", kind=SwitchKind.SECTIONALIZER, from_node="N1",
               to_node="H2"),
        Switch(mrid="SW3", name="SW3", kind=SwitchKind.SECTIONALIZER, from_node="N1",
               to_node="H3"),
        Switch(mrid="TA", name="Tie A", kind=SwitchKind.TIE, normal_open=True, open=True,
               from_node="N3", to_node="ALTA"),
    ]
    return Feeder(mrid="QA2", name="QA2", substation="QA", nominal_kv=12.47, rating_amps=600.0,
                  source_node="SRC", sections=sections, switches=switches)


L_A = 1000.125
L_B = 600.25


@pytest.mark.parametrize(("entry", "reason"), [
    (_cap(L_A - 0.5), None),
    (_cap(math.nextafter(L_A - 0.5, -math.inf)), "CAPACITY_EXCEEDED"),
    (_cap(L_A), None),
    (_cap(L_A, age_s=20.0), None),
    (_cap(L_A, age_s=20.000001), "CAPACITY_STALE"),
    (_cap(L_A, age_s=-2.0), None),
    (_cap(L_A, age_s=-2.000001), "CAPACITY_INVALID"),
    (_cap(1e308), None),
    (_cap(-0.0), "CAPACITY_EXCEEDED"),
    (_cap(-1e-12), "CAPACITY_INVALID"),
    (_cap(math.nan), "CAPACITY_INVALID"),
    (_cap(math.inf), "CAPACITY_INVALID"),
    (_cap(-math.inf), "CAPACITY_INVALID"),
    (_cap(1e9, quality="good"), "CAPACITY_UNKNOWN"),
    (_cap(1e9, quality="GOOD "), "CAPACITY_UNKNOWN"),
    (_cap(1e9, quality=""), "CAPACITY_UNKNOWN"),
    (_cap(1e9, age_s=25.0, quality="BAD"), "CAPACITY_UNKNOWN"),
    (_cap(L_A - 0.6, age_s=25.0), "CAPACITY_STALE"),
    (_cap(math.nan, age_s=25.0, quality="BAD"), "CAPACITY_INVALID"),
    (_cap(1e9, age_s=-2.5, quality="BAD"), "CAPACITY_INVALID"),
    (None, "CAPACITY_UNKNOWN"),
])
def test_qa_u4_boundary_vectors_on_tie_a(entry, reason):
    feeder = _two_tie_feeder()
    caps = {"TA": entry} if entry is not None else {}
    assert oracle_reason(entry, L_A, QA_AS_OF) == reason
    assert qa_check(feeder, "CB", caps, QA_AS_OF, {"tie_capacity": caps, "as_of": QA_AS_OF}) == []
    plan = build_plan(feeder, "CB", tie_capacity=caps, as_of=QA_AS_OF)
    closes = [s.switch_mrid for s in plan.restoration if s.action == "close"]
    assert ("TA" in closes) is (reason is None)
    assert [b.reason.value for b in plan.blocked_ties if b.tie_id == "TA"] == (
        [] if reason is None else [reason])


def test_qa_u4_per_tie_blocking_keeps_switch_order_and_one_entry_each():
    feeder = _two_tie_feeder()
    caps = {"TA": _cap(L_A - 0.5), "TB": _cap(L_B - 0.6)}
    plan = build_plan(feeder, "CB", tie_capacity=caps, as_of=QA_AS_OF)
    assert [(b.tie_id, b.reason.value) for b in plan.blocked_ties] == [
        ("TB", "CAPACITY_EXCEEDED")]
    assert [s.switch_mrid for s in plan.restoration] == ["CB", "TA"]
    assert (plan.customers_restored, plan.customers_remaining) == (40, 20 + 30)
    swapped = {"TA": _cap(math.nan), "TB": _cap(L_B - 0.5)}
    plan = build_plan(feeder, "CB", tie_capacity=swapped, as_of=QA_AS_OF)
    assert [(b.tie_id, b.reason.value) for b in plan.blocked_ties] == [("TA", "CAPACITY_INVALID")]
    assert [s.switch_mrid for s in plan.restoration] == ["CB", "TB"]
    assert plan.transferred_load_kw == L_B
    for caps in ({"TA": _cap(L_A - 0.5), "TB": _cap(L_B - 0.6)}, swapped):
        assert qa_check(feeder, "CB", caps, QA_AS_OF, {"tie_capacity": caps,
                                                       "as_of": QA_AS_OF}) == []


@pytest.mark.parametrize("as_of_tz", QA_OFFSETS)
def test_qa_u4_offsets_do_not_move_the_freshness_boundary(as_of_tz):
    as_of = QA_AS_OF.astimezone(as_of_tz)
    fresh = TieCapacity(kw=L_A, quality="GOOD", timestamp=(
        QA_AS_OF - timedelta(seconds=20)).astimezone(timezone(timedelta(hours=-11))))
    stale = TieCapacity(kw=L_A, quality="GOOD", timestamp=(
        QA_AS_OF - timedelta(seconds=20, microseconds=1)).astimezone(timezone(timedelta(hours=14))))
    for entry, reason in ((fresh, None), (stale, "CAPACITY_STALE")):
        caps = {"TA": entry}
        plan = build_plan(_two_tie_feeder(), "CB", tie_capacity=caps, as_of=as_of)
        assert [b.reason.value for b in plan.blocked_ties if b.tie_id == "TA"] == (
            [] if reason is None else [reason])
        assert qa_check(_two_tie_feeder(), "CB", caps, as_of,
                        {"tie_capacity": caps, "as_of": as_of}) == []


# ---------------------------------------------------------------- QA seeded sweep


def test_qa_u4_invariant_holds_over_qa_seeded_feeders():
    violations, stats = run_qa_sweep(QA_SEED, QA_CASES)
    print(f"\nQA REQ-TIECAP-21 sweep: seed={QA_SEED} cases={QA_CASES} "
          f"violations={len(violations)}")
    for key in sorted(stats):
        print(f"  {key}: {stats[key]}")
    assert not violations, f"{len(violations)}/{QA_CASES}: {violations[:5]}"
    assert QA_CASES >= 500
    for key in ("CLOSED", "FAULTED_SECTION", "CAPACITY_INVALID", "CAPACITY_UNKNOWN",
                "CAPACITY_STALE", "CAPACITY_EXCEEDED", "expected_refusal",
                "plans_with_mixed_tie_outcomes", "closed_inside_tolerance",
                "closed_at_L_eq_C_plus_0.5", "stale_by_one_microsecond",
                "capacity_mode=legacy", "capacity_mode=none", "capacity_mode=empty",
                "load_mode=nan", "load_mode=negative", "load_mode=overflow",
                "radial", "branched"):
        assert stats[key] >= 10, f"QA generator exercised {key} only {stats[key]} times"


@pytest.mark.parametrize("seed", [1, 2026, 424242])
def test_qa_u4_invariant_holds_for_other_qa_seeds(seed):
    violations, _ = run_qa_sweep(seed, 300)
    assert violations == []


# ---------------------------------------------------------------- the U4 test under test


def test_qa_u4_coding_test_meets_std_safety_5_and_names_the_requirement(u4, capsys):
    assert u4.INVARIANT_CASES >= 500
    assert isinstance(u4.INVARIANT_SEED, int)
    marks = u4.pytestmark if isinstance(u4.pytestmark, list) else [u4.pytestmark]
    assert [m.args for m in marks if m.name == "requirement"] == [("REQ-TIECAP-21",)]
    u4.test_req_tiecap_21_no_tie_closed_without_usable_capacity_over_seeded_feeders()
    out = capsys.readouterr().out
    assert f"seed={u4.INVARIANT_SEED} cases={u4.INVARIANT_CASES} violations=0" in out


@pytest.mark.parametrize("seed", [3, 77, 20261017])
def test_qa_u4_coding_harness_is_not_tuned_to_its_seed(u4, seed):
    rng = random.Random(seed)
    stats: Counter = Counter()
    violations = []
    for index in range(300):
        feeder, _, _, _, capacities, as_of, kwargs = u4._case(rng)
        problems = u4._check_case(feeder, capacities, as_of, kwargs, stats)
        if problems:
            violations.append((index, problems))
    assert violations == []


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_qa_u4_coding_test_fails_on_each_forbidden_planner_behaviour(u4, monkeypatch, name):
    """STD-QA-1: Coding's mutation table re-run in-process. The identity mutant must keep
    both the Coding test and the QA sweep green; every other mutant must fail both."""
    mutant = mutant_flisr(MUTATIONS[name])
    monkeypatch.setattr(u4, "build_plan", mutant.build_plan)
    qa_violations, _ = run_qa_sweep(QA_SEED, 300, plan_fn=mutant.build_plan)
    if name == "identity (control)":
        assert mutant.build_plan is not build_plan
        u4.test_req_tiecap_21_no_tie_closed_without_usable_capacity_over_seeded_feeders()
        assert qa_violations == []
        return
    with pytest.raises((AssertionError, ValueError)) as info:
        u4.test_req_tiecap_21_no_tie_closed_without_usable_capacity_over_seeded_feeders()
    if info.type is ValueError:
        # Only the "L range check deleted" mutant: tie_capacity_verdict's own precondition
        # raises ValueError (no plan), which the Coding harness does not catch -> test error.
        assert name == "L range check deleted", f"{name}: {info.value}"
    else:
        assert "cases:" in str(info.value), f"{name}: Coding test failed for another reason"
    assert qa_violations, f"QA sweep did not detect: {name}"
    print(f"\nmutant {name!r}: QA sweep violations={len(qa_violations)}/300; "
          f"Coding test: {str(info.value)[:80]}")
