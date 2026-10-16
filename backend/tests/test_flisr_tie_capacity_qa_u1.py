"""QA re-verification of unit U1 of run feature-tie-capacity (REQ-TIECAP-19, REQ-TIECAP-22).

Independent oracle (STD-QA-3, STD-SAFETY-6, design §6.3): the functions named ``oracle_*`` use
their own breadth-first search over the feeder data and the baseline closed-form rules of the
specification ("Current behaviour", main @ 5f6b471 / base @ 20d2a30). They import neither
``app.flisr`` nor ``app.network``; ``app.models`` is used as plain data only. ``build_plan`` is
imported solely as the system under test.

Checks: (1) every vector the U1 characterization file pins is inside the REQ-TIECAP-22 input
class (finite non-negative C, L <= C or L > C + 0.5 kW, no tie held by the DEF-FLISR-7 guard,
finite non-negative section loads); (2) the oracle plan equals the planner's plan on those
vectors and on QA's own vectors; (3) no characterization capacity lies in the behaviour-change
band [L - 0.5, L) that the planner change makes more permissive; (4) every U1 test carries a
requirement marker and the characterization tests carry ``characterization``.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path

import pytest

from app.flisr import build_plan
from app.models import Feeder


def _load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


char_mod = _load_sibling("test_flisr_tie_capacity_characterization")
repro_mod = _load_sibling("test_flisr_tie_capacity_repro")

MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "feeder_model.json"
TOLERANCE_KW = 0.5  # spec τ, Q-SPEC-1 / Q-SPEC-4 (restated literal, not imported)

PINNED_FIELDS = (
    "feeder_mrid",
    "faulted_section",
    "isolation",
    "restoration",
    "customers_restored",
    "customers_remaining",
    "transferred_load_kw",
)


# --------------------------------------------------------------------------- oracle (QA-owned)


def oracle_adjacency(feeder: Feeder, forced: dict[str, bool]) -> dict[str, set[str]]:
    """Undirected node graph: sections always conduct; a switch conducts when closed.

    ``forced`` maps switch mRID -> open state overriding the model.
    """
    graph: dict[str, set[str]] = {}

    def link(a: str, b: str) -> None:
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)

    for section in feeder.sections:
        link(section.from_node, section.to_node)
    for switch in feeder.switches:
        is_open = forced.get(switch.mrid, switch.open)
        if not is_open:
            link(switch.from_node, switch.to_node)
    return graph


def oracle_reach(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    frontier = [start]
    while frontier:
        node = frontier.pop()
        if node in seen:
            continue
        seen.add(node)
        frontier.extend(graph.get(node, set()) - seen)
    return seen


def oracle_faulted_section(feeder: Feeder) -> str | None:
    """Baseline rule: the section after the last indicated one, else the last indicated."""
    indicated = [i for i, section in enumerate(feeder.sections) if section.fault_indicator]
    if not indicated:
        return None
    last = max(indicated)
    return feeder.sections[min(last + 1, len(feeder.sections) - 1)].mrid


def oracle_isolation(feeder: Feeder, faulted_mrid: str) -> list[dict]:
    faulted = next(s for s in feeder.sections if s.mrid == faulted_mrid)
    steps = []
    for switch in feeder.switches:
        if switch.kind.value == "tie" or not switch.scada_controllable:
            continue
        if switch.to_node == faulted.from_node:
            steps.append({"switch_mrid": switch.mrid, "action": "open",
                          "reason": f"upstream isolation of {faulted.name}"})
        elif switch.from_node == faulted.to_node:
            steps.append({"switch_mrid": switch.mrid, "action": "open",
                          "reason": f"downstream isolation of {faulted.name}"})
    return steps


def oracle_pickup_nodes(feeder: Feeder, tie_mrid: str, isolation_mrids: set[str]) -> set[str]:
    forced = {mrid: True for mrid in isolation_mrids}
    forced[tie_mrid] = False
    graph = oracle_adjacency(feeder, forced)
    tie = next(s for s in feeder.switches if s.mrid == tie_mrid)
    return oracle_reach(graph, tie.from_node) - oracle_reach(graph, feeder.source_node)


def oracle_load_kw(feeder: Feeder, nodes: set[str]) -> float:
    return sum(s.load_kw for s in feeder.sections if s.to_node in nodes)


def oracle_customers(feeder: Feeder, nodes: set[str]) -> int:
    return sum(s.customers for s in feeder.sections if s.to_node in nodes)


def oracle_downstream_customers(feeder: Feeder, node: str) -> int:
    """Customers on every section reachable from ``node`` without passing the source."""
    graph = oracle_adjacency(feeder, {})
    graph.pop(feeder.source_node, None)
    for neighbours in graph.values():
        neighbours.discard(feeder.source_node)
    return oracle_customers(feeder, oracle_reach(graph, node))


def oracle_plan(feeder: Feeder, lockout_mrid: str, capacity: dict[str, float]) -> dict:
    """Baseline FLISR plan restated from the specification's 'Current behaviour'.

    Returns the pinned fields plus ``_held`` (ties the DEF-FLISR-7 guard holds) and
    ``_candidates`` (tie mRID -> (L, C)) so the caller can check the REQ-TIECAP-22 input class.
    """
    lockout = next(s for s in feeder.switches if s.mrid == lockout_mrid)
    assert lockout.open, "vector must put the lockout switch in lockout"
    faulted = oracle_faulted_section(feeder)
    plan = {
        "feeder_mrid": feeder.mrid,
        "faulted_section": faulted,
        "isolation": [],
        "restoration": [],
        "customers_restored": 0,
        "customers_remaining": 0,
        "transferred_load_kw": 0.0,
        "_held": [],
        "_candidates": {},
    }
    if faulted is None:
        plan["customers_remaining"] = oracle_downstream_customers(feeder, lockout.to_node)
        return plan

    plan["isolation"] = oracle_isolation(feeder, faulted)
    isolation_mrids = {step["switch_mrid"] for step in plan["isolation"]}
    faulted_section = next(s for s in feeder.sections if s.mrid == faulted)
    plan["customers_remaining"] = faulted_section.customers

    for switch in feeder.switches:
        if switch.kind.value != "tie" or not switch.scada_controllable:
            continue
        nodes = oracle_pickup_nodes(feeder, switch.mrid, isolation_mrids)
        if not nodes:
            continue
        if nodes & {faulted_section.from_node, faulted_section.to_node}:
            plan["_held"].append(switch.mrid)
            plan["customers_remaining"] += sum(
                s.customers for s in feeder.sections
                if s.to_node in nodes and s.mrid != faulted
            )
            continue
        transferred = oracle_load_kw(feeder, nodes)
        available = capacity.get(switch.mrid, 0.0)  # baseline default, pinned by REQ-TIECAP-22
        plan["_candidates"][switch.mrid] = (transferred, available)
        if transferred > available:
            plan["customers_remaining"] += oracle_customers(feeder, nodes)
            continue
        plan["restoration"].append({
            "switch_mrid": switch.mrid, "action": "close",
            "reason": f"back-feed {len(nodes)} nodes from alternate source",
        })
        plan["transferred_load_kw"] += transferred
        plan["customers_restored"] += oracle_customers(feeder, nodes)

    if lockout.scada_controllable:
        plan["restoration"].insert(0, {
            "switch_mrid": lockout.mrid, "action": "close",
            "reason": "re-energise healthy sections upstream of the fault",
        })
    return plan


def in_req_tiecap_22_class(plan: dict, feeder: Feeder) -> bool:
    """REQ-TIECAP-22 input class: no held tie, finite non-negative loads and capacities,
    and for every candidate tie L <= C or L > C + 0.5 kW."""
    if plan["_held"]:
        return False
    if any(not (math.isfinite(s.load_kw) and s.load_kw >= 0) for s in feeder.sections):
        return False
    for load, cap in plan["_candidates"].values():
        if not (math.isfinite(cap) and cap >= 0):
            return False
        if not (load <= cap or load > cap + TOLERANCE_KW):
            return False
    return True


# --------------------------------------------------------------------------- fixtures (QA-owned)


def shipped_feeder(indicated: set[str] | None = None) -> Feeder:
    """FDR-1201 loaded straight from the JSON model, CB-1201 in lockout."""
    with MODEL_PATH.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    feeder = Feeder.model_validate(next(f for f in raw["feeders"] if f["mrid"] == "FDR-1201"))
    if indicated is not None:
        for section in feeder.sections:
            section.fault_indicator = section.mrid in indicated
    next(s for s in feeder.switches if s.mrid == "CB-1201").open = True
    return feeder


def strip(plan_dict: dict) -> dict:
    return {k: plan_dict[k] for k in PINNED_FIELDS}


def sut(plan) -> dict:
    return strip(plan.model_dump())


# --------------------------------------------------------------------------- vectors


def _param_values(func, *names):
    """Parametrize argument tuples of a test function, read from its pytest marks."""
    for mark in getattr(func, "pytestmark", []):
        if mark.name != "parametrize":
            continue
        argnames = mark.args[0]
        argnames = [a.strip() for a in argnames.split(",")] if isinstance(argnames, str) \
            else list(argnames)
        for values in mark.args[1]:
            values = values if isinstance(values, tuple) else (values,)
            yield tuple(dict(zip(argnames, values, strict=True))[n] for n in names)


CHAR_SEC_03 = [c for (c, _) in _param_values(
    char_mod.test_req_tiecap_22_char_shipped_fault_sec_1201_03, "capacity_kw", "expected")]
CHAR_SEC_02 = [c for (c, _) in _param_values(
    char_mod.test_req_tiecap_22_char_fault_sec_1201_02, "capacity_kw", "expected")]
CHAR_TWO_TIE = list(_param_values(
    char_mod.test_req_tiecap_22_char_two_tie_branched_feeder, "capacity_t1", "capacity_t2"))

# QA's own vectors (nominal, boundary just outside the band, large, zero).
QA_SEC_03 = [1490.6, 1489.4, 1490.0, 1489.0, 3000.0, 1e9, 0.0, 1e-9]
QA_SEC_02 = [1920.6, 1919.4, 1920.0, 1919.0, 2200.0, 0.0]
QA_TWO_TIE = [(300.6, 150.6), (299.4, 149.4), (300.0, 149.4), (299.4, 150.0), (1e6, 0.0),
              (0.0, 1e6)]


def _shipped_vectors():
    for cap in CHAR_SEC_03 + QA_SEC_03:
        yield pytest.param(None, cap, id=f"sec03-C{cap}")
    for cap in CHAR_SEC_02 + QA_SEC_02:
        yield pytest.param({"SEC-1201-01"}, cap, id=f"sec02-C{cap}")


@pytest.mark.requirement("REQ-TIECAP-22")
@pytest.mark.parametrize(("indicated", "capacity_kw"), list(_shipped_vectors()))
def test_qa_u1_oracle_matches_planner_on_shipped_feeder(indicated, capacity_kw):
    capacity = {"TIE-1201-1405": capacity_kw}
    expected = oracle_plan(shipped_feeder(indicated), "CB-1201", capacity)
    assert in_req_tiecap_22_class(expected, shipped_feeder(indicated)), \
        "vector outside the REQ-TIECAP-22 input class"

    observed = sut(build_plan(shipped_feeder(indicated), "CB-1201", tie_capacity_kw=capacity))

    assert observed == strip(expected)


@pytest.mark.requirement("REQ-TIECAP-22")
@pytest.mark.parametrize(("capacity_t1", "capacity_t2"), CHAR_TWO_TIE + QA_TWO_TIE)
def test_qa_u1_oracle_matches_planner_on_two_tie_feeder(capacity_t1, capacity_t2):
    capacity = {"TIE-T1": capacity_t1, "TIE-T2": capacity_t2}
    expected = oracle_plan(char_mod.two_tie_feeder(), "CB-T", capacity)
    assert in_req_tiecap_22_class(expected, char_mod.two_tie_feeder())
    assert expected["_candidates"] == {"TIE-T1": (300.0, capacity_t1),
                                       "TIE-T2": (150.0, capacity_t2)}

    observed = sut(build_plan(char_mod.two_tie_feeder(), "CB-T", tie_capacity_kw=capacity))

    assert observed == strip(expected)


@pytest.mark.requirement("REQ-TIECAP-22")
def test_qa_u1_oracle_matches_planner_non_scada_variants():
    feeder = shipped_feeder()
    next(s for s in feeder.switches if s.mrid == "TIE-1201-1405").scada_controllable = False
    expected = oracle_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
    assert expected["_candidates"] == {}
    assert sut(build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})) \
        == strip(expected)

    feeder = shipped_feeder()
    next(s for s in feeder.switches if s.mrid == "CB-1201").scada_controllable = False
    expected = oracle_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
    assert expected["restoration"][0]["switch_mrid"] == "TIE-1201-1405"
    assert sut(build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})) \
        == strip(expected)


@pytest.mark.requirement("REQ-TIECAP-22")
def test_qa_u1_pinned_constants_match_oracle():
    """The literal expected dicts in the characterization file equal the oracle's plans."""
    closed = oracle_plan(shipped_feeder(), "CB-1201", {"TIE-1201-1405": 2000.0})
    skipped = oracle_plan(shipped_feeder(), "CB-1201", {"TIE-1201-1405": 0.0})
    assert strip(closed) == char_mod.SEC_1201_03_TIE_CLOSED
    assert strip(skipped) == char_mod.SEC_1201_03_TIE_SKIPPED
    assert closed["_candidates"] == {"TIE-1201-1405": (1490.0, 2000.0)}

    closed = oracle_plan(shipped_feeder({"SEC-1201-01"}), "CB-1201", {"TIE-1201-1405": 2500.0})
    skipped = oracle_plan(shipped_feeder({"SEC-1201-01"}), "CB-1201", {"TIE-1201-1405": 0.0})
    assert strip(closed) == char_mod.SEC_1201_02_TIE_CLOSED
    assert strip(skipped) == char_mod.SEC_1201_02_TIE_SKIPPED
    assert closed["_candidates"] == {"TIE-1201-1405": (1920.0, 2500.0)}


