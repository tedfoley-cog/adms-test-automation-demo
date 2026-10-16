"""Domain types for the tie-capacity change (REQ-TIECAP-1, REQ-TIECAP-11).

Every accept/reject class of REQ-TIECAP-1 is checked twice: through
``TieCapacity.model_validate_json`` (JSON mode) and through a FastAPI ``TestClient`` echo
route defined here, because FastAPI validates request bodies in Python mode (spec section 4
design note). Expected values are literals from the specification, not the models module.
"""

from __future__ import annotations

import ast
import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import models
from app.models import BlockedTie, RestorationPlan, TieBlockReason, TieCapacity

GOOD_TS = "2026-10-15T22:00:00Z"
GOOD_TS_INSTANT = datetime(2026, 10, 15, 22, 0, 0, tzinfo=UTC)

echo_app = FastAPI()


@echo_app.post("/echo")
def echo(body: TieCapacity) -> dict:
    return {
        "kw": repr(body.kw),
        "timestamp_utc": body.timestamp.astimezone(UTC).isoformat(),
        "quality": body.quality,
    }


client = TestClient(echo_app)


def entry(**overrides) -> dict:
    body = {"kw": 2000.0, "timestamp": GOOD_TS, "quality": "GOOD"}
    body.update(overrides)
    return body


def raw_json(body: dict) -> str:
    # json.dumps writes NaN / Infinity / -Infinity literals for non-finite floats.
    return json.dumps(body)


def via_json(text: str) -> TieCapacity:
    return TieCapacity.model_validate_json(text)


def via_http(text: str):
    return client.post("/echo", content=text, headers={"content-type": "application/json"})


def without(key: str) -> dict:
    body = entry()
    del body[key]
    return body


REJECT = {
    "timestamp_yesterday": entry(timestamp="yesterday"),
    "timestamp_json_number": entry(timestamp=1790000000),
    "timestamp_numeric_string": entry(timestamp="1790000000"),
    "timestamp_naive": entry(timestamp="2026-10-15T22:00:00"),
    "timestamp_date_only": entry(timestamp="2026-10-15"),
    "timestamp_null": entry(timestamp=None),
    "timestamp_bool": entry(timestamp=True),
    "kw_string": entry(kw="2000"),
    "kw_bool": entry(kw=True),
    "kw_null": entry(kw=None),
    "quality_number": entry(quality=1),
    "quality_null": entry(quality=None),
    "quality_bool": entry(quality=True),
    "extra_field": entry(source="SCADA"),
    "missing_kw": without("kw"),
    "missing_timestamp": without("timestamp"),
    "missing_quality": without("quality"),
}


@pytest.mark.requirement("REQ-TIECAP-1")
@pytest.mark.parametrize("case", sorted(REJECT))
def test_req_tiecap_1_tie_capacity_rejects_json(case):
    with pytest.raises(ValidationError):
        via_json(raw_json(REJECT[case]))


@pytest.mark.requirement("REQ-TIECAP-1")
@pytest.mark.parametrize("case", sorted(REJECT))
def test_req_tiecap_1_tie_capacity_rejects_http_422(case):
    response = via_http(raw_json(REJECT[case]))
    assert response.status_code == 422, response.text


ACCEPT_KW = {
    "nan": (math.nan, "nan"),
    "pos_inf": (math.inf, "inf"),
    "neg_inf": (-math.inf, "-inf"),
    "negative": (-1.0, "-1.0"),
    "zero": (0.0, "0.0"),
    "integer_number": (2000, "2000.0"),
    "boundary": (1489.5, "1489.5"),
}


@pytest.mark.requirement("REQ-TIECAP-1")
@pytest.mark.parametrize("case", sorted(ACCEPT_KW))
def test_req_tiecap_1_kw_is_not_range_checked_json(case):
    value, expected_repr = ACCEPT_KW[case]
    parsed = via_json(raw_json(entry(kw=value)))
    assert isinstance(parsed.kw, float)
    assert repr(parsed.kw) == expected_repr


