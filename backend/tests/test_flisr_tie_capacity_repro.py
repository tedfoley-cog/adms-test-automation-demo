"""Failing reproductions for the tie-capacity change (STD-SAFETY-3).

Recorded on the unmodified base backend/ tree @ 20d2a30 (and main @ 5f6b471) as
``xfail(strict=True)`` so the suite stays green; the planner change removes only the markers.
Shipped FDR-1201, CB-1201 in lockout, shipped fault indications: the fault is located on
SEC-1201-03, TIE-1201-1405 picks up SEC-1201-04 (L = 1490 kW) and is not held by the
DEF-FLISR-7 guard.
"""

from __future__ import annotations

import math

import pytest

from app.flisr import build_plan
from app.network import get_feeder, load_network, switch_by_mrid

TIE = "TIE-1201-1405"


def cedar_ridge_in_lockout():
    feeder = get_feeder(load_network(), "FDR-1201")
    switch_by_mrid(feeder, "CB-1201").open = True
    return feeder


def tie_closes(plan) -> list[dict]:
    return [
        step.model_dump()
        for step in plan.restoration
        if step.switch_mrid == TIE and step.action == "close"
    ]


@pytest.mark.requirement("REQ-TIECAP-5")
@pytest.mark.xfail(
    strict=True,
    reason="REPRO REQ-TIECAP-5: missing tie capacity is read as 0 kW and the plan carries no "
    "machine-readable reason for skipping TIE-1201-1405",
)
@pytest.mark.parametrize("tie_capacity_kw", [None, {}], ids=["none", "empty"])
def test_req_tiecap_5_repro_missing_capacity_blocks_tie_as_unknown(tie_capacity_kw):
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity_kw=tie_capacity_kw)

    assert plan.faulted_section == "SEC-1201-03"
    assert tie_closes(plan) == []
    assert plan.model_dump().get("blocked_ties") == [
        {"tie_id": TIE, "reason": "CAPACITY_UNKNOWN"}
    ]


@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.xfail(
    strict=True,
    reason="REPRO REQ-TIECAP-8: a non-finite legacy tie capacity passes `transferred > "
    "available` and the plan closes TIE-1201-1405",
)
@pytest.mark.parametrize("capacity_kw", [math.nan, math.inf], ids=["nan", "+inf"])
def test_req_tiecap_8_repro_non_finite_capacity_never_closes_tie(capacity_kw):
    plan = build_plan(cedar_ridge_in_lockout(), "CB-1201", tie_capacity_kw={TIE: capacity_kw})

    assert plan.faulted_section == "SEC-1201-03"
    assert tie_closes(plan) == []
