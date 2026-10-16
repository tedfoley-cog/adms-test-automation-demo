"""Characterization of build_plan before the tie-capacity change (REQ-TIECAP-19, REQ-TIECAP-22).

Pinned on the unmodified base backend/ tree @ 20d2a30 (STD-SAFETY-2); the same values hold on
main @ 5f6b471. Every input goes through the legacy ``tie_capacity_kw`` map with a finite,
non-negative entry for each candidate tie and either L <= C or L > C + 0.5 kW, so the
tie-capacity change must leave these plans unchanged. Notes text is not pinned (REQ-TIECAP-12
rewrites it). Excluded on purpose: C in (L, L + 0.5], missing entries, NaN/inf/negative
capacities, invalid section loads, and faults on a section with a SCADA tie at either endpoint
(those ties are held by the DEF-FLISR-7 guard and pinned by test_flisr_characterization.py and
test_flisr_def_flisr_7.py).
"""

from __future__ import annotations

import pytest

from app.flisr import build_plan
from app.models import Feeder, Section, Switch, SwitchKind
from app.network import get_feeder, load_network, switch_by_mrid

pytestmark = [pytest.mark.characterization]

PINNED_FIELDS = (
    "feeder_mrid",
    "faulted_section",
    "isolation",
    "restoration",
    "customers_restored",
    "customers_remaining",
    "transferred_load_kw",
)

ISOLATE_SEC_1201_03 = [
    {"switch_mrid": "SEC-SW-1201-1", "action": "open",
     "reason": "upstream isolation of Quarry Crossing"},
    {"switch_mrid": "REC-1201-2", "action": "open",
     "reason": "downstream isolation of Quarry Crossing"},
]
ISOLATE_SEC_1201_02 = [
    {"switch_mrid": "REC-1201-1", "action": "open",
     "reason": "upstream isolation of Mill Road lateral"},
    {"switch_mrid": "SEC-SW-1201-1", "action": "open",
     "reason": "downstream isolation of Mill Road lateral"},
]
ISOLATE_SEC_B = [
    {"switch_mrid": "REC-T1", "action": "open", "reason": "upstream isolation of SEC-B"},
    {"switch_mrid": "SW-T2", "action": "open", "reason": "downstream isolation of SEC-B"},
    {"switch_mrid": "SW-T3", "action": "open", "reason": "downstream isolation of SEC-B"},
]
RECLOSE_CB_1201 = {"switch_mrid": "CB-1201", "action": "close",
                   "reason": "re-energise healthy sections upstream of the fault"}
RECLOSE_CB_T = {"switch_mrid": "CB-T", "action": "close",
                "reason": "re-energise healthy sections upstream of the fault"}


def _tie_close(mrid: str, nodes: int) -> dict:
    return {"switch_mrid": mrid, "action": "close",
            "reason": f"back-feed {nodes} nodes from alternate source"}


def pinned(plan) -> dict:
    dumped = plan.model_dump()
    return {field: dumped[field] for field in PINNED_FIELDS}


def cedar_ridge_in_lockout(indicated: set[str] | None = None) -> Feeder:
    """Shipped FDR-1201 with CB-1201 in lockout; optionally replace the fault indications."""
    feeder = get_feeder(load_network(), "FDR-1201")
    if indicated is not None:
        for section in feeder.sections:
            section.fault_indicator = section.mrid in indicated
    switch_by_mrid(feeder, "CB-1201").open = True
    return feeder