@pytest.mark.requirement("REQ-TIECAP-22")
def test_qa_u1_characterization_avoids_behaviour_change_band():
    """No pinned capacity lies in [L - 0.5, L): skipped today, closed after REQ-TIECAP-3."""
    def in_band(load, cap):
        return load - TOLERANCE_KW <= cap < load

    assert not any(in_band(1490.0, c) for c in CHAR_SEC_03)
    assert not any(in_band(1920.0, c) for c in CHAR_SEC_02)
    assert not any(in_band(300.0, t1) or in_band(150.0, t2) for t1, t2 in CHAR_TWO_TIE)
    # and the band really is a behaviour change on the base: C = L - 0.5 skips the tie today
    assert sut(build_plan(shipped_feeder(), "CB-1201", tie_capacity_kw={"TIE-1201-1405": 1489.5}
                          ))["restoration"] == [char_mod.RECLOSE_CB_1201]


@pytest.mark.requirement("REQ-TIECAP-22")
def test_qa_u1_characterization_excludes_held_ties():
    """A fault on SEC-1201-04 puts TIE-1201-1405 on a faulted endpoint: held by the base's
    DEF-FLISR-7 guard, so it is outside this unit's input class and not pinned here."""
    feeder = shipped_feeder({"SEC-1201-01", "SEC-1201-02", "SEC-1201-03"})
    expected = oracle_plan(feeder, "CB-1201", {"TIE-1201-1405": 2000.0})
    assert expected["_held"] == ["TIE-1201-1405"]
    assert not in_req_tiecap_22_class(expected, feeder)
    assert "SEC-1201-04" not in {
        e.get("faulted_section") for (_, e) in _param_values(
            char_mod.test_req_tiecap_22_char_shipped_fault_sec_1201_03, "capacity_kw", "expected")
    }


