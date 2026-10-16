"""Independent QA for U3 (REQ-TIECAP-2..18, 20, 23): planner and POST /flisr/plan.

QA-owned closed-form oracle restated from the specification literals (0.5 kW, 20 s, -2 s,
60 s / +2 s, "GOOD"), with its own BFS over the test topology for isolation, candidate nodes,
L and customer sums. The ``oracle_*`` functions import nothing from ``app.flisr`` or
``app.network`` and use none of the ``models.py`` threshold constants (design 6.3, Q-DESIGN-1);
``build_plan`` / ``tie_capacity_verdict`` / ``app.api`` are imported only as the subject under
test. Vectors: the brief's shipped-model boundaries, every REQ-TIECAP-9 condition combination,
missing / invalid inputs, and 600 seeded random feeders (radial and branched, one to three
ties) compared step by step with the oracle. Tolerance 0.5 kW engineering units; per-unit
statement waived by Q-SPEC-4 (recorded against STD-SAFETY-6).
"""

from __future__ import annotations

import ast
import json
import math
import random
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, flisr
from app.flisr import FlisrError, build_plan, tie_capacity_verdict
from app.models import Feeder, Section, Switch, SwitchKind, TieCapacity

APP_DIR = Path(__file__).resolve().parent.parent / "app"
SHIPPED_MODEL = Path(__file__).resolve().parent.parent / "data" / "feeder_model.json"
TIE = "TIE-1201-1405"
NOW = datetime(2026, 10, 15, 22, 0, 0, tzinfo=UTC)
NOW_ISO = "2026-10-15T22:00:00Z"

# ---------------------------------------------------------------------------------------------
# Oracle: closed forms from the specification only
# ---------------------------------------------------------------------------------------------