def two_tie_feeder() -> Feeder:
    """Branched test feeder: fault on SEC-B, two downstream branches each with its own tie.

    SRC -CB-T- BUS =SEC-A= N1 -REC-T1- N1A =SEC-B= N2 -SW-T2- N2A =SEC-C= N3 -TIE-T1- ALT-1
                                                       N2 -SW-T3- N2B =SEC-D= N4 -TIE-T2- ALT-2
    Neither tie touches an endpoint of SEC-B, so the DEF-FLISR-7 guard does not hold either.
    Tie candidate loads: TIE-T1 L = 300 kW (SEC-C, 30 customers); TIE-T2 L = 150 kW (SEC-D, 20).
    """

    def section(mrid, from_node, to_node, customers, load_kw, indicated=False):
        return Section(mrid=mrid, name=mrid, from_node=from_node, to_node=to_node,
                       customers=customers, load_kw=load_kw, fault_indicator=indicated)

    def switch(mrid, kind, from_node, to_node, is_open=False):
        return Switch(mrid=mrid, name=mrid, kind=kind, from_node=from_node, to_node=to_node,
                      open=is_open, normal_open=is_open)

    return Feeder(
        mrid="FDR-T", name="Two-tie test feeder", substation="TEST", nominal_kv=12.47,
        source_node="SRC", rating_amps=600.0,
        sections=[
            section("SEC-A", "BUS", "N1", 120, 500.0, indicated=True),
            section("SEC-B", "N1A", "N2", 50, 200.0),
            section("SEC-C", "N2A", "N3", 30, 300.0),
            section("SEC-D", "N2B", "N4", 20, 150.0),
        ],
        switches=[
            switch("CB-T", SwitchKind.BREAKER, "SRC", "BUS", is_open=True),
            switch("REC-T1", SwitchKind.RECLOSER, "N1", "N1A"),
            switch("SW-T2", SwitchKind.SECTIONALIZER, "N2", "N2A"),
            switch("SW-T3", SwitchKind.SECTIONALIZER, "N2", "N2B"),
            switch("TIE-T1", SwitchKind.TIE, "N3", "ALT-1", is_open=True),
            switch("TIE-T2", SwitchKind.TIE, "N4", "ALT-2", is_open=True),
        ],
    )


# Shipped indications locate SEC-1201-03; TIE-1201-1405 picks up SEC-1201-04, L = 1490 kW.
SEC_1201_03_TIE_CLOSED = {
    "feeder_mrid": "FDR-1201",
    "faulted_section": "SEC-1201-03",
    "isolation": ISOLATE_SEC_1201_03,
    "restoration": [RECLOSE_CB_1201, _tie_close("TIE-1201-1405", 3)],
    "customers_restored": 341,
    "customers_remaining": 96,
    "transferred_load_kw": 1490.0,
}
SEC_1201_03_TIE_SKIPPED = {
    "feeder_mrid": "FDR-1201",
    "faulted_section": "SEC-1201-03",
    "isolation": ISOLATE_SEC_1201_03,
    "restoration": [RECLOSE_CB_1201],
    "customers_restored": 0,
    "customers_remaining": 437,
    "transferred_load_kw": 0.0,
}


@pytest.mark.requirement("REQ-TIECAP-22")
@pytest.mark.parametrize(
    ("capacity_kw", "expected"),
    [
        (1_000_000.0, SEC_1201_03_TIE_CLOSED),
        (2000.0, SEC_1201_03_TIE_CLOSED),
        (1490.0, SEC_1201_03_TIE_CLOSED),  # L == C closes
        (1489.4, SEC_1201_03_TIE_SKIPPED),  # L > C + 0.5 kW
        (1000.0, SEC_1201_03_TIE_SKIPPED),
        (0.0, SEC_1201_03_TIE_SKIPPED),
    ],
)
def test_req_tiecap_22_char_shipped_fault_sec_1201_03(capacity_kw, expected):
    plan = build_plan(
        cedar_ridge_in_lockout(), "CB-1201", tie_capacity_kw={"TIE-1201-1405": capacity_kw}
    )

    assert pinned(plan) == expected


SEC_1201_02_TIE_CLOSED = {
    "feeder_mrid": "FDR-1201",
    "faulted_section": "SEC-1201-02",
    "isolation": ISOLATE_SEC_1201_02,
    "restoration": [RECLOSE_CB_1201, _tie_close("TIE-1201-1405", 5)],
    "customers_restored": 437,
    "customers_remaining": 268,
    "transferred_load_kw": 1920.0,
}
SEC_1201_02_TIE_SKIPPED = {
    "feeder_mrid": "FDR-1201",
    "faulted_section": "SEC-1201-02",
    "isolation": ISOLATE_SEC_1201_02,
    "restoration": [RECLOSE_CB_1201],
    "customers_restored": 0,
    "customers_remaining": 705,
    "transferred_load_kw": 0.0,
}


@pytest.mark.requirement("REQ-TIECAP-22")
@pytest.mark.parametrize(
    ("capacity_kw", "expected"),
    [
        (2500.0, SEC_1201_02_TIE_CLOSED),
        (1920.0, SEC_1201_02_TIE_CLOSED),  # L == C closes
        (1919.4, SEC_1201_02_TIE_SKIPPED),  # L > C + 0.5 kW
        (1000.0, SEC_1201_02_TIE_SKIPPED),
        (0.0, SEC_1201_02_TIE_SKIPPED),
    ],
)
def test_req_tiecap_22_char_fault_sec_1201_02(capacity_kw, expected):
    # Indication on SEC-1201-01 only locates SEC-1201-02; the tie picks up SEC-1201-03 and -04.
    plan = build_plan(
        cedar_ridge_in_lockout({"SEC-1201-01"}),
        "CB-1201",
        tie_capacity_kw={"TIE-1201-1405": capacity_kw},
    )

    assert pinned(plan) == expected