@pytest.mark.requirement("REQ-TIECAP-19")
@pytest.mark.parametrize("capacity", [None, {}, {"TIE-1201-1405": 2000.0}])
def test_qa_u1_no_fault_plan_matches_oracle(capacity):
    feeder = shipped_feeder(set())
    expected = oracle_plan(feeder, "CB-1201", capacity or {})
    assert expected["customers_remaining"] == 412 + 268 + 96 + 341

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw=capacity)

    assert sut(plan) == strip(expected)
    assert plan.notes == ["no fault indication received; manual patrol required"]
    assert plan.model_dump().get("blocked_ties", []) == []


@pytest.mark.requirement("REQ-TIECAP-19")
def test_qa_u1_no_fault_plan_two_tie_feeder():
    feeder = char_mod.two_tie_feeder()
    for section in feeder.sections:
        section.fault_indicator = False
    plan = build_plan(feeder, "CB-T", tie_capacity_kw={"TIE-T1": 1e6, "TIE-T2": 1e6})
    assert sut(plan) == strip(oracle_plan(feeder, "CB-T", {}))
    assert plan.customers_remaining == 120 + 50 + 30 + 20
    assert plan.restoration == [] and plan.isolation == []


# --------------------------------------------------------------------------- unit hygiene


def _marks(func):
    return {m.name: m for m in getattr(func, "pytestmark", [])}