@pytest.mark.requirement("REQ-TIECAP-1")
@pytest.mark.parametrize("case", sorted(ACCEPT_KW))
def test_req_tiecap_1_kw_is_not_range_checked_http(case):
    value, expected_repr = ACCEPT_KW[case]
    response = via_http(raw_json(entry(kw=value)))
    assert response.status_code == 200, response.text
    assert response.json()["kw"] == expected_repr


ACCEPT_TS = {
    "utc_z": ("2026-10-15T22:00:00Z", GOOD_TS_INSTANT),
    "utc_offset": ("2026-10-15T22:00:00+00:00", GOOD_TS_INSTANT),
    "plus_02_00": ("2026-10-16T00:00:00+02:00", GOOD_TS_INSTANT),
    "minus_05_00": ("2026-10-15T17:00:00-05:00", GOOD_TS_INSTANT),
    "fractional": (
        "2026-10-15T22:00:00.001Z",
        GOOD_TS_INSTANT + timedelta(milliseconds=1),
    ),
    # No clock comparison in the model: far past and far future are left to the planner.
    "far_past": ("2000-01-01T00:00:00Z", datetime(2000, 1, 1, tzinfo=UTC)),
    "far_future": ("2100-01-01T00:00:00Z", datetime(2100, 1, 1, tzinfo=UTC)),
}


@pytest.mark.requirement("REQ-TIECAP-1")
@pytest.mark.parametrize("case", sorted(ACCEPT_TS))
def test_req_tiecap_1_timestamp_aware_iso8601_accepted_json(case):
    text, instant = ACCEPT_TS[case]
    parsed = via_json(raw_json(entry(timestamp=text)))
    assert parsed.timestamp.tzinfo is not None
    assert parsed.timestamp == instant


@pytest.mark.requirement("REQ-TIECAP-1")
@pytest.mark.parametrize("case", sorted(ACCEPT_TS))
def test_req_tiecap_1_timestamp_aware_iso8601_accepted_http(case):
    text, instant = ACCEPT_TS[case]
    response = via_http(raw_json(entry(timestamp=text)))
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["timestamp_utc"]) == instant


@pytest.mark.requirement("REQ-TIECAP-1")
@pytest.mark.parametrize("quality", ["GOOD", "BAD", "SUSPECT", "good", ""])
def test_req_tiecap_1_quality_any_string_accepted(quality):
    assert via_json(raw_json(entry(quality=quality))).quality == quality
    response = via_http(raw_json(entry(quality=quality)))
    assert response.status_code == 200, response.text
    assert response.json()["quality"] == quality


@pytest.mark.requirement("REQ-TIECAP-1")
def test_req_tiecap_1_python_callers_pass_aware_datetime():
    tc = TieCapacity(kw=1490.0, timestamp=GOOD_TS_INSTANT, quality="GOOD")
    assert tc.timestamp == GOOD_TS_INSTANT


@pytest.mark.requirement("REQ-TIECAP-1")
def test_req_tiecap_1_python_callers_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        TieCapacity(kw=1490.0, timestamp=datetime(2026, 10, 15, 22, 0, 0), quality="GOOD")


@pytest.mark.requirement("REQ-TIECAP-1")
def test_req_tiecap_1_characteristic_constants_pinned():
    # P1 (design section 6.3): spec literals Q-SPEC-1/2/4/10/12.
    assert models.TIE_CAPACITY_TOLERANCE_KW == 0.5
    assert models.TIE_CAPACITY_MAX_AGE == timedelta(seconds=20)
    assert models.TIE_CAPACITY_MAX_LEAD == timedelta(seconds=2)
    assert models.AS_OF_MAX_LAG == timedelta(seconds=60)
    assert models.AS_OF_MAX_LEAD == timedelta(seconds=2)
    assert models.TIE_CAPACITY_GOOD_QUALITY == "GOOD"


@pytest.mark.requirement("REQ-TIECAP-1")
def test_req_tiecap_1_models_module_imports_stdlib_and_pydantic_only():
    tree = ast.parse(Path(models.__file__).read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "models.py must not import other app modules"
            roots.add(node.module.split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"pydantic"}
    assert roots <= allowed, roots - allowed


CONTROL_FLOW = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)


