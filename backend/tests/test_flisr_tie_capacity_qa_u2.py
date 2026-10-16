"""Independent QA oracle for U2 (REQ-TIECAP-1, REQ-TIECAP-11).

QA-owned closed-form oracle for the TieCapacity accept/reject contract, restated from the
specification literals (REQ-TIECAP-1, Q-SPEC-9, Q-SPEC-13), not from ``app.models``. It is
compared with the production model over the brief's named vectors and over 600 seeded random
request bodies, through both validation paths: ``model_validate_json`` (JSON mode) and a FastAPI
``TestClient`` route whose body nests ``dict[str, TieCapacity]`` exactly as ``POST /flisr/plan``
will (Python mode). ``app.models`` is imported for its data types only; ``app.flisr`` and
``app.network`` are not imported (design section 6.3, Q-DESIGN-1).
"""

from __future__ import annotations

import ast
import json
import math
import random
import re
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app import models
from app.models import BlockedTie, RestorationPlan, TieBlockReason, TieCapacity

pytestmark = pytest.mark.requirement("REQ-TIECAP-1")

# ---------------------------------------------------------------------------------------------
# Oracle (spec literals only)
# ---------------------------------------------------------------------------------------------

ORACLE_FIELDS = frozenset({"kw", "timestamp", "quality"})

# Strict ISO-8601 extended profile with a mandatory UTC designator or numeric offset
# (REQ-TIECAP-1: "strict timezone-aware ISO-8601 datetime"). Lower-case designators, week
# dates, ordinal dates and basic format are outside the oracle profile and are not generated.
_ISO_AWARE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})T(?P<h>\d{2}):(?P<mi>\d{2})"
    r"(?::(?P<s>\d{2})(?:\.(?P<f>\d{1,6}))?)?"
    r"(?P<tz>Z|[+-]\d{2}:\d{2})$"
)


def oracle_parse_timestamp(value: object) -> datetime | None:
    """Return the instant for an accepted timestamp, None when the oracle rejects it."""
    if not isinstance(value, str):
        return None  # JSON number, null, bool, array, object: reject (Q-SPEC-13)
    m = _ISO_AWARE.match(value)
    if m is None:
        return None  # non-ISO string, date-only, naive: reject
    try:
        base = datetime(
            int(m["y"]),
            int(m["mo"]),
            int(m["d"]),
            int(m["h"]),
            int(m["mi"]),
            int(m["s"] or 0),
            int((m["f"] or "0").ljust(6, "0")),
        )
    except ValueError:
        return None  # out-of-range calendar fields
    tz = m["tz"]
    if tz == "Z":
        offset = timedelta(0)
    else:
        sign = 1 if tz[0] == "+" else -1
        hours, minutes = int(tz[1:3]), int(tz[4:6])
        if hours > 23 or minutes > 59:
            return None
        offset = sign * timedelta(hours=hours, minutes=minutes)
    return base.replace(tzinfo=timezone(offset)).astimezone(UTC)


def oracle_kw_ok(value: object) -> bool:
    # A JSON number: int or float, never bool (a JSON true/false), never a string or null.
    # No range check: NaN, +-inf and negative numbers pass (REQ-TIECAP-1, REQ-TIECAP-8).
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def oracle_quality_ok(value: object) -> bool:
    return isinstance(value, str)


def oracle_accepts(body: object) -> bool:
    if not isinstance(body, dict) or set(body) != ORACLE_FIELDS:
        return False  # missing or unknown field
    return (
        oracle_kw_ok(body["kw"])
        and oracle_parse_timestamp(body["timestamp"]) is not None
        and oracle_quality_ok(body["quality"])
    )


# ---------------------------------------------------------------------------------------------
# HTTP path: the body shape POST /flisr/plan will use
# ---------------------------------------------------------------------------------------------

qa_app = FastAPI()


