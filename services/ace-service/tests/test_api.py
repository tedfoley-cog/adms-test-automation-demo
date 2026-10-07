"""HTTP contract and input refusals of the ACE service (spec §5.2, §6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ace_service.hdb_export import SavecaseError, parse_export, split_fields
from ace_service.service import MAX_SAVECASE_BYTES, app

client = TestClient(app)


def area(**overrides):
    body = {
        "savecase": "API",
        "frequency": {"actual_hz": 59.98, "bias_mw_per_0_1hz": -500.0},
        "meter_error_mw": 0.0,
        "tie_lines": [{"id": "TIE.A", "actual_mw": 150.0, "scheduled_mw": 100.0}],
        "units": [
            {
                "id": "GEN.A",
                "output_mw": 100.0,
                "min_mw": 50.0,
                "max_mw": 200.0,
                "ramp_mw_per_min": 600.0,
                "participation": 1.0,
                "on_agc": True,
            }
        ],
    }
    body.update(overrides)
    return body


def unit(**overrides):
    base = area()["units"][0]
    base.update(overrides)
    return base


def test_health():
    assert client.get("/health").json() == {
        "status": "ok",
        "service": "ace-service",
        "legacy_task": "RTGENACE",
        "version": "1.0.0",
    }


def test_dispatch_json():
    body = client.post("/v1/rtgenace/dispatch", json=area()).json()

    assert body["ace_mw"] == -50.0
    assert body["in_deadband"] is False
    assert body["deadband_mw"] == 5.0 and body["control_cycle_s"] == 4.0
    assert body["setpoints"] == [
        {"unit": "GEN.A", "setpoint_delta_mw": 40.0, "target_mw": 140.0, "participating": True}
    ]
    assert body["warnings"] == []


def test_dispatch_in_deadband_reports_zero_moves():
    body = client.post(
        "/v1/rtgenace/dispatch",
        json=area(frequency={"actual_hz": 60.0, "bias_mw_per_0_1hz": -500.0}, tie_lines=[], meter_error_mw=-5.0),
    ).json()
    assert body["in_deadband"] is True
    assert body["setpoints"][0]["setpoint_delta_mw"] == 0.0


def test_tie_line_quality_warning():
    body = client.post(
        "/v1/rtgenace/dispatch",
        json=area(tie_lines=[{"id": "TIE.A", "actual_mw": 1.0, "scheduled_mw": 0.0, "quality": "S"}]),
    ).json()
    assert body["warnings"] == [
        "F-2: tie line TIE.A quality 'S' is not normal and is still summed into net interchange"
    ]


@pytest.mark.parametrize(
    "payload",
    [
        area(units=[unit(), unit()]),
        area(units=[unit(min_mw=150.0, max_mw=120.0)]),
        area(units=[unit(ramp_mw_per_min=-6.0)]),
        area(units=[unit(id="GEN.ABCDEFGHIJKLMNOPQRSTU")]),
        area(units=[unit(id=f"GEN.{i}") for i in range(65)]),
        area(tie_lines=[{"id": f"T{i}", "actual_mw": 0.0, "scheduled_mw": 0.0} for i in range(33)]),
        area(frequency={"actual_hz": 60.0}),
    ],
    ids=["duplicate-id", "min-gt-max", "negative-ramp", "long-id", "65-units", "33-ties", "no-bias"],
)
def test_dispatch_refuses(payload):
    assert client.post("/v1/rtgenace/dispatch", json=payload).status_code == 422


def test_dispatch_refuses_non_finite_json():
    raw = '{"frequency": {"actual_hz": NaN, "bias_mw_per_0_1hz": -500.0}}'
    response = client.post("/v1/rtgenace/dispatch", content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 422


def test_savecase_refusals():
    too_big = client.post("/v1/rtgenace/savecase", content=b"*" * (MAX_SAVECASE_BYTES + 1))
    not_utf8 = client.post("/v1/rtgenace/savecase", content=b"SAVECASE \xff\n")
    malformed = client.post("/v1/rtgenace/savecase", content="RECORD TIELINE\n  TIE.A  x  1.0  N\n")

    assert too_big.status_code == 413
    assert not_utf8.status_code == 422 and not_utf8.json()["ierr"] == 2
    assert malformed.json() == {"ierr": 2, "detail": "TIELINE: 'x' is not a finite real number", "line": 2}


@pytest.mark.parametrize(
    ("text", "fields"),
    [
        ("A  1.0  2", ["A", "1.0", "2"]),
        ("A, 1.0 ,2", ["A", "1.0", "2"]),
        ("'O''BRIEN 1' 2", ["O'BRIEN 1", "2"]),
        ('"GEN B",3', ["GEN B", "3"]),
        ("", []),
    ],
)
def test_split_fields(text, fields):
    assert split_fields(text) == fields


@pytest.mark.parametrize("text", ["A,,1", ",A", "A / 1", "'open", "3*1.0 2"])
def test_split_fields_refuses_unsupported_list_directed_forms(text):
    with pytest.raises(ValueError):
        split_fields(text)


def test_feeders_are_read_and_validated():
    case = parse_export("RECORD FEEDER\n  FDR.1  4.5  1  2\nTIMESTAMP 2026\n")
    assert case.feeders == [{"id": "FDR.1", "load_mw": 4.5, "shed_block": 1, "priority": 2}]

    with pytest.raises(SavecaseError, match="is not an integer"):
        parse_export("RECORD FEEDER\n  FDR.1  4.5  1.5  2\n")
    with pytest.raises(SavecaseError, match="more than 256 feeders"):
        parse_export("RECORD FEEDER\n" + "".join(f"  F{i}  1.0  1  1\n" for i in range(257)))


def test_blank_quoted_quality_is_kept_as_blank():
    case = parse_export("RECORD FREQ\n  AREA  60.0  60.0  -500.0  ''\n")
    assert case.frequency_quality == " "


def test_finite_inputs_that_overflow_are_refused_not_500():
    area = {
        "frequency": {"actual_hz": 60.0, "bias_mw_per_0_1hz": -50.0},
        "tie_lines": [
            {"id": "T1", "actual_mw": 1e308, "scheduled_mw": 0.0},
            {"id": "T2", "actual_mw": 1e308, "scheduled_mw": 0.0},
        ],
        "units": [],
    }
    response = TestClient(app).post("/v1/rtgenace/dispatch", json=area)

    assert response.status_code == 422
    assert response.json() == {
        "ierr": 2,
        "detail": "area state overflows to a non-finite ACE or setpoint",
    }


def test_tab_separated_fields_split_like_blanks():
    assert split_fields("GEN.A\t100.0 \t, 5\t'x\ty'") == ["GEN.A", "100.0", "5", "x\ty"]