@pytest.mark.requirement("REQ-TIECAP-1")
def test_req_tiecap_1_models_module_has_no_control_flow():
    # STD-ARCH-1 / verify check model_logic_separation: models.py declares types and
    # constants only; validation is composed from pydantic types, never branched by hand.
    tree = ast.parse(Path(models.__file__).read_text())
    found = [
        f"line {node.lineno}: {type(node).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, CONTROL_FLOW)
    ]
    assert found == []


@pytest.mark.requirement("REQ-TIECAP-11")
def test_req_tiecap_11_block_reason_members_in_precedence_order():
    # REQ-TIECAP-11 / REQ-TIECAP-9 as amended by Q-DESIGN-3.
    assert [m.value for m in TieBlockReason] == [
        "FAULTED_SECTION",
        "CAPACITY_INVALID",
        "CAPACITY_UNKNOWN",
        "CAPACITY_STALE",
        "CAPACITY_EXCEEDED",
    ]


@pytest.mark.requirement("REQ-TIECAP-11")
def test_req_tiecap_11_blocked_tie_round_trip():
    blocked = BlockedTie(tie_id="TIE-1201-1405", reason="CAPACITY_UNKNOWN")
    assert blocked.reason is TieBlockReason.CAPACITY_UNKNOWN
    assert blocked.model_dump(mode="json") == {
        "tie_id": "TIE-1201-1405",
        "reason": "CAPACITY_UNKNOWN",
    }


@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.parametrize("reason", ["CAPACITY_LOW", "capacity_unknown", "", None])
def test_req_tiecap_11_blocked_tie_rejects_unknown_reason(reason):
    with pytest.raises(ValidationError):
        BlockedTie(tie_id="TIE-1201-1405", reason=reason)


@pytest.mark.requirement("REQ-TIECAP-11")
def test_req_tiecap_11_blocked_tie_requires_both_fields():
    with pytest.raises(ValidationError):
        BlockedTie(tie_id="TIE-1201-1405")
    with pytest.raises(ValidationError):
        BlockedTie(reason="CAPACITY_UNKNOWN")


@pytest.mark.requirement("REQ-TIECAP-11")
def test_req_tiecap_11_restoration_plan_blocked_ties_defaults_empty():
    first = RestorationPlan(feeder_mrid="FDR-1201", faulted_section=None)
    second = RestorationPlan(feeder_mrid="FDR-1201", faulted_section=None)
    assert first.blocked_ties == []
    first.blocked_ties.append(BlockedTie(tie_id="TIE-1201-1405", reason="CAPACITY_STALE"))
    assert second.blocked_ties == []


@pytest.mark.requirement("REQ-TIECAP-11")
def test_req_tiecap_11_restoration_plan_carries_blocked_ties_in_order():
    plan = RestorationPlan(
        feeder_mrid="FDR-1201",
        faulted_section="SEC-1201-03",
        blocked_ties=[
            {"tie_id": "TIE-A", "reason": "FAULTED_SECTION"},
            {"tie_id": "TIE-B", "reason": "CAPACITY_EXCEEDED"},
        ],
    )
    assert plan.model_dump(mode="json")["blocked_ties"] == [
        {"tie_id": "TIE-A", "reason": "FAULTED_SECTION"},
        {"tie_id": "TIE-B", "reason": "CAPACITY_EXCEEDED"},
    ]


@pytest.mark.requirement("REQ-TIECAP-11")
def test_req_tiecap_11_restoration_plan_existing_fields_unchanged():
    # Additive only: the pre-existing fields and defaults are as on the base @ 20d2a30.
    plan = RestorationPlan(feeder_mrid="FDR-1201", faulted_section=None)
    dumped = plan.model_dump()
    assert {k: v for k, v in dumped.items() if k != "blocked_ties"} == {
        "feeder_mrid": "FDR-1201",
        "faulted_section": None,
        "isolation": [],
        "restoration": [],
        "customers_restored": 0,
        "customers_remaining": 0,
        "transferred_load_kw": 0.0,
        "notes": [],
    }