@pytest.mark.requirement("REQ-TIECAP-22")
def test_req_tiecap_22_char_non_candidate_capacity_entry_is_ignored():
    plan = build_plan(
        cedar_ridge_in_lockout(),
        "CB-1201",
        tie_capacity_kw={"TIE-1201-1405": 2000.0, "TIE-NOT-ON-FEEDER": 5.0},
    )

    assert pinned(plan) == SEC_1201_03_TIE_CLOSED


@pytest.mark.requirement("REQ-TIECAP-22")
def test_req_tiecap_22_char_non_scada_tie_is_skipped_silently():
    feeder = cedar_ridge_in_lockout()
    switch_by_mrid(feeder, "TIE-1201-1405").scada_controllable = False

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert pinned(plan) == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": "SEC-1201-03",
        "isolation": ISOLATE_SEC_1201_03,
        "restoration": [RECLOSE_CB_1201],
        "customers_restored": 0,
        "customers_remaining": 96,
        "transferred_load_kw": 0.0,
    }


@pytest.mark.requirement("REQ-TIECAP-22")
def test_req_tiecap_22_char_non_scada_lockout_is_not_reclosed():
    feeder = cedar_ridge_in_lockout()
    switch_by_mrid(feeder, "CB-1201").scada_controllable = False

    plan = build_plan(feeder, "CB-1201", tie_capacity_kw={"TIE-1201-1405": 2000.0})

    assert pinned(plan) == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": "SEC-1201-03",
        "isolation": ISOLATE_SEC_1201_03,
        "restoration": [_tie_close("TIE-1201-1405", 3)],
        "customers_restored": 341,
        "customers_remaining": 96,
        "transferred_load_kw": 1490.0,
    }


@pytest.mark.requirement("REQ-TIECAP-22")
@pytest.mark.parametrize(
    ("capacity_t1", "capacity_t2", "restoration", "restored", "remaining", "transferred"),
    [
        (1000.0, 1000.0,
         [RECLOSE_CB_T, _tie_close("TIE-T1", 3), _tie_close("TIE-T2", 3)], 50, 50, 450.0),
        (300.0, 150.0,  # L == C on both ties
         [RECLOSE_CB_T, _tie_close("TIE-T1", 3), _tie_close("TIE-T2", 3)], 50, 50, 450.0),
        (299.4, 150.0,  # TIE-T1 L > C + 0.5 kW
         [RECLOSE_CB_T, _tie_close("TIE-T2", 3)], 20, 80, 150.0),
        (300.0, 149.4,  # TIE-T2 L > C + 0.5 kW
         [RECLOSE_CB_T, _tie_close("TIE-T1", 3)], 30, 70, 300.0),
        (0.0, 0.0,
         [RECLOSE_CB_T], 0, 100, 0.0),
    ],
)
def test_req_tiecap_22_char_two_tie_branched_feeder(
    capacity_t1, capacity_t2, restoration, restored, remaining, transferred
):
    plan = build_plan(
        two_tie_feeder(), "CB-T", tie_capacity_kw={"TIE-T1": capacity_t1, "TIE-T2": capacity_t2}
    )

    assert pinned(plan) == {
        "feeder_mrid": "FDR-T",
        "faulted_section": "SEC-B",
        "isolation": ISOLATE_SEC_B,
        "restoration": restoration,
        "customers_restored": restored,
        "customers_remaining": remaining,
        "transferred_load_kw": transferred,
    }


@pytest.mark.requirement("REQ-TIECAP-19")
@pytest.mark.parametrize("tie_capacity_kw", [{"TIE-1201-1405": 2000.0}, None])
def test_req_tiecap_19_char_no_fault_indication_plan(tie_capacity_kw):
    plan = build_plan(cedar_ridge_in_lockout(set()), "CB-1201", tie_capacity_kw=tie_capacity_kw)

    assert plan.feeder_mrid == "FDR-1201"
    assert plan.faulted_section is None
    assert plan.isolation == []
    assert plan.restoration == []
    assert plan.notes == ["no fault indication received; manual patrol required"]
    assert plan.customers_remaining == 1117
    assert plan.customers_restored == 0
    assert plan.transferred_load_kw == 0.0
    assert plan.model_dump().get("blocked_ties", []) == []