def _tests(module):
    return [getattr(module, n) for n in dir(module) if n.startswith("test_")]


def test_qa_u1_every_test_carries_requirement_and_class_markers():
    """STD-QA-6: each U1 test references a requirement id; characterization tests are marked."""
    assert pytest.mark.characterization.mark.name in {m.name for m in char_mod.pytestmark}
    for func in _tests(char_mod):
        req = _marks(func)["requirement"].args[0]
        assert req in {"REQ-TIECAP-19", "REQ-TIECAP-22"}, func.__name__
    assert {_marks(f)["requirement"].args[0] for f in _tests(char_mod)} == {
        "REQ-TIECAP-19", "REQ-TIECAP-22"}
    for func in _tests(repro_mod):
        marks = _marks(func)
        assert marks["requirement"].args[0] in {"REQ-TIECAP-5", "REQ-TIECAP-8"}, func.__name__
        assert marks["xfail"].kwargs.get("strict") is True, func.__name__
        assert marks["xfail"].kwargs["reason"].startswith("REPRO ")


def test_qa_u1_oracle_is_independent_of_planner_and_network():
    """Design §6.3 / Q-DESIGN-1: the oracle imports neither app.flisr nor app.network."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "app.network" not in imported
    assert imported & {"app.flisr"} == {"app.flisr"}  # SUT only
    oracle_src = "\n".join(
        ast.get_source_segment(Path(__file__).read_text(encoding="utf-8"), node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("oracle_")
    )
    assert "build_plan" not in oracle_src
    assert "load_on_nodes" not in oracle_src and "energised_nodes" not in oracle_src
