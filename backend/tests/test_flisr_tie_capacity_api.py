"""POST /flisr/plan tie-capacity request validation and response (U3; REQ-TIECAP-8, 13..17, 23).

The server clock is fixed through ``app.dependency_overrides[api.server_now]`` so the as_of
bounds can be hit exactly. ``api.flisr.build_plan`` is wrapped by a recorder so every 422 test
can assert the planner never ran. The as_of bound oracle is a closed form with the spec's
literals (60 s, 2 s) and does not use the models.py constants (design section 6.3, O1).
"""

from __future__ import annotations

import ast
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.network import get_feeder, load_network, switch_by_mrid

TIE = "TIE-1201-1405"
NOW = datetime(2026, 10, 15, 22, 0, 0, tzinfo=UTC)
NOW_TS = "2026-10-15T22:00:00Z"


def oracle_as_of_ok(as_of: datetime, now: datetime) -> bool:
    """REQ-TIECAP-23 closed form: accepted iff now - 60 s <= as_of <= now + 2 s."""
    return now - as_of <= timedelta(seconds=60) and as_of - now <= timedelta(seconds=2)


def _forbidden_oracle_refs(source: str) -> list[str]:
    tree = ast.parse(source)
    found = []
    for func in tree.body:
        if isinstance(func, ast.FunctionDef) and func.name.startswith("oracle_"):
            for node in ast.walk(func):
                name = node.id if isinstance(node, ast.Name) else (
                    node.attr if isinstance(node, ast.Attribute) else ""
                )
                if name.startswith(("TIE_CAPACITY_", "AS_OF_")) or name in (
                    "api", "flisr", "network", "build_plan", "models", "_check_as_of_bound",
                ):
                    found.append(f"{func.name}: {name}")
    return found


def iso(instant: datetime) -> str:
    return instant.isoformat().replace("+00:00", "Z")


def entry(kw=2000.0, timestamp=NOW_TS, quality="GOOD", **extra) -> dict:
    return {"kw": kw, "timestamp": timestamp, "quality": quality, **extra}


def body(**fields) -> dict:
    return {"feeder_mrid": "FDR-1201", "lockout_switch_mrid": "CB-1201", **fields}


class Recorder:
    def __init__(self, real):
        self.real = real
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.real(*args, **kwargs)


def lockout_network(indicated: set[str] | None = None):
    network = load_network()
    feeder = get_feeder(network, "FDR-1201")
    if indicated is not None:
        for section in feeder.sections:
            section.fault_indicator = section.mrid in indicated
    switch_by_mrid(feeder, "CB-1201").open = True
    return network


@pytest.fixture
def planner(monkeypatch):
    recorder = Recorder(api.flisr.build_plan)
    monkeypatch.setattr(api.flisr, "build_plan", recorder)
    monkeypatch.setattr(api, "load_network", lockout_network)
    return recorder