@qa_app.exception_handler(RequestValidationError)
def _validation_error_without_input_echo(_: Request, exc: RequestValidationError) -> JSONResponse:
    # QA finding for U3, not a U2 defect: FastAPI's default 422 handler echoes the offending
    # input. When a body is rejected for a missing field and carries a non-finite kw
    # (JSON NaN / Infinity), that echo is not JSON-serialisable and the default handler turns
    # the 422 into a 500. The QA harness drops the echo so the validation verdict is what is
    # measured; the production endpoint (U3, REQ-TIECAP-13) has to handle this itself.
    return JSONResponse(
        status_code=422,
        content={"detail": [{"type": e["type"], "loc": list(e["loc"])} for e in exc.errors()]},
    )


class _PlanLikeBody(BaseModel):
    tie_capacity: dict[str, TieCapacity]


@qa_app.post("/qa/tie-capacity")
def echo_tie_capacity(body: _PlanLikeBody) -> dict:
    entry = body.tie_capacity["TIE-1201-1405"]
    return {
        "kw": repr(entry.kw),
        "timestamp_utc": entry.timestamp.astimezone(UTC).isoformat(),
        "quality": entry.quality,
    }


@qa_app.post("/qa/plan")
def echo_plan(plan: RestorationPlan) -> RestorationPlan:
    return plan


client = TestClient(qa_app)


def http_status(entry_json: str) -> tuple[int, dict | None]:
    response = client.post(
        "/qa/tie-capacity",
        content='{"tie_capacity": {"TIE-1201-1405": ' + entry_json + "}}",
        headers={"content-type": "application/json"},
    )
    return response.status_code, (response.json() if response.status_code == 200 else None)


def json_accepts(entry_json: str) -> TieCapacity | None:
    try:
        return TieCapacity.model_validate_json(entry_json)
    except ValidationError:
        return None