def oracle_adjacency(feeder: Feeder, opened: set[str], closed: set[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for section in feeder.sections:
        graph.setdefault(section.from_node, set()).add(section.to_node)
        graph.setdefault(section.to_node, set()).add(section.from_node)
    for switch in feeder.switches:
        is_open = switch.open
        if switch.mrid in opened:
            is_open = True
        if switch.mrid in closed:
            is_open = False
        if is_open:
            continue
        graph.setdefault(switch.from_node, set()).add(switch.to_node)
        graph.setdefault(switch.to_node, set()).add(switch.from_node)
    return graph


def oracle_reach(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    queue = [start]
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        queue.extend(graph.get(node, ()))
    return seen


def oracle_faulted(feeder: Feeder) -> Section | None:
    """Spec baseline: the section after the last fault indication (or the last one)."""
    last = None
    for index, section in enumerate(feeder.sections):
        if section.fault_indicator:
            last = index
    if last is None:
        return None
    return feeder.sections[min(last + 1, len(feeder.sections) - 1)]


def oracle_isolation(feeder: Feeder, faulted: Section) -> list[str]:
    """Spec baseline isolation points: SCADA non-tie switches bounding the faulted section."""
    return [
        sw.mrid
        for sw in feeder.switches
        if sw.scada_controllable
        and sw.kind != SwitchKind.TIE
        and (sw.to_node == faulted.from_node or sw.from_node == faulted.to_node)
    ]


def oracle_candidate_nodes(feeder: Feeder, tie_mrid: str, opened: set[str]) -> set[str]:
    tie = next(sw for sw in feeder.switches if sw.mrid == tie_mrid)
    graph = oracle_adjacency(feeder, opened, {tie_mrid})
    return oracle_reach(graph, tie.from_node) - oracle_reach(graph, feeder.source_node)


def oracle_sections(feeder: Feeder, nodes: set[str]) -> list[Section]:
    return [s for s in feeder.sections if s.to_node in nodes]


def oracle_load_kw(feeder: Feeder, nodes: set[str]) -> float:
    return sum(s.load_kw for s in oracle_sections(feeder, nodes))


def oracle_customers(feeder: Feeder, nodes: set[str], exclude: str | None = None) -> int:
    return sum(s.customers for s in oracle_sections(feeder, nodes) if s.mrid != exclude)


def oracle_sections_ok(feeder: Feeder, nodes: set[str]) -> bool:
    return all(math.isfinite(s.load_kw) and s.load_kw >= 0 for s in oracle_sections(feeder, nodes))


def oracle_held(nodes: set[str], faulted: Section) -> bool:
    return bool(nodes & {faulted.from_node, faulted.to_node})


def oracle_kw_valid(kw: object) -> bool:
    if not isinstance(kw, (int, float)) or isinstance(kw, bool):
        return False
    return math.isfinite(kw) and kw >= 0


def oracle_reason(entry: TieCapacity | None, load_kw: float, as_of: datetime) -> str | None:
    """REQ-TIECAP-9 precedence; None means the tie may close (REQ-TIECAP-3)."""
    if entry is None:
        return "CAPACITY_UNKNOWN"
    age = as_of - entry.timestamp
    if not oracle_kw_valid(entry.kw) or age < timedelta(seconds=-2):
        return "CAPACITY_INVALID"
    if entry.quality != "GOOD":
        return "CAPACITY_UNKNOWN"
    if age > timedelta(seconds=20):
        return "CAPACITY_STALE"
    if load_kw <= entry.kw + 0.5:
        return None
    return "CAPACITY_EXCEEDED"


def oracle_as_of_ok(as_of: datetime, now: datetime) -> bool:
    return now - as_of <= timedelta(seconds=60) and as_of - now <= timedelta(seconds=2)


def oracle_plan(feeder: Feeder, lockout_mrid: str, capacities: dict[str, TieCapacity], as_of):
    """Expected plan for a feeder in lockout with a fault indication, or 'FlisrError'."""
    faulted = oracle_faulted(feeder)
    assert faulted is not None
    opened = set(oracle_isolation(feeder, faulted))
    if not opened:
        return "FlisrError"
    lockout = next(sw for sw in feeder.switches if sw.mrid == lockout_mrid)
    expected = {
        "isolation": sorted(opened),
        "closes": [lockout_mrid] if lockout.scada_controllable else [],
        "blocked": [],
        "restored": 0,
        "remaining": faulted.customers,
        "transferred": 0.0,
    }
    for sw in feeder.switches:
        if sw.kind != SwitchKind.TIE or not sw.scada_controllable:
            continue
        nodes = oracle_candidate_nodes(feeder, sw.mrid, opened)
        if not nodes:
            continue
        if not oracle_sections_ok(feeder, nodes):
            return "FlisrError"
        if oracle_held(nodes, faulted):
            expected["blocked"].append((sw.mrid, "FAULTED_SECTION"))
            expected["remaining"] += oracle_customers(feeder, nodes, exclude=faulted.mrid)
            continue
        load = oracle_load_kw(feeder, nodes)
        reason = oracle_reason(capacities.get(sw.mrid), load, as_of)
        if reason is None:
            expected["closes"].append(sw.mrid)
            expected["restored"] += oracle_customers(feeder, nodes)
            expected["transferred"] += load
        else:
            expected["blocked"].append((sw.mrid, reason))
            expected["remaining"] += oracle_customers(feeder, nodes)
    return expected


def observed(plan) -> dict:
    return {
        "isolation": sorted(s.switch_mrid for s in plan.isolation),
        "closes": [s.switch_mrid for s in plan.restoration if s.action == "close"],
        "blocked": [(b.tie_id, b.reason.value) for b in plan.blocked_ties],
        "restored": plan.customers_restored,
        "remaining": plan.customers_remaining,
        "transferred": plan.transferred_load_kw,
    }


def assert_agrees(feeder, lockout_mrid, capacities, as_of, **kwargs):
    expected = oracle_plan(feeder, lockout_mrid, capacities, as_of)
    if expected == "FlisrError":
        with pytest.raises(FlisrError):
            build_plan(feeder, lockout_mrid, as_of=as_of, **kwargs)
        return None
    plan = build_plan(feeder, lockout_mrid, as_of=as_of, **kwargs)
    got = observed(plan)
    assert got["transferred"] == pytest.approx(expected["transferred"], abs=1e-6)
    got["transferred"] = expected["transferred"]
    assert got == expected
    assert all(s.action == "open" for s in plan.isolation)
    assert plan.faulted_section == oracle_faulted(feeder).mrid
    return plan


# ---------------------------------------------------------------------------------------------
# Fixtures and helpers (not oracle)
# ---------------------------------------------------------------------------------------------


def shipped(indicated: set[str] | None = None, lockout: str = "CB-1201") -> Feeder:
    data = json.loads(SHIPPED_MODEL.read_text(encoding="utf-8"))
    feeder = Feeder.model_validate(data["feeders"][0])
    if indicated is not None:
        for section in feeder.sections:
            section.fault_indicator = section.mrid in indicated
    next(sw for sw in feeder.switches if sw.mrid == lockout).open = True
    return feeder


def cap(kw=2000.0, age_s: float = 0.0, quality="GOOD", as_of=NOW) -> TieCapacity:
    return TieCapacity(kw=kw, timestamp=as_of - timedelta(seconds=age_s), quality=quality)


def shipped_tie_outcome(entry: TieCapacity | None, as_of=NOW):
    plan = build_plan(shipped(), "CB-1201", tie_capacity={TIE: entry} if entry else {}, as_of=as_of)
    closed = [s.switch_mrid for s in plan.restoration if s.action == "close"]
    return plan, TIE in closed, [(b.tie_id, b.reason.value) for b in plan.blocked_ties]


def generated_feeder(rng: random.Random) -> tuple[Feeder, str]:
    """Radial or branched feeder with 3..6 sections, SCADA switches between them, 1..3 ties."""
    n = rng.randint(3, 6)
    sections, switches = [], []
    switches.append(
        Switch(mrid="CB", name="breaker", kind=SwitchKind.BREAKER, from_node="SRC", to_node="N0X",
               open=True)
    )
    for i in range(1, n + 1):
        if i == 1:
            from_node = "N0X"
        else:
            parent = rng.randint(max(1, i - 2), i - 1) if rng.random() < 0.3 else i - 1
            from_node = f"N{parent}-{i}X"
            switches.append(
                Switch(
                    mrid=f"SW{i}", name=f"switch {i}",
                    kind=rng.choice([SwitchKind.RECLOSER, SwitchKind.SECTIONALIZER]),
                    from_node=f"N{parent}", to_node=from_node,
                    scada_controllable=rng.random() < 0.9,
                )
            )
        sections.append(
            Section(
                mrid=f"SEC{i}", name=f"section {i}", from_node=from_node, to_node=f"N{i}",
                customers=rng.randint(0, 400), load_kw=round(rng.uniform(0, 2000), 1),
            )
        )
    for k in range(rng.randint(1, 3)):
        switches.append(
            Switch(
                mrid=f"TIE{k}", name=f"tie {k}", kind=SwitchKind.TIE, normal_open=True, open=True,
                from_node=f"N{rng.randint(1, n)}", to_node=f"ALT{k}",
                scada_controllable=rng.random() < 0.9,
            )
        )
    last_indicated = rng.randint(0, n - 1)
    for i, section in enumerate(sections):
        section.fault_indicator = i <= last_indicated
    feeder = Feeder(mrid="FDR-G", name="generated", substation="sub", nominal_kv=12.47,
                    source_node="SRC", rating_amps=600.0, sections=sections, switches=switches)
    return feeder, "CB"


def random_capacity(rng: random.Random, load_kw: float, as_of: datetime) -> TieCapacity | None:
    roll = rng.random()
    if roll < 0.10:
        return None
    kw = rng.choice([load_kw - 1.0, load_kw - 0.6, load_kw - 0.5, load_kw - 0.4, load_kw,
                     load_kw + 1.0, 0.0, -0.0, round(rng.uniform(0, 3000), 1)])
    if roll < 0.20:
        kw = rng.choice([math.nan, math.inf, -math.inf, -1.0, -1e-9])
    age = rng.choice([0.0, 5.0, 19.999, 20.0, 20.001, 45.0, -1.999, -2.0, -2.001, -30.0])
    quality = "GOOD" if rng.random() < 0.8 else rng.choice(["BAD", "good", "", "SUSPECT"])
    return TieCapacity(kw=kw, timestamp=as_of - timedelta(seconds=age), quality=quality)


# ---------------------------------------------------------------------------------------------
# Oracle self-checks and independence
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TIECAP-3")
def test_qa_u3_oracle_imports_nothing_from_flisr_or_network():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    offenders = []
    for func in tree.body:
        if not (isinstance(func, ast.FunctionDef) and func.name.startswith("oracle_")):
            continue
        for node in ast.walk(func):
            name = getattr(node, "id", None) or getattr(node, "attr", "")
            if name.startswith(("TIE_CAPACITY_", "AS_OF_")) or name in {
                "flisr", "api", "network", "build_plan", "tie_capacity_verdict", "models",
                "load_on_nodes", "energised_nodes", "sections_downstream_of",
            }:
                offenders.append(f"{func.name}: {name}")
    assert offenders == []


@pytest.mark.requirement("REQ-TIECAP-3")
def test_qa_u3_oracle_reproduces_hand_computed_shipped_values():
    feeder = shipped()
    faulted = oracle_faulted(feeder)
    assert faulted.mrid == "SEC-1201-03"
    opened = set(oracle_isolation(feeder, faulted))
    assert opened == {"SEC-SW-1201-1", "REC-1201-2"}
    nodes = oracle_candidate_nodes(feeder, TIE, opened)
    assert nodes == {"N-1201-4", "N-1201-3A", "ALT-1405"}
    assert [sec.mrid for sec in oracle_sections(feeder, nodes)] == ["SEC-1201-04"]
    assert oracle_load_kw(feeder, nodes) == 1490.0
    assert oracle_customers(feeder, nodes) == 341
    assert oracle_reason(cap(1490.0), 1490.0, NOW) is None
    assert oracle_reason(cap(1489.5), 1490.0, NOW) is None
    assert oracle_reason(cap(1489.4), 1490.0, NOW) == "CAPACITY_EXCEEDED"


# ---------------------------------------------------------------------------------------------
# REQ-TIECAP-3 / 4: close iff L <= C + 0.5 kW (shipped model, L = 1490 kW)
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.requirement("REQ-TIECAP-4")
@pytest.mark.parametrize(
    "capacity_kw",
    [1490.0, 1489.5, 1489.4, 1489.5000001, 1489.4999999, 0.0, 2000.0, 1e9, 1490.5, 1489.9],
)
def test_qa_u3_shipped_close_boundary_matches_oracle(capacity_kw):
    entry = cap(capacity_kw)
    plan, closed, blocked = shipped_tie_outcome(entry)
    expect_close = oracle_reason(entry, 1490.0, NOW) is None
    assert closed is expect_close
    assert blocked == ([] if expect_close else [(TIE, "CAPACITY_EXCEEDED")])
    assert plan.customers_restored == (341 if expect_close else 0)
    assert plan.customers_remaining == (96 if expect_close else 437)
    assert plan.transferred_load_kw == (1490.0 if expect_close else 0.0)


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.requirement("REQ-TIECAP-4")
def test_qa_u3_shipped_boundaries_named_in_the_brief():
    assert shipped_tie_outcome(cap(1490.0))[1] is True
    assert shipped_tie_outcome(cap(1489.5))[1] is True
    _, closed, blocked = shipped_tie_outcome(cap(1489.4))
    assert closed is False and blocked == [(TIE, "CAPACITY_EXCEEDED")]


# ---------------------------------------------------------------------------------------------
# REQ-TIECAP-5 / 6 / 7 / 8: missing, late, future-dated, invalid
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TIECAP-5")
@pytest.mark.parametrize("kwargs", [{}, {"tie_capacity": None}, {"tie_capacity": {}},
                                    {"tie_capacity": {"OTHER-TIE": cap(5000.0)}},
                                    {"tie_capacity_kw": {}}, {"tie_capacity_kw": None}])
def test_qa_u3_missing_capacity_is_unknown_never_zero(kwargs):
    plan = build_plan(shipped(), "CB-1201", as_of=NOW, **kwargs)
    assert [(b.tie_id, b.reason.value) for b in plan.blocked_ties] == [(TIE, "CAPACITY_UNKNOWN")]
    assert [s.switch_mrid for s in plan.restoration] == ["CB-1201"]
    totals = (plan.customers_restored, plan.customers_remaining, plan.transferred_load_kw)
    assert totals == (0, 437, 0.0)
    assert not any("0 kW" in note or "0.0 kW" in note for note in plan.notes)


@pytest.mark.requirement("REQ-TIECAP-5")
@pytest.mark.parametrize("quality", ["BAD", "SUSPECT", "good", "", " GOOD", "GOOD ", "Good"])
def test_qa_u3_non_good_quality_is_unknown(quality):
    _, closed, blocked = shipped_tie_outcome(cap(5000.0, quality=quality))
    assert closed is False and blocked == [(TIE, "CAPACITY_UNKNOWN")]


@pytest.mark.requirement("REQ-TIECAP-6")
@pytest.mark.requirement("REQ-TIECAP-7")
@pytest.mark.parametrize(
    "age_s", [19.999, 20.0, 20.001, 19.9999995, 20.000001, -1.999, -2.0, -2.001, -2.000001,
              -1.9999995, 0.0, 60.0, -3600.0, 86400.0]
)
def test_qa_u3_age_boundaries_match_oracle(age_s):
    entry = cap(2000.0, age_s=age_s)
    expected = oracle_reason(entry, 1490.0, NOW)
    plan, closed, blocked = shipped_tie_outcome(entry)
    assert closed is (expected is None)
    assert blocked == ([] if expected is None else [(TIE, expected)])
    if expected == "CAPACITY_STALE":
        assert any(f"{age_s:.3f} s" in note for note in plan.notes)


@pytest.mark.requirement("REQ-TIECAP-6")
@pytest.mark.requirement("REQ-TIECAP-7")
def test_qa_u3_age_measured_against_as_of_not_wall_clock():
    """A 2024 timestamp is fresh when as_of is 2024 and stale when as_of is 2026."""
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    entry = TieCapacity(kw=2000.0, timestamp=ts, quality="GOOD")
    assert shipped_tie_outcome(entry, as_of=ts + timedelta(seconds=20))[1] is True
    assert shipped_tie_outcome(entry, as_of=NOW)[2] == [(TIE, "CAPACITY_STALE")]
    early = ts - timedelta(seconds=3)
    assert shipped_tie_outcome(entry, as_of=early)[2] == [(TIE, "CAPACITY_INVALID")]


@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.parametrize("kw", [math.nan, math.inf, -math.inf, -1.0, -1e-9, -1e300, 5e-324 * -1])
def test_qa_u3_invalid_capacity_blocks_as_invalid(kw):
    _, closed, blocked = shipped_tie_outcome(cap(kw))
    assert closed is False
    assert blocked == ([(TIE, "CAPACITY_INVALID")] if (kw != 0 or math.isnan(kw)) else [])


@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.parametrize("kw", [0.0, -0.0, 5e-324])
def test_qa_u3_zero_capacity_is_valid_and_exceeded_on_shipped_load(kw):
    _, closed, blocked = shipped_tie_outcome(cap(kw))
    assert closed is False and blocked == [(TIE, "CAPACITY_EXCEEDED")]


@pytest.mark.requirement("REQ-TIECAP-8")
def test_qa_u3_future_dated_beyond_lead_is_invalid_even_with_bad_quality_and_huge_capacity():
    entry = cap(1e9, age_s=-2.001, quality="BAD")
    assert shipped_tie_outcome(entry)[2] == [(TIE, "CAPACITY_INVALID")]


# ---------------------------------------------------------------------------------------------
# REQ-TIECAP-9: precedence over every combination of conditions
# ---------------------------------------------------------------------------------------------

CONDITIONS = ("invalid_kw", "future", "bad_quality", "stale", "exceeded")


@pytest.mark.requirement("REQ-TIECAP-9")
@pytest.mark.parametrize("mask", range(1, 2 ** len(CONDITIONS)))
def test_qa_u3_precedence_over_all_condition_combinations(mask):
    flags = {name: bool(mask & (1 << i)) for i, name in enumerate(CONDITIONS)}
    if flags["future"] and flags["stale"]:
        pytest.skip("future-dated and stale are mutually exclusive on one timestamp")
    kw = math.nan if flags["invalid_kw"] else (1489.4 if flags["exceeded"] else 2000.0)
    age = -2.001 if flags["future"] else (20.001 if flags["stale"] else 0.0)
    entry = cap(kw, age_s=age, quality="BAD" if flags["bad_quality"] else "GOOD")
    expected = oracle_reason(entry, 1490.0, NOW)
    closed_form = (
        "CAPACITY_INVALID" if flags["invalid_kw"] or flags["future"]
        else "CAPACITY_UNKNOWN" if flags["bad_quality"]
        else "CAPACITY_STALE" if flags["stale"]
        else "CAPACITY_EXCEEDED"
    )
    assert expected == closed_form
    assert tie_capacity_verdict(entry, 1490.0, NOW).value == expected
    _, closed, blocked = shipped_tie_outcome(entry)
    assert closed is False and blocked == [(TIE, expected)]


@pytest.mark.requirement("REQ-TIECAP-9")
@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.parametrize("entry", [None, cap(2000.0), cap(math.nan), cap(2000.0, quality="BAD"),
                                   cap(2000.0, age_s=30.0), cap(10.0), cap(1e9, age_s=-5.0)],
                         ids=["none", "good", "nan", "bad", "stale", "short", "future"])
def test_qa_u3_held_tie_is_faulted_section_before_any_capacity_reason(entry):
    feeder = shipped(indicated={"SEC-1201-01", "SEC-1201-02", "SEC-1201-03"})
    plan = assert_agrees(feeder, "CB-1201", {TIE: entry} if entry else {}, NOW,
                         tie_capacity={TIE: entry} if entry else {})
    assert [(b.tie_id, b.reason.value) for b in plan.blocked_ties] == [(TIE, "FAULTED_SECTION")]
    assert TIE not in [s.switch_mrid for s in plan.restoration]
    assert plan.customers_remaining == 341
    assert sum("held open" in n for n in plan.notes) == 1


# ---------------------------------------------------------------------------------------------
# REQ-TIECAP-2 / 15 / 16 / 20: as_of handling, mutual exclusion, legacy, clock read once
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TIECAP-2")
def test_qa_u3_offset_as_of_is_the_same_instant_and_echoed_in_utc():
    entry = cap(2000.0, age_s=20.0)
    utc_plan = build_plan(shipped(), "CB-1201", tie_capacity={TIE: entry}, as_of=NOW)
    plus2 = NOW.astimezone(timezone(timedelta(hours=2)))
    minus7 = NOW.astimezone(timezone(timedelta(hours=-7)))
    for as_of in (plus2, minus7):
        plan = build_plan(shipped(), "CB-1201", tie_capacity={TIE: entry}, as_of=as_of)
        assert plan.model_dump() == utc_plan.model_dump()
        assert plan.as_of == NOW and plan.as_of.utcoffset() == timedelta(0)
    later = build_plan(shipped(), "CB-1201", tie_capacity={TIE: entry},
                       as_of=plus2 + timedelta(milliseconds=1))
    assert [b.reason.value for b in later.blocked_ties] == ["CAPACITY_STALE"]


@pytest.mark.requirement("REQ-TIECAP-2")
@pytest.mark.parametrize("as_of", [datetime(2026, 10, 15, 22), "2026-10-15T22:00:00Z",
                                   1790000000, NOW.date()])
def test_qa_u3_naive_or_non_datetime_as_of_yields_no_plan(as_of):
    with pytest.raises((ValueError, TypeError)):
        build_plan(shipped(), "CB-1201", tie_capacity={TIE: cap()}, as_of=as_of)


@pytest.mark.requirement("REQ-TIECAP-2")
def test_qa_u3_absent_as_of_is_utc_now_within_the_call_window():
    before = datetime.now(UTC)
    plan = build_plan(shipped(), "CB-1201", tie_capacity={TIE: cap(as_of=before)})
    after = datetime.now(UTC)
    assert before <= plan.as_of <= after
    assert plan.as_of.utcoffset() == timedelta(0)


@pytest.mark.requirement("REQ-TIECAP-20")
def test_qa_u3_clock_read_once_and_all_ties_aged_against_it(monkeypatch):
    """Two ties whose timestamps sit either side of the 20 s edge relative to a clock that
    jumps on every read: with one read both verdicts use the same instant."""
    reads = []
    base = NOW

    def ticking_clock():
        reads.append(1)
        return base + timedelta(seconds=30 * (len(reads) - 1))

    monkeypatch.setattr(flisr, "_utc_now", ticking_clock)
    feeder, lockout = generated_feeder(random.Random(7))
    while sum(sw.kind == SwitchKind.TIE for sw in feeder.switches) < 2:
        feeder, lockout = generated_feeder(random.Random(len(reads) + random.randint(0, 10**6)))
    entries = {sw.mrid: TieCapacity(kw=1e6, timestamp=base - timedelta(seconds=19.999),
                                    quality="GOOD")
               for sw in feeder.switches if sw.kind == SwitchKind.TIE}
    plan = build_plan(feeder, lockout, tie_capacity=entries)
    assert len(reads) == 1
    assert plan.as_of == base
    assert all(b.reason.value != "CAPACITY_STALE" for b in plan.blocked_ties)


@pytest.mark.requirement("REQ-TIECAP-20")
def test_qa_u3_no_clock_read_inside_the_tie_loop_by_inspection():
    source = (APP_DIR / "flisr.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_plan")
    loop_calls = [
        ast.unparse(c.func)
        for loop in ast.walk(fn) if isinstance(loop, ast.For)
        for c in ast.walk(loop) if isinstance(c, ast.Call)
    ]
    assert not any("now" in call or "utcnow" in call or "time" in call for call in loop_calls)


@pytest.mark.requirement("REQ-TIECAP-15")
@pytest.mark.parametrize("new,legacy", [({}, {}), ({TIE: cap()}, {TIE: 2000.0}), ({}, {TIE: 1.0})])
def test_qa_u3_both_maps_raise_and_return_no_plan(new, legacy):
    with pytest.raises(ValueError):
        build_plan(shipped(), "CB-1201", legacy, tie_capacity=new, as_of=NOW)
    with pytest.raises(ValueError):
        build_plan(shipped(), "CB-1201", tie_capacity_kw=legacy, tie_capacity=new, as_of=NOW)


@pytest.mark.requirement("REQ-TIECAP-16")
@pytest.mark.parametrize("value", [2000.0, 1490.0, 1489.5, 1489.4, 0.0, -0.0, 1490, 1e9])
def test_qa_u3_legacy_value_equals_good_entry_at_as_of(value):
    legacy = build_plan(shipped(), "CB-1201", tie_capacity_kw={TIE: value}, as_of=NOW)
    new = build_plan(shipped(), "CB-1201", tie_capacity={TIE: cap(float(value))}, as_of=NOW)
    assert legacy.model_dump(exclude={"deprecations"}) == new.model_dump(exclude={"deprecations"})
    assert legacy.deprecations == ["tie_capacity_kw"] and new.deprecations == []
    assert (TIE in [s.switch_mrid for s in legacy.restoration]) is (
        oracle_reason(cap(float(value)), 1490.0, NOW) is None)


@pytest.mark.requirement("REQ-TIECAP-16")
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -1.0, "2000", True, None])
def test_qa_u3_legacy_invalid_values_never_close(value):
    reason = "CAPACITY_INVALID"
    plan = build_plan(shipped(), "CB-1201", tie_capacity_kw={TIE: value}, as_of=NOW)
    assert [(b.tie_id, b.reason.value) for b in plan.blocked_ties] == [(TIE, reason)]
    assert TIE not in [s.switch_mrid for s in plan.restoration]
    assert plan.deprecations == ["tie_capacity_kw"]


@pytest.mark.requirement("REQ-TIECAP-16")
def test_qa_u3_legacy_missing_tie_is_unknown_with_deprecation():
    plan = build_plan(shipped(), "CB-1201", tie_capacity_kw={"OTHER": 9999.0}, as_of=NOW)
    assert [b.reason.value for b in plan.blocked_ties] == ["CAPACITY_UNKNOWN"]
    assert plan.deprecations == ["tie_capacity_kw"]


# ---------------------------------------------------------------------------------------------
# REQ-TIECAP-10 / 11 / 12 / 18: per-tie blocking, blocked_ties content/order, notes, accounting
# ---------------------------------------------------------------------------------------------


def two_tie_feeder() -> tuple[Feeder, str]:
    """Branched feeder: fault on SEC2; SEC3 (tie A, 300 kW, 30 cust) and SEC4 (tie B, 150 kW,
    15 cust) hang below it on separate branches."""
    sections = [
        Section(mrid="SEC1", name="s1", from_node="N0X", to_node="N1", customers=100, load_kw=500.0,
                fault_indicator=True),
        Section(mrid="SEC2", name="s2", from_node="N1X", to_node="N2", customers=50, load_kw=200.0),
        Section(mrid="SEC3", name="s3", from_node="N2A", to_node="N3", customers=30, load_kw=300.0),
        Section(mrid="SEC4", name="s4", from_node="N2B", to_node="N4", customers=15, load_kw=150.0),
    ]
    switches = [
        Switch(mrid="CB", name="cb", kind=SwitchKind.BREAKER, from_node="SRC", to_node="N0X",
               open=True),
        Switch(mrid="SW2", name="sw2", kind=SwitchKind.RECLOSER, from_node="N1", to_node="N1X"),
        Switch(mrid="SW3", name="sw3", kind=SwitchKind.SECTIONALIZER, from_node="N2",
               to_node="N2A"),
        Switch(mrid="SW4", name="sw4", kind=SwitchKind.SECTIONALIZER, from_node="N2",
               to_node="N2B"),
        Switch(mrid="TIE-A", name="tie A", kind=SwitchKind.TIE, normal_open=True, open=True,
               from_node="N3", to_node="ALT-A"),
        Switch(mrid="TIE-B", name="tie B", kind=SwitchKind.TIE, normal_open=True, open=True,
               from_node="N4", to_node="ALT-B"),
    ]
    feeder = Feeder(mrid="FDR-T", name="two tie", substation="sub", nominal_kv=12.47,
                    source_node="SRC", rating_amps=600.0, sections=sections, switches=switches)
    return feeder, "CB"


BLOCKERS = {
    "missing": None, "nan": cap(math.nan), "bad": cap(1e6, quality="BAD"),
    "stale": cap(1e6, age_s=20.001), "exceeded": cap(299.4), "future": cap(1e6, age_s=-2.001),
}


@pytest.mark.requirement("REQ-TIECAP-10")
@pytest.mark.requirement("REQ-TIECAP-18")
@pytest.mark.parametrize("blocker", BLOCKERS.values(), ids=list(BLOCKERS))
def test_qa_u3_blocking_one_tie_changes_nothing_else(blocker):
    feeder, lockout = two_tie_feeder()
    good = {"TIE-A": cap(300.0), "TIE-B": cap(149.5)}
    mixed = {"TIE-B": cap(149.5)}
    if blocker is not None:
        mixed["TIE-A"] = blocker
    full = assert_agrees(feeder, lockout, good, NOW, tie_capacity=good)
    plan = assert_agrees(feeder, lockout, mixed, NOW, tie_capacity=mixed)
    assert plan.isolation == full.isolation
    without_a = [s for s in full.restoration if s.switch_mrid != "TIE-A"]
    assert [s for s in plan.restoration if s.switch_mrid != "TIE-A"] == without_a
    assert "TIE-A" in [s.switch_mrid for s in full.restoration]
    assert "TIE-A" not in [s.switch_mrid for s in plan.restoration]
    assert plan.transferred_load_kw == 150.0 and full.transferred_load_kw == 450.0
    assert (plan.customers_restored, plan.customers_remaining) == (15, 80)
    assert (full.customers_restored, full.customers_remaining) == (45, 50)
    assert len(plan.blocked_ties) == 1 and plan.blocked_ties[0].tie_id == "TIE-A"


@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.requirement("REQ-TIECAP-12")
def test_qa_u3_blocked_ties_in_switch_order_one_note_each():
    feeder, lockout = two_tie_feeder()
    feeder.switches[4], feeder.switches[5] = feeder.switches[5], feeder.switches[4]
    caps = {"TIE-A": cap(299.4), "TIE-B": cap(1e6, age_s=25.0)}
    plan = assert_agrees(feeder, lockout, caps, NOW, tie_capacity=caps)
    assert [(b.tie_id, b.reason.value) for b in plan.blocked_ties] == [
        ("TIE-B", "CAPACITY_STALE"), ("TIE-A", "CAPACITY_EXCEEDED")]
    assert plan.restoration == [plan.restoration[0]] and plan.restoration[0].switch_mrid == "CB"
    notes_a = [n for n in plan.notes if "tie A" in n]
    notes_b = [n for n in plan.notes if "tie B" in n]
    assert len(notes_a) == 1 and len(notes_b) == 1 and len(plan.notes) == 2
    assert "CAPACITY_EXCEEDED" in notes_a[0] and "300.0" in notes_a[0] and "299.4" in notes_a[0]
    assert "CAPACITY_STALE" in notes_b[0] and "25.000 s" in notes_b[0]
    first = plan.model_dump(mode="json")["blocked_ties"][0]
    assert first == {"tie_id": "TIE-B", "reason": "CAPACITY_STALE"}


@pytest.mark.requirement("REQ-TIECAP-12")
@pytest.mark.parametrize("entry,reason,fragment", [
    (None, "CAPACITY_UNKNOWN", None),
    (cap(2000.0, quality="BAD"), "CAPACITY_UNKNOWN", "BAD"),
    (cap(math.nan), "CAPACITY_INVALID", "nan"),
    (cap(2000.0, age_s=-3.0), "CAPACITY_INVALID", "3.000 s"),
    (cap(2000.0, age_s=21.5), "CAPACITY_STALE", "21.500 s"),
    (cap(1000.0), "CAPACITY_EXCEEDED", "1490.0 kW"),
    (cap(1489.4), "CAPACITY_EXCEEDED", "1489.4 kW"),
])
def test_qa_u3_note_names_tie_and_reason(entry, reason, fragment):
    plan, _, _ = shipped_tie_outcome(entry)
    assert len(plan.notes) == 1
    note = plan.notes[0]
    assert "Hollow Creek tie to 1405" in note and reason in note
    if fragment:
        assert fragment in note


@pytest.mark.requirement("REQ-TIECAP-18")
def test_qa_u3_held_tie_counts_healthy_pickup_sections_but_not_faulted_twice():
    feeder, lockout = two_tie_feeder()
    feeder.sections[1].fault_indicator = True  # fault moves to SEC3 (30 customers)
    # A 7-customer spur SEC5 hangs below the faulted section; TIE-A now attaches at its end, so
    # the held tie's pick-up set is {SEC3 (faulted), SEC5}: only SEC5 is added to remaining.
    feeder.sections.append(Section(mrid="SEC5", name="s5", from_node="N3", to_node="N5",
                                   customers=7, load_kw=10.0))
    next(sw for sw in feeder.switches if sw.mrid == "TIE-A").from_node = "N5"
    caps = {"TIE-A": cap(1e6), "TIE-B": cap(1e6)}
    plan = assert_agrees(feeder, lockout, caps, NOW, tie_capacity=caps)
    assert [(b.tie_id, b.reason.value) for b in plan.blocked_ties] == [("TIE-A", "FAULTED_SECTION")]
    assert plan.customers_remaining == 30 + 7
    # TIE-B's pick-up set reaches SEC1, SEC2 and SEC4 through the open breaker (baseline topology
    # behaviour, out of scope): 100 + 50 + 15.
    assert plan.customers_restored == 165


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.parametrize("load_kw", [math.nan, math.inf, -math.inf, -120.0, -1e-9])
@pytest.mark.parametrize("caps", [{}, {TIE: cap(0.0)}, {TIE: cap(2000.0)}, {TIE: cap(math.nan)}])
def test_qa_u3_invalid_candidate_section_load_refuses_the_plan(load_kw, caps):
    feeder = shipped()
    feeder.sections[3].load_kw = load_kw
    assert oracle_plan(feeder, "CB-1201", caps, NOW) == "FlisrError"
    with pytest.raises(FlisrError):
        build_plan(feeder, "CB-1201", tie_capacity=caps, as_of=NOW)


# ---------------------------------------------------------------------------------------------
# Seeded sweep: 600 generated feeders against the oracle (QA vectors, not the U4 invariant)
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TIECAP-3")
@pytest.mark.requirement("REQ-TIECAP-4")
@pytest.mark.requirement("REQ-TIECAP-5")
@pytest.mark.requirement("REQ-TIECAP-6")
@pytest.mark.requirement("REQ-TIECAP-7")
@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.requirement("REQ-TIECAP-9")
@pytest.mark.requirement("REQ-TIECAP-10")
@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.requirement("REQ-TIECAP-18")
def test_qa_u3_seeded_feeders_agree_with_oracle():
    seed, count = 20261016, 600
    rng = random.Random(seed)
    tally = {"plans": 0, "refused": 0, "closed": 0, "blocked": {}, "ties": 0}
    for _ in range(count):
        feeder, lockout = generated_feeder(rng)
        as_of = NOW + timedelta(seconds=rng.uniform(-1e6, 1e6))
        faulted = oracle_faulted(feeder)
        opened = set(oracle_isolation(feeder, faulted))
        capacities: dict[str, TieCapacity] = {}
        for sw in feeder.switches:
            if sw.kind == SwitchKind.TIE:
                nodes = oracle_candidate_nodes(feeder, sw.mrid, opened) if opened else set()
                load = oracle_load_kw(feeder, nodes) if nodes else 0.0
                entry = random_capacity(rng, load, as_of)
                if entry is not None:
                    capacities[sw.mrid] = entry
        if rng.random() < 0.05:
            rng.choice(feeder.sections).load_kw = rng.choice([math.nan, math.inf, -math.inf, -50.0])
        legacy = rng.random() < 0.15 and all(e.quality == "GOOD" and e.timestamp == as_of
                                             for e in capacities.values())
        kwargs = ({"tie_capacity_kw": {k: v.kw for k, v in capacities.items()}} if legacy
                  else {"tie_capacity": capacities})
        plan = assert_agrees(feeder, lockout, capacities, as_of, **kwargs)
        if plan is None:
            tally["refused"] += 1
            continue
        tally["plans"] += 1
        tally["closed"] += len(plan.restoration) - 1
        for b in plan.blocked_ties:
            tally["blocked"][b.reason.value] = tally["blocked"].get(b.reason.value, 0) + 1
        assert plan.deprecations == (["tie_capacity_kw"] if legacy else [])
        assert plan.as_of == as_of.astimezone(UTC)
        assert len({b.tie_id for b in plan.blocked_ties}) == len(plan.blocked_ties)
        assert len(plan.notes) >= len(plan.blocked_ties)
        assert plan.transferred_load_kw >= 0 and math.isfinite(plan.transferred_load_kw)
    print(f"\nQA-U3 sweep seed={seed} count={count}: {tally}")
    assert tally["plans"] >= 450 and tally["refused"] >= 10 and tally["closed"] >= 50
    assert set(tally["blocked"]) >= {"CAPACITY_UNKNOWN", "CAPACITY_STALE", "CAPACITY_INVALID",
                                      "CAPACITY_EXCEEDED", "FAULTED_SECTION"}


# ---------------------------------------------------------------------------------------------
# STD-QA-4 failure modes and STD-SAFETY-4 inspection
# ---------------------------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TIECAP-5")
def test_qa_u3_flisr_has_no_defaulted_lookup_and_models_has_no_logic():
    flisr_src = (APP_DIR / "flisr.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(flisr_src)):
        is_get = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        if is_get and node.func.attr == "get":
            assert len(node.args) == 1 and not node.keywords, ast.unparse(node)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            assert not any(isinstance(v, ast.Constant) and v.value in (0, 0.0, {}, "")
                           for v in node.values), ast.unparse(node)
    models_tree = ast.parse((APP_DIR / "models.py").read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(models_tree)
                if isinstance(n, (ast.FunctionDef, ast.If, ast.For, ast.While, ast.Try))]
    api_src = (APP_DIR / "api.py").read_text(encoding="utf-8")
    assert "except KeyError" in api_src and "except flisr.FlisrError" in api_src
    assert flisr_src.count("raise FlisrError") >= 3


# ---------------------------------------------------------------------------------------------
# HTTP: REQ-TIECAP-13 / 14 / 15 / 16 / 17 / 23
# ---------------------------------------------------------------------------------------------


class _Recorder:
    def __init__(self, real):
        self.real, self.calls = real, []

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.real(*a, **k)


@pytest.fixture
def planner(monkeypatch):
    from app import network as net

    rec = _Recorder(api.flisr.build_plan)
    monkeypatch.setattr(api.flisr, "build_plan", rec)

    def lockout_network(indicated=None):
        model = net.load_network()
        feeder = next(f for f in model.feeders if f.mrid == "FDR-1201")
        if indicated is not None:
            for s in feeder.sections:
                s.fault_indicator = s.mrid in indicated
        next(sw for sw in feeder.switches if sw.mrid == "CB-1201").open = True
        return model

    monkeypatch.setattr(api, "load_network", lockout_network)
    return rec


@pytest.fixture
def client(planner):
    api.app.dependency_overrides[api.server_now] = lambda: NOW
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def post(client, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return client.post("/flisr/plan", content=text, headers={"content-type": "application/json"})


def body(**fields):
    return {"feeder_mrid": "FDR-1201", "lockout_switch_mrid": "CB-1201", **fields}


def jcap(kw=2000.0, timestamp=NOW_ISO, quality="GOOD", **extra):
    return {"kw": kw, "timestamp": timestamp, "quality": quality, **extra}


MALFORMED = {
    "kw_string": body(tie_capacity={TIE: jcap(kw="2000")}),
    "kw_bool": body(tie_capacity={TIE: jcap(kw=True)}),
    "kw_null": body(tie_capacity={TIE: jcap(kw=None)}),
    "kw_missing": body(tie_capacity={TIE: {"timestamp": NOW_ISO, "quality": "GOOD"}}),
    "ts_yesterday": body(tie_capacity={TIE: jcap(timestamp="yesterday")}),
    "ts_number": body(tie_capacity={TIE: jcap(timestamp=1790000000)}),
    "ts_numeric_string": body(tie_capacity={TIE: jcap(timestamp="1790000000")}),
    "ts_naive": body(tie_capacity={TIE: jcap(timestamp="2026-10-15T22:00:00")}),
    "ts_null": body(tie_capacity={TIE: jcap(timestamp=None)}),
    "ts_date_only": body(tie_capacity={TIE: jcap(timestamp="2026-10-15")}),
    "quality_missing": body(tie_capacity={TIE: {"kw": 2000.0, "timestamp": NOW_ISO}}),
    "quality_number": body(tie_capacity={TIE: jcap(quality=1)}),
    "quality_null": body(tie_capacity={TIE: jcap(quality=None)}),
    "entry_extra_field": body(tie_capacity={TIE: jcap(unit="kW")}),
    "entry_not_object": body(tie_capacity={TIE: 2000.0}),
    "entry_null": body(tie_capacity={TIE: None}),
    "tie_capacity_null": body(tie_capacity=None),
    "tie_capacity_list": body(tie_capacity=[jcap()]),
    "tie_capacity_string": body(tie_capacity="2000"),
    "body_extra_field": body(tie_capacity={TIE: jcap()}, operator="x"),
    "both_maps": body(tie_capacity={TIE: jcap()}, tie_capacity_kw={TIE: 2000.0}),
    "both_maps_empty": body(tie_capacity={}, tie_capacity_kw={}),
    "legacy_string_value": body(tie_capacity_kw={TIE: "2000"}),
    "legacy_bool_value": body(tie_capacity_kw={TIE: True}),
    "legacy_null_value": body(tie_capacity_kw={TIE: None}),
    "legacy_null": body(tie_capacity_kw=None),
    "as_of_naive": body(as_of="2026-10-15T22:00:00"),
    "as_of_yesterday": body(as_of="yesterday"),
    "as_of_number": body(as_of=1790000000),
    "as_of_null": body(as_of=None),
    "as_of_too_old": body(as_of="2026-10-15T21:58:59.999Z"),
    "as_of_too_new": body(as_of="2026-10-15T22:00:02.001Z"),
    "feeder_number": {"feeder_mrid": 1201, "lockout_switch_mrid": "CB-1201"},
    "lockout_missing": {"feeder_mrid": "FDR-1201"},
    "nan_in_rejected_entry": (
        '{"feeder_mrid":"FDR-1201","lockout_switch_mrid":"CB-1201",'
        '"tie_capacity":{"TIE-1201-1405":{"kw":NaN,"timestamp":"' + NOW_ISO + '"}}}'
    ),
    "not_json": "{not json",
}


@pytest.mark.requirement("REQ-TIECAP-13")
@pytest.mark.requirement("REQ-TIECAP-15")
@pytest.mark.requirement("REQ-TIECAP-23")
@pytest.mark.parametrize("payload", MALFORMED.values(), ids=list(MALFORMED))
def test_qa_u3_malformed_body_is_422_before_the_planner(client, planner, payload):
    response = post(client, payload)
    assert response.status_code == 422, response.text
    assert planner.calls == []
    assert "detail" in response.json() and "blocked_ties" not in response.text


@pytest.mark.requirement("REQ-TIECAP-13")
@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "-1", "-1e-9"])
@pytest.mark.parametrize("field", ["tie_capacity", "tie_capacity_kw"])
def test_qa_u3_non_finite_json_capacity_is_200_invalid(client, planner, literal, field):
    if field == "tie_capacity":
        text = json.dumps(body(tie_capacity={TIE: jcap(kw="__KW__")})).replace('"__KW__"', literal)
    else:
        text = json.dumps(body(tie_capacity_kw={TIE: "__KW__"})).replace('"__KW__"', literal)
    response = post(client, text)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["blocked_ties"] == [{"tie_id": TIE, "reason": "CAPACITY_INVALID"}]
    assert [s["switch_mrid"] for s in plan["restoration"]] == ["CB-1201"]
    assert plan["deprecations"] == (["tie_capacity_kw"] if field == "tie_capacity_kw" else [])
    assert len(planner.calls) == 1


@pytest.mark.requirement("REQ-TIECAP-13")
@pytest.mark.parametrize("entry,reason", [
    (None, "CAPACITY_UNKNOWN"), (jcap(quality="BAD"), "CAPACITY_UNKNOWN"),
    (jcap(timestamp="2026-10-15T21:59:39.999Z"), "CAPACITY_STALE"),
    (jcap(timestamp="2026-10-15T22:00:02.001Z"), "CAPACITY_INVALID"),
    (jcap(kw=1489.4), "CAPACITY_EXCEEDED"),
])
def test_qa_u3_blocked_tie_is_200_never_409(client, planner, entry, reason):
    payload = body(tie_capacity={TIE: entry} if entry else {})
    response = post(client, payload)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["blocked_ties"] == [{"tie_id": TIE, "reason": reason}]
    assert plan["customers_remaining"] == 437 and plan["customers_restored"] == 0
    assert plan["as_of"] == NOW_ISO
    assert len(planner.calls) == 1


@pytest.mark.requirement("REQ-TIECAP-13")
@pytest.mark.parametrize("ts,closes", [
    ("2026-10-15T21:59:40Z", True), ("2026-10-15T21:59:39.999Z", False),
    ("2026-10-15T22:00:02Z", True), ("2026-10-15T22:00:02.001Z", False),
    ("2026-10-16T00:00:00+02:00", True), ("2026-10-15T23:59:59.999+02:00", True),
])
def test_qa_u3_http_freshness_boundaries(client, ts, closes):
    response = post(client, body(tie_capacity={TIE: jcap(timestamp=ts)}))
    assert response.status_code == 200
    assert (TIE in [s["switch_mrid"] for s in response.json()["restoration"]]) is closes


@pytest.mark.requirement("REQ-TIECAP-13")
def test_qa_u3_http_plan_equals_direct_plan_and_existing_errors_unchanged(client, monkeypatch):
    response = post(client, body(tie_capacity={TIE: jcap(kw=1489.5)}, as_of=NOW_ISO))
    assert response.status_code == 200
    direct = build_plan(shipped(), "CB-1201", tie_capacity={TIE: cap(1489.5)}, as_of=NOW)
    assert response.json() == json.loads(direct.model_dump_json())
    assert post(client, body(feeder_mrid="FDR-9999")).status_code == 404
    assert post(client, body(lockout_switch_mrid="NOPE")).status_code == 404
    assert post(client, body(lockout_switch_mrid="REC-1201-1")).status_code == 409

    real = api.load_network
    monkeypatch.setattr(api, "load_network", lambda: _with_nan(real))
    response = post(client, body(tie_capacity={TIE: jcap()}))
    assert response.status_code == 409 and "blocked_ties" not in response.text


def _with_nan(loader):
    model = loader()
    model.feeders[0].sections[3].load_kw = math.nan
    return model


@pytest.mark.requirement("REQ-TIECAP-14")
@pytest.mark.parametrize("as_of,expected", [
    ("2026-10-15T23:00:00+01:00", NOW), ("2026-10-15T22:00:00Z", NOW),
    ("2026-10-15T22:00:00+00:00", NOW), ("2026-10-15T15:00:00-07:00", NOW),
    ("2026-10-15T21:59:00.5Z", NOW - timedelta(seconds=59.5)),
])
def test_qa_u3_as_of_echoed_as_utc_instant(client, as_of, expected):
    response = post(client, body(as_of=as_of, tie_capacity={TIE: jcap()}))
    assert response.status_code == 200, response.text
    echoed = datetime.fromisoformat(response.json()["as_of"].replace("Z", "+00:00"))
    assert echoed == expected and echoed.utcoffset() == timedelta(0)
    assert response.json()["as_of"].endswith("Z")


@pytest.mark.requirement("REQ-TIECAP-14")
def test_qa_u3_absent_as_of_is_server_now(client):
    response = post(client, body(tie_capacity={TIE: jcap()}))
    assert response.status_code == 200 and response.json()["as_of"] == NOW_ISO


@pytest.mark.requirement("REQ-TIECAP-14")
def test_qa_u3_absent_as_of_with_real_clock_lies_in_the_request_window(planner):
    client = TestClient(api.app)
    before = datetime.now(UTC)
    response = post(client, body(tie_capacity={TIE: jcap(timestamp=before.isoformat())}))
    after = datetime.now(UTC)
    assert response.status_code == 200, response.text
    echoed = datetime.fromisoformat(response.json()["as_of"].replace("Z", "+00:00"))
    assert before <= echoed <= after
    assert TIE in [s["switch_mrid"] for s in response.json()["restoration"]]


@pytest.mark.requirement("REQ-TIECAP-23")
@pytest.mark.parametrize(
    "offset_ms", [-60001, -60000, -59999, -1, 0, 1, 1999, 2000, 2001, -3600000, 86400000]
)
def test_qa_u3_as_of_bound_matches_oracle(client, planner, offset_ms):
    as_of = NOW + timedelta(milliseconds=offset_ms)
    stamp = as_of.isoformat()
    response = post(client, body(as_of=stamp, tie_capacity={TIE: jcap(timestamp=stamp)}))
    if oracle_as_of_ok(as_of, NOW):
        assert response.status_code == 200, response.text
        assert len(planner.calls) == 1
    else:
        assert response.status_code == 422, response.text
        assert planner.calls == []
        assert "as_of" in str(response.json()["detail"][0]["loc"])


@pytest.mark.requirement("REQ-TIECAP-23")
@pytest.mark.parametrize("as_of,status", [
    ("2026-10-16T00:00:00+02:00", 200), ("2026-10-16T00:00:02+02:00", 200),
    ("2026-10-16T00:00:02.001+02:00", 422), ("2026-10-15T23:59:00+02:00", 200),
    ("2026-10-15T23:58:59.999+02:00", 422), ("2026-10-15T14:59:00-07:00", 200),
])
def test_qa_u3_as_of_bound_normalises_offsets(client, planner, as_of, status):
    assert post(client, body(as_of=as_of)).status_code == status
    assert len(planner.calls) == (1 if status == 200 else 0)


@pytest.mark.requirement("REQ-TIECAP-23")
def test_qa_u3_bound_is_against_server_clock_not_capacity_timestamp(client):
    """Back-dating as_of by 60 s makes an 80 s-old value fresh (spec residual window);
    60.001 s is 422."""
    old = NOW - timedelta(seconds=80)
    ok = post(client, body(as_of=(NOW - timedelta(seconds=60)).isoformat(),
                           tie_capacity={TIE: jcap(timestamp=old.isoformat())}))
    assert ok.status_code == 200 and ok.json()["blocked_ties"] == []
    too_far = post(client, body(as_of=(NOW - timedelta(seconds=60.001)).isoformat(),
                                tie_capacity={TIE: jcap(timestamp=old.isoformat())}))
    assert too_far.status_code == 422


@pytest.mark.requirement("REQ-TIECAP-16")
@pytest.mark.parametrize(
    "value,closes", [(2000.0, True), (2000, True), (1489.5, True), (1489.4, False), (0, False)]
)
def test_qa_u3_legacy_http_matches_new_field_and_is_flagged(client, value, closes):
    legacy = post(client, body(tie_capacity_kw={TIE: value}, as_of=NOW_ISO))
    new = post(client, body(tie_capacity={TIE: jcap(kw=float(value))}, as_of=NOW_ISO))
    assert legacy.status_code == 200 and new.status_code == 200
    lj, nj = legacy.json(), new.json()
    assert lj["deprecations"] == ["tie_capacity_kw"] and nj["deprecations"] == []
    lj.pop("deprecations"), nj.pop("deprecations")
    assert lj == nj
    assert (TIE in [s["switch_mrid"] for s in lj["restoration"]]) is closes


@pytest.mark.requirement("REQ-TIECAP-16")
def test_qa_u3_no_map_at_all_is_unknown_without_deprecation(client):
    response = post(client, body())
    assert response.status_code == 200
    assert response.json()["blocked_ties"] == [{"tie_id": TIE, "reason": "CAPACITY_UNKNOWN"}]
    assert response.json()["deprecations"] == []


@pytest.mark.requirement("REQ-TIECAP-17")
def test_qa_u3_openapi_description_states_deprecation_removal_and_exclusivity():
    text = api.app.openapi()["paths"]["/flisr/plan"]["post"]["description"]
    assert "tie_capacity_kw" in text and "deprecated" in text.lower()
    assert "mutually exclusive" in text and "tie_capacity" in text
    assert "one release" in text and ("removed" in text or "removal" in text)
    schema = api.app.openapi()["components"]["schemas"]
    assert "tie_capacity" in schema["FlisrRequest"]["properties"]
    assert schema["FlisrRequest"].get("additionalProperties") is False
    assert {"as_of", "blocked_ties", "deprecations"} <= set(schema["RestorationPlan"]["properties"])


@pytest.mark.requirement("REQ-TIECAP-13")
def test_qa_u3_held_tie_over_http_is_200_faulted_section(client, monkeypatch):
    real = api.load_network
    indicated = {"SEC-1201-01", "SEC-1201-02", "SEC-1201-03"}
    monkeypatch.setattr(api, "load_network", lambda: real(indicated))
    response = post(client, body(tie_capacity={TIE: jcap()}))
    assert response.status_code == 200
    assert response.json()["blocked_ties"] == [{"tie_id": TIE, "reason": "FAULTED_SECTION"}]
    assert response.json()["faulted_section"] == "SEC-1201-04"