@pytest.fixture
def client(planner):
    api.app.dependency_overrides[api.server_now] = lambda: NOW
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def post_raw(client: TestClient, payload):
    """Send `payload` as written by json.dumps (NaN / Infinity literals allowed)."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return client.post("/flisr/plan", content=text,
                       headers={"content-type": "application/json"})


@pytest.mark.requirement("REQ-TIECAP-23")
def test_req_tiecap_23_oracle_is_independent():
    assert _forbidden_oracle_refs(Path(__file__).read_text(encoding="utf-8")) == []


# ------------------------------------------------------------ REQ-TIECAP-13: 422 before the planner


MALFORMED = {
    "kw_string": body(tie_capacity={TIE: entry(kw="2000")}),
    "kw_bool": body(tie_capacity={TIE: entry(kw=True)}),
    "kw_null": body(tie_capacity={TIE: entry(kw=None)}),
    "timestamp_yesterday": body(tie_capacity={TIE: entry(timestamp="yesterday")}),
    "timestamp_number": body(tie_capacity={TIE: entry(timestamp=1790000000)}),
    "timestamp_numeric_string": body(tie_capacity={TIE: entry(timestamp="1790000000")}),
    "timestamp_naive": body(tie_capacity={TIE: entry(timestamp="2026-10-15T22:00:00")}),
    "quality_number": body(tie_capacity={TIE: entry(quality=1)}),
    "entry_extra_field": body(tie_capacity={TIE: entry(source="SCADA")}),
    "entry_missing_quality": body(tie_capacity={TIE: {"kw": 2000.0, "timestamp": NOW_TS}}),
    "entry_not_object": body(tie_capacity={TIE: 2000.0}),
    "tie_capacity_null": body(tie_capacity=None),
    "tie_capacity_list": body(tie_capacity=[]),
    "legacy_null": body(tie_capacity_kw=None),
    "legacy_string": body(tie_capacity_kw={TIE: "2000"}),
    "legacy_bool": body(tie_capacity_kw={TIE: True}),
    "body_extra_field": body(tie_capacity={TIE: entry()}, operator="night shift"),
    "feeder_number": {"feeder_mrid": 1201, "lockout_switch_mrid": "CB-1201"},
    "missing_lockout": {"feeder_mrid": "FDR-1201"},
    "as_of_null": body(as_of=None),
    "as_of_naive": body(as_of="2026-10-15T22:00:00"),
    "as_of_yesterday": body(as_of="yesterday"),
    "as_of_number": body(as_of=1790000000),
    "as_of_numeric_string": body(as_of="1790000000"),
    "both_maps": body(tie_capacity={TIE: entry()}, tie_capacity_kw={TIE: 2000.0}),
    "both_maps_empty": body(tie_capacity={}, tie_capacity_kw={}),
    "as_of_60.001s_behind": body(as_of=iso(NOW - timedelta(seconds=60, milliseconds=1))),
    "as_of_2.001s_ahead": body(as_of=iso(NOW + timedelta(seconds=2, milliseconds=1))),
}


@pytest.mark.requirement("REQ-TIECAP-13")
@pytest.mark.requirement("REQ-TIECAP-15")
@pytest.mark.requirement("REQ-TIECAP-23")
@pytest.mark.parametrize("payload", MALFORMED.values(), ids=MALFORMED)
def test_req_tiecap_13_malformed_body_is_422_and_planner_not_called(client, planner, payload):
    response = post_raw(client, payload)
    assert response.status_code == 422, response.text
    assert planner.calls == []
    detail = response.json()["detail"]
    assert detail and all(set(item) == {"type", "loc", "msg"} for item in detail)


NON_FINITE_IN_REJECTED_BODY = {
    "nan_missing_quality": body(tie_capacity={TIE: {"kw": math.nan, "timestamp": NOW_TS}}),
    "inf_extra_field": body(tie_capacity={TIE: entry(kw=math.inf, source="x")}),
    "nan_and_both_maps": body(tie_capacity={TIE: entry(kw=math.nan)},
                              tie_capacity_kw={TIE: math.nan}),
    "nan_extra_body_field": body(tie_capacity_kw={TIE: -math.inf}, extra=math.nan),
}


@pytest.mark.requirement("REQ-TIECAP-13")
@pytest.mark.parametrize(
    "payload", NON_FINITE_IN_REJECTED_BODY.values(), ids=NON_FINITE_IN_REJECTED_BODY
)
def test_req_tiecap_13_rejected_body_with_non_finite_input_is_422_not_500(client, planner, payload):
    """F-QA-U2-1: the 422 body never echoes the (unserialisable) rejected input."""
    response = post_raw(client, payload)
    assert response.status_code == 422, response.text
    assert planner.calls == []
    assert '"input"' not in response.text
    assert "NaN" not in response.text and "Infinity" not in response.text


@pytest.mark.requirement("REQ-TIECAP-13")
def test_req_tiecap_13_blocked_tie_is_200_with_blocked_ties(client, planner):
    response = post_raw(client, body(tie_capacity={}))
    assert response.status_code == 200
    plan = response.json()
    assert plan["blocked_ties"] == [{"tie_id": TIE, "reason": "CAPACITY_UNKNOWN"}]
    assert ("TIE-1201-1405", "close") not in [
        (s["switch_mrid"], s["action"]) for s in plan["restoration"]
    ]
    assert len(planner.calls) == 1


@pytest.mark.requirement("REQ-TIECAP-8")
@pytest.mark.requirement("REQ-TIECAP-13")
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "-1", "-1.0"])
@pytest.mark.parametrize("field", ["tie_capacity", "tie_capacity_kw"])
def test_req_tiecap_8_non_finite_or_negative_json_capacity_is_200_invalid(client, field, literal):
    value = (f'{{"kw": {literal}, "timestamp": "{NOW_TS}", "quality": "GOOD"}}'
             if field == "tie_capacity" else literal)
    text = (f'{{"feeder_mrid": "FDR-1201", "lockout_switch_mrid": "CB-1201", '
            f'"{field}": {{"{TIE}": {value}}}}}')
    response = post_raw(client, text)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["blocked_ties"] == [{"tie_id": TIE, "reason": "CAPACITY_INVALID"}]
    assert plan["customers_restored"] == 0


@pytest.mark.requirement("REQ-TIECAP-13")
def test_req_tiecap_13_http_plan_equals_direct_plan(client):
    capacities = {TIE: entry(kw=1489.5, timestamp=iso(NOW - timedelta(seconds=5)))}
    response = post_raw(client, body(tie_capacity=capacities, as_of=NOW_TS))
    assert response.status_code == 200
    feeder = get_feeder(lockout_network(), "FDR-1201")
    direct = api.flisr.build_plan.real(
        feeder, "CB-1201",
        tie_capacity={TIE: api.TieCapacity.model_validate(capacities[TIE])}, as_of=NOW,
    )
    assert response.json() == direct.model_dump(mode="json")
    assert [s["switch_mrid"] for s in response.json()["restoration"]] == ["CB-1201", TIE]


@pytest.mark.requirement("REQ-TIECAP-13")
def test_req_tiecap_13_stale_capacity_over_http(client):
    stale = entry(timestamp=iso(NOW - timedelta(seconds=20, milliseconds=1)))
    response = post_raw(client, body(tie_capacity={TIE: stale}))
    assert response.status_code == 200
    assert response.json()["blocked_ties"] == [{"tie_id": TIE, "reason": "CAPACITY_STALE"}]


@pytest.mark.requirement("REQ-TIECAP-13")
def test_req_tiecap_13_unknown_feeder_is_still_404(client):
    response = post_raw(client, body(feeder_mrid="FDR-NOPE", tie_capacity={}))
    assert response.status_code == 404


@pytest.mark.requirement("REQ-TIECAP-13")
def test_req_tiecap_13_invalid_section_load_is_409_without_a_plan(client, monkeypatch):
    def nan_load_network():
        network = lockout_network()
        feeder = get_feeder(network, "FDR-1201")
        next(s for s in feeder.sections if s.mrid == "SEC-1201-04").load_kw = math.nan
        return network

    monkeypatch.setattr(api, "load_network", nan_load_network)
    response = post_raw(client, body(tie_capacity={TIE: entry()}))
    assert response.status_code == 409
    assert set(response.json()) == {"detail"}
    assert "no plan" in response.json()["detail"]


@pytest.mark.requirement("REQ-TIECAP-13")
def test_req_tiecap_13_held_tie_is_200_faulted_section(client, monkeypatch):
    monkeypatch.setattr(
        api, "load_network",
        lambda: lockout_network({"SEC-1201-01", "SEC-1201-02", "SEC-1201-03"}),
    )
    response = post_raw(client, body(tie_capacity={TIE: entry()}))
    assert response.status_code == 200
    assert response.json()["blocked_ties"] == [{"tie_id": TIE, "reason": "FAULTED_SECTION"}]


# ---------------------------------------------------------------- REQ-TIECAP-14: as_of echo


@pytest.mark.requirement("REQ-TIECAP-14")
def test_req_tiecap_14_offset_as_of_echoed_as_utc_instant(client, planner):
    response = post_raw(client, body(tie_capacity={}, as_of="2026-10-15T23:00:00+01:00"))
    assert response.status_code == 200
    echoed = datetime.fromisoformat(response.json()["as_of"])
    assert echoed == NOW and echoed.utcoffset() == timedelta(0)
    assert planner.calls[0][1]["as_of"] == NOW


@pytest.mark.requirement("REQ-TIECAP-14")
def test_req_tiecap_14_absent_as_of_is_server_now(client, planner):
    response = post_raw(client, body(tie_capacity={}))
    assert datetime.fromisoformat(response.json()["as_of"]) == NOW
    assert planner.calls[0][1]["as_of"] == NOW


@pytest.mark.requirement("REQ-TIECAP-14")
def test_req_tiecap_14_absent_as_of_uses_the_real_clock(planner):
    real = TestClient(api.app)
    before = datetime.now(UTC)
    response = post_raw(real, body(tie_capacity={}))
    after = datetime.now(UTC)
    echoed = datetime.fromisoformat(response.json()["as_of"])
    assert before <= echoed <= after
    assert echoed.utcoffset() == timedelta(0)


# ---------------------------------------------------------------- REQ-TIECAP-23: as_of bound


AS_OF_OFFSETS_MS = [-60_001, -60_000, -59_999, -1, 0, 1, 1_999, 2_000, 2_001]


@pytest.mark.requirement("REQ-TIECAP-23")
@pytest.mark.parametrize("offset_ms", AS_OF_OFFSETS_MS)
def test_req_tiecap_23_as_of_bound_against_oracle(client, planner, offset_ms):
    as_of = NOW + timedelta(milliseconds=offset_ms)
    response = post_raw(client, body(tie_capacity={}, as_of=iso(as_of)))
    if oracle_as_of_ok(as_of, NOW):
        assert response.status_code == 200, response.text
        assert datetime.fromisoformat(response.json()["as_of"]) == as_of
        assert len(planner.calls) == 1
    else:
        assert response.status_code == 422
        assert planner.calls == []
        assert response.json()["detail"][0]["loc"] == ["body", "as_of"]


@pytest.mark.requirement("REQ-TIECAP-23")
def test_req_tiecap_23_oracle_boundaries():
    assert oracle_as_of_ok(NOW - timedelta(seconds=60), NOW)
    assert oracle_as_of_ok(NOW + timedelta(seconds=2), NOW)
    assert not oracle_as_of_ok(NOW - timedelta(seconds=60, milliseconds=1), NOW)
    assert not oracle_as_of_ok(NOW + timedelta(seconds=2, milliseconds=1), NOW)


@pytest.mark.requirement("REQ-TIECAP-23")
@pytest.mark.parametrize(
    ("as_of", "status"),
    [("2026-10-16T00:00:02+02:00", 200), ("2026-10-16T00:00:02.001+02:00", 422),
     ("2026-10-15T16:59:00-05:00", 200), ("2026-10-15T16:58:59.999-05:00", 422)],
)
def test_req_tiecap_23_offset_as_of_bounded_on_the_same_instant(client, as_of, status):
    assert post_raw(client, body(tie_capacity={}, as_of=as_of)).status_code == status


# ---------------------------------------------------------------- REQ-TIECAP-15 / 16: legacy map


@pytest.mark.requirement("REQ-TIECAP-16")
@pytest.mark.parametrize("capacity_kw", [2000.0, 1490.0, 1489.4])
def test_req_tiecap_16_legacy_only_matches_good_entry_and_is_flagged(client, capacity_kw):
    legacy = post_raw(client, body(tie_capacity_kw={TIE: capacity_kw})).json()
    new = post_raw(client, body(tie_capacity={TIE: entry(kw=capacity_kw)})).json()
    assert legacy["deprecations"] == ["tie_capacity_kw"]
    assert new["deprecations"] == []
    assert {k: v for k, v in legacy.items() if k != "deprecations"} == {
        k: v for k, v in new.items() if k != "deprecations"
    }


@pytest.mark.requirement("REQ-TIECAP-16")
def test_req_tiecap_16_legacy_json_integer_is_accepted(client):
    response = post_raw(client, '{"feeder_mrid": "FDR-1201", "lockout_switch_mrid": "CB-1201", '
                                f'"tie_capacity_kw": {{"{TIE}": 2000}}}}')
    assert response.status_code == 200
    assert response.json()["customers_restored"] == 341


@pytest.mark.requirement("REQ-TIECAP-16")
def test_req_tiecap_16_neither_map_blocks_unknown_without_deprecation(client):
    plan = post_raw(client, body()).json()
    assert plan["blocked_ties"] == [{"tie_id": TIE, "reason": "CAPACITY_UNKNOWN"}]
    assert plan["deprecations"] == []


# ---------------------------------------------------------------- REQ-TIECAP-17: OpenAPI note


@pytest.mark.requirement("REQ-TIECAP-17")
def test_req_tiecap_17_openapi_description_carries_deprecation_note():
    description = api.app.openapi()["paths"]["/flisr/plan"]["post"]["description"]
    assert "`tie_capacity_kw` is deprecated and will be removed one release after this one" in (
        description
    )
    assert "mutually exclusive with `tie_capacity`; sending both returns 422" in description
    assert "quality GOOD with timestamp = `as_of`" in description
    assert "0.5 kW" in description and "20 s" in description
    assert "60 s before and 2 s after the server clock" in description