def same_kw(a: float, b: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or a == b


def check_agreement(body: object) -> None:
    text = json.dumps(body)  # writes NaN / Infinity / -Infinity literals
    expected = oracle_accepts(body)
    parsed = json_accepts(text)
    status, echoed = http_status(text)

    assert (parsed is not None) == expected, (text, "JSON path")
    assert status == (200 if expected else 422), (text, "HTTP path", status)
    if expected:
        instant = oracle_parse_timestamp(body["timestamp"])
        assert parsed.timestamp == instant, text
        assert same_kw(parsed.kw, float(body["kw"])), text
        assert parsed.quality == body["quality"], text
        assert datetime.fromisoformat(echoed["timestamp_utc"]) == instant, text
        assert same_kw(float(echoed["kw"]), float(body["kw"])), text
        assert echoed["quality"] == body["quality"], text


# ---------------------------------------------------------------------------------------------
# Brief vectors (unit U2 "oracle" field) and boundary vectors
# ---------------------------------------------------------------------------------------------

GOOD = {"kw": 1490.0, "timestamp": "2026-10-15T22:00:00Z", "quality": "GOOD"}


def body(**overrides) -> dict:
    out = dict(GOOD)
    out.update(overrides)
    return out


BRIEF_VECTORS = {
    "reject_timestamp_yesterday": body(timestamp="yesterday"),
    "reject_timestamp_unix_number": body(timestamp=1790000000),
    "reject_timestamp_unix_float": body(timestamp=1790000000.0),
    "reject_timestamp_unix_string": body(timestamp="1790000000"),
    "reject_timestamp_naive": body(timestamp="2026-10-15T22:00:00"),
    "reject_timestamp_naive_fraction": body(timestamp="2026-10-15T22:00:00.250"),
    "reject_timestamp_date_only": body(timestamp="2026-10-15"),
    "reject_timestamp_null": body(timestamp=None),
    "reject_timestamp_bool": body(timestamp=True),
    "reject_timestamp_empty": body(timestamp=""),
    "reject_timestamp_offset_24h": body(timestamp="2026-10-15T22:00:00+24:00"),
    "reject_timestamp_hour_24": body(timestamp="2026-10-15T24:00:00Z"),
    "reject_timestamp_month_13": body(timestamp="2026-13-15T22:00:00Z"),
    "reject_kw_string": body(kw="2000"),
    "reject_kw_nan_string": body(kw="NaN"),
    "reject_kw_true": body(kw=True),
    "reject_kw_false": body(kw=False),
    "reject_kw_null": body(kw=None),
    "reject_kw_array": body(kw=[1490.0]),
    "reject_quality_number": body(quality=0),
    "reject_quality_null": body(quality=None),
    "reject_quality_bool": body(quality=False),
    "reject_quality_array": body(quality=["GOOD"]),
    "reject_extra_field": body(source="SCADA"),
    "reject_extra_field_case_variant": body(KW=1490.0),
    "reject_missing_kw": {"timestamp": GOOD["timestamp"], "quality": "GOOD"},
    "reject_missing_timestamp": {"kw": 1490.0, "quality": "GOOD"},
    "reject_missing_quality": {"kw": 1490.0, "timestamp": GOOD["timestamp"]},
    "reject_empty_object": {},
    "accept_nominal": body(),
    "accept_kw_nan": body(kw=math.nan),
    "accept_kw_pos_inf": body(kw=math.inf),
    "accept_kw_neg_inf": body(kw=-math.inf),
    "accept_kw_negative": body(kw=-1.0),
    "accept_kw_zero": body(kw=0.0),
    "accept_kw_neg_zero": body(kw=-0.0),
    "accept_kw_integer_literal": body(kw=1490),
    "accept_kw_tolerance_boundary": body(kw=1489.5),
    "accept_kw_just_below_boundary": body(kw=1489.4),
    "accept_offset_plus_02_00": body(timestamp="2026-10-16T00:00:00+02:00"),
    "accept_offset_minus_05_00": body(timestamp="2026-10-15T17:00:00-05:00"),
    "accept_offset_plus_00_00": body(timestamp="2026-10-15T22:00:00+00:00"),
    "accept_fractional_seconds": body(timestamp="2026-10-15T22:00:00.123456Z"),
    "accept_no_seconds": body(timestamp="2026-10-15T22:00Z"),
    "accept_far_past": body(timestamp="2000-01-01T00:00:00Z"),
    "accept_far_future": body(timestamp="2100-01-01T00:00:00Z"),
    "accept_quality_bad": body(quality="BAD"),
    "accept_quality_lowercase_good": body(quality="good"),
    "accept_quality_empty": body(quality=""),
}


@pytest.mark.parametrize("case", sorted(BRIEF_VECTORS))
def test_qa_u2_brief_vector_agrees_with_oracle(case):
    expected = case.startswith("accept_")
    assert oracle_accepts(BRIEF_VECTORS[case]) is expected, "oracle self-check"
    check_agreement(BRIEF_VECTORS[case])


# ---------------------------------------------------------------------------------------------
# Seeded random bodies (STD-SAFETY-5 style: >= 500 generated inputs)
# ---------------------------------------------------------------------------------------------

SEED = 20261016
CASES = 600


def _random_offset(rng: random.Random) -> str:
    if rng.random() < 0.3:
        return "Z"
    return f"{rng.choice('+-')}{rng.randrange(0, 24):02d}:{rng.choice([0, 15, 30, 45]):02d}"


def _random_timestamp(rng: random.Random) -> object:
    roll = rng.random()
    stamp = (
        f"{rng.randrange(1970, 2101):04d}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}"
        f"T{rng.randrange(0, 24):02d}:{rng.randrange(0, 60):02d}:{rng.randrange(0, 60):02d}"
    )
    if roll < 0.45:
        frac = f".{rng.randrange(0, 1_000_000):06d}" if rng.random() < 0.3 else ""
        return stamp + frac + _random_offset(rng)  # aware: accept
    if roll < 0.60:
        return stamp  # naive: reject
    if roll < 0.70:
        return rng.randrange(0, 2_000_000_000)  # unix number: reject
    if roll < 0.78:
        return str(rng.randrange(0, 2_000_000_000))  # numeric string: reject
    if roll < 0.86:
        return rng.choice(["yesterday", "", "now", "2026-10-15", "22:00:00Z", "T22:00:00Z"])
    if roll < 0.92:
        return stamp + f"+{rng.randrange(24, 100):02d}:00"  # offset out of range: reject
    return rng.choice([None, True, False, [stamp + "Z"], {"iso": stamp + "Z"}, 1.5])


def _random_kw(rng: random.Random) -> object:
    roll = rng.random()
    if roll < 0.40:
        return round(rng.uniform(-5000.0, 5000.0), rng.randrange(0, 4))
    if roll < 0.55:
        return rng.choice([math.nan, math.inf, -math.inf, -1.0, 0.0, -0.0, 1489.5, 1490.0])
    if roll < 0.65:
        return rng.randrange(-100, 5000)  # JSON integer literal: accept
    if roll < 0.80:
        return rng.choice(["2000", "1490.0", "NaN", "", "GOOD"])  # string: reject
    return rng.choice([True, False, None, [1490.0], {"kw": 1490.0}])


def _random_quality(rng: random.Random) -> object:
    roll = rng.random()
    if roll < 0.65:
        return rng.choice(["GOOD", "BAD", "SUSPECT", "good", "", "UNCERTAIN", "Good "])
    return rng.choice([0, 1, 1.0, True, False, None, ["GOOD"], {"q": "GOOD"}])


def random_body(rng: random.Random) -> dict:
    out = {
        "kw": _random_kw(rng),
        "timestamp": _random_timestamp(rng),
        "quality": _random_quality(rng),
    }
    roll = rng.random()
    if roll < 0.07:
        del out[rng.choice(sorted(out))]  # missing field: reject
    elif roll < 0.14:
        out[rng.choice(["source", "unit", "KW", "ts", "quality_code"])] = "x"  # extra: reject
    return out


def test_qa_u2_seeded_bodies_agree_with_oracle_on_both_paths():
    rng = random.Random(SEED)
    accepted = rejected = 0
    for _ in range(CASES):
        candidate = random_body(rng)
        check_agreement(candidate)
        if oracle_accepts(candidate):
            accepted += 1
        else:
            rejected += 1
    assert accepted + rejected == CASES
    # Both classes must be well represented or the agreement claim is hollow.
    assert accepted >= 100, accepted
    assert rejected >= 100, rejected


# ---------------------------------------------------------------------------------------------
# Python-mode callers (build_plan / api.py construct TieCapacity directly)
# ---------------------------------------------------------------------------------------------

AWARE = datetime(2026, 10, 15, 22, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kw": 1490.0, "timestamp": AWARE, "quality": "GOOD"},
        {
            "kw": 1490.0,
            "timestamp": AWARE.astimezone(timezone(timedelta(hours=2))),
            "quality": "GOOD",
        },
        {"kw": 1490.0, "timestamp": "2026-10-15T22:00:00Z", "quality": "GOOD"},
        {"kw": 1490, "timestamp": AWARE, "quality": "GOOD"},
        {"kw": math.nan, "timestamp": AWARE, "quality": "GOOD"},
    ],
)
def test_qa_u2_python_mode_accepts(kwargs):
    tc = TieCapacity(**kwargs)
    assert tc.timestamp == AWARE
    assert tc.timestamp.utcoffset() is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kw": 1490.0, "timestamp": AWARE.replace(tzinfo=None), "quality": "GOOD"},
        {"kw": 1490.0, "timestamp": AWARE.date(), "quality": "GOOD"},
        {"kw": 1490.0, "timestamp": 1790000000, "quality": "GOOD"},
        {"kw": 1490.0, "timestamp": 1790000000.0, "quality": "GOOD"},
        {"kw": 1490.0, "timestamp": b"2026-10-15T22:00:00Z", "quality": "GOOD"},
        {"kw": "1490.0", "timestamp": AWARE, "quality": "GOOD"},
        {"kw": True, "timestamp": AWARE, "quality": "GOOD"},
        {"kw": 1490.0, "timestamp": AWARE, "quality": b"GOOD"},
        {"kw": 1490.0, "timestamp": AWARE, "quality": "GOOD", "source": "SCADA"},
    ],
)
def test_qa_u2_python_mode_rejects(kwargs):
    with pytest.raises(ValidationError):
        TieCapacity(**kwargs)


# ---------------------------------------------------------------------------------------------
# Model-wide properties
# ---------------------------------------------------------------------------------------------

_CLOCK_NAMES = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "fromtimestamp"}


def test_qa_u2_models_module_reads_no_clock():
    # REQ-TIECAP-1: the model never compares a timestamp with a clock (Q-SPEC-10 puts the time
    # reference in build_plan / api.py). No clock call or `time` import may appear in models.py.
    tree = ast.parse(Path(models.__file__).read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _CLOCK_NAMES:
            offenders.append(f"line {node.lineno}: .{node.attr}")
        if isinstance(node, ast.Name) and node.id in _CLOCK_NAMES:
            offenders.append(f"line {node.lineno}: {node.id}")
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "time" for a in node.names):
            offenders.append(f"line {node.lineno}: import time")
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            offenders.append(f"line {node.lineno}: from time import")
    assert offenders == []


def test_qa_u2_models_module_imports_no_app_module():
    tree = ast.parse(Path(models.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module.split(".")[0] in set(sys.stdlib_module_names) | {"pydantic"}
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in set(sys.stdlib_module_names) | {"pydantic"}


def test_qa_u2_tie_capacity_fields_have_no_defaults():
    # STD-QA-4 missing-as-zero: every field is required; a missing capacity can never read as 0.
    for name in ("kw", "timestamp", "quality"):
        assert TieCapacity.model_fields[name].is_required(), name
    assert set(TieCapacity.model_fields) == ORACLE_FIELDS
    assert TieCapacity.model_config.get("extra") == "forbid"


def test_qa_u2_tie_capacity_openapi_schema_is_strict_object():
    schema = qa_app.openapi()["components"]["schemas"]["TieCapacity"]
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(ORACLE_FIELDS)
    assert schema["properties"]["kw"] == {"title": "Kw", "type": "number"}
    assert schema["properties"]["timestamp"]["type"] == "string"
    assert schema["properties"]["timestamp"]["format"] == "date-time"
    assert schema["properties"]["quality"]["type"] == "string"


# ---------------------------------------------------------------------------------------------
# REQ-TIECAP-11: BlockedTie, TieBlockReason, RestorationPlan.blocked_ties
# ---------------------------------------------------------------------------------------------

# Spec REQ-TIECAP-11 amended by Q-DESIGN-3: FAULTED_SECTION ahead of every capacity reason.
EXPECTED_REASONS = [
    "FAULTED_SECTION",
    "CAPACITY_INVALID",
    "CAPACITY_UNKNOWN",
    "CAPACITY_STALE",
    "CAPACITY_EXCEEDED",
]

# RestorationPlan fields and defaults on the base (agent/rca-backfeed/fix @ 20d2a30).
BASE_PLAN_FIELDS = {
    "feeder_mrid": "FDR-1201",
    "faulted_section": None,
    "isolation": [],
    "restoration": [],
    "customers_restored": 0,
    "customers_remaining": 0,
    "transferred_load_kw": 0.0,
    "notes": [],
}


@pytest.mark.requirement("REQ-TIECAP-11")
def test_qa_u2_block_reason_enum_members_and_order():
    assert [m.value for m in TieBlockReason] == EXPECTED_REASONS
    assert [m.name for m in TieBlockReason] == EXPECTED_REASONS
    assert all(isinstance(m, str) for m in TieBlockReason)
    assert qa_app.openapi()["components"]["schemas"]["TieBlockReason"]["enum"] == EXPECTED_REASONS


@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.parametrize("reason", EXPECTED_REASONS)
def test_qa_u2_blocked_tie_accepts_each_reason_by_value(reason):
    blocked = BlockedTie.model_validate_json(
        json.dumps({"tie_id": "TIE-1201-1405", "reason": reason})
    )
    assert blocked.tie_id == "TIE-1201-1405"
    assert blocked.reason == reason
    assert blocked.model_dump(mode="json") == {"tie_id": "TIE-1201-1405", "reason": reason}


@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.parametrize(
    "payload",
    [
        {"tie_id": "TIE-1201-1405", "reason": "CAPACITY_LOW"},
        {"tie_id": "TIE-1201-1405", "reason": "capacity_exceeded"},
        {"tie_id": "TIE-1201-1405", "reason": "FAULTED_SECTION "},
        {"tie_id": "TIE-1201-1405", "reason": 0},
        {"tie_id": "TIE-1201-1405", "reason": None},
        {"tie_id": "TIE-1201-1405"},
        {"reason": "CAPACITY_UNKNOWN"},
        {"tie_id": 1405, "reason": "CAPACITY_UNKNOWN"},
        {"tie_id": None, "reason": "CAPACITY_UNKNOWN"},
    ],
)
def test_qa_u2_blocked_tie_rejects_malformed(payload):
    with pytest.raises(ValidationError):
        BlockedTie.model_validate(payload)


@pytest.mark.requirement("REQ-TIECAP-11")
def test_qa_u2_restoration_plan_is_additive_with_empty_default():
    plan = RestorationPlan.model_validate({"feeder_mrid": "FDR-1201", "faulted_section": None})
    dumped = plan.model_dump()
    assert dumped.pop("blocked_ties") == []
    assert dumped == BASE_PLAN_FIELDS
    assert list(RestorationPlan.model_fields) == [*BASE_PLAN_FIELDS, "blocked_ties"]

    # A base-shaped JSON document (no blocked_ties key) still validates: additive only.
    legacy = RestorationPlan.model_validate_json(json.dumps(BASE_PLAN_FIELDS))
    assert legacy.blocked_ties == []

    # Default is per instance, not shared.
    other = RestorationPlan(feeder_mrid="FDR-1201", faulted_section=None)
    plan.blocked_ties.append(BlockedTie(tie_id="TIE-1201-1405", reason="CAPACITY_STALE"))
    assert other.blocked_ties == []


@pytest.mark.requirement("REQ-TIECAP-11")
def test_qa_u2_restoration_plan_blocked_ties_round_trip_over_http_preserves_order():
    blocked = [
        {"tie_id": "TIE-1201-1405", "reason": "FAULTED_SECTION"},
        {"tie_id": "TIE-1201-1406", "reason": "CAPACITY_EXCEEDED"},
        {"tie_id": "TIE-1201-1407", "reason": "CAPACITY_UNKNOWN"},
    ]
    payload = dict(BASE_PLAN_FIELDS, faulted_section="SEC-1201-03", blocked_ties=blocked)
    response = client.post("/qa/plan", json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == payload
    schema = qa_app.openapi()["components"]["schemas"]["RestorationPlan"]
    assert schema["properties"]["blocked_ties"]["items"] == {
        "$ref": "#/components/schemas/BlockedTie"
    }
    assert "blocked_ties" not in schema.get("required", [])


@pytest.mark.requirement("REQ-TIECAP-11")
@pytest.mark.parametrize(
    "blocked_ties",
    [None, "TIE-1201-1405", [{"tie_id": "TIE-1201-1405", "reason": "LOW"}], [{"tie_id": "T"}]],
)
def test_qa_u2_restoration_plan_rejects_malformed_blocked_ties(blocked_ties):
    with pytest.raises(ValidationError):
        RestorationPlan(feeder_mrid="FDR-1201", faulted_section=None, blocked_ties=blocked_ties)
