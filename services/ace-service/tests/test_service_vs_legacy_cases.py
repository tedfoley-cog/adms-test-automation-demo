"""Every characterization case replayed through the service over HTTP (spec §5.4, §6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from legacy_harness import PRINT_RESOLUTION, ace_bound, area_from_text
from rtgenace_cases import HAB_SAVECASE_CASES, LEGACY, RTGENACE_CASES

from ace_service.service import app

client = TestClient(app)
CASES = RTGENACE_CASES + HAB_SAVECASE_CASES


def post_savecase(text: str):
    return client.post("/v1/rtgenace/savecase", content=text, headers={"content-type": "text/plain"})


@pytest.mark.parametrize("case", [c for c in CASES if c.service == "same"], ids=lambda case: case.id)
def test_service_matches_pinned_legacy(case):
    pinned = LEGACY[case.id]
    response = post_savecase(case.text)

    if pinned.rc != 0:
        assert response.status_code == 422
        assert response.json()["ierr"] == pinned.ierr
        return

    assert response.status_code == 200, response.text
    body = response.json()
    tolerance = ace_bound(area_from_text(case.text))
    assert body["savecase"] == pinned.name
    assert abs(body["ace_mw"] - pinned.ace) <= tolerance
    assert [(s["unit"]) for s in body["setpoints"]] == [unit for unit, _ in pinned.setpoints]
    for setpoint, (_, pinned_mw) in zip(body["setpoints"], pinned.setpoints, strict=True):
        assert abs(setpoint["setpoint_delta_mw"] - pinned_mw) <= tolerance + PRINT_RESOLUTION


@pytest.mark.parametrize("case", [c for c in CASES if c.service == "refuse"], ids=lambda case: case.id)
def test_service_refuses_unsafe_or_malformed_input(case):
    response = post_savecase(case.text)

    assert response.status_code == 422, response.text
    assert response.json()["ierr"] == 2


def test_c16_and_c17_carry_finding_warnings():
    by_id = {case.id: case for case in CASES}
    c16 = post_savecase(by_id["C16"].text).json()
    c17 = post_savecase(by_id["C17"].text).json()

    assert c16["setpoints"][0]["setpoint_delta_mw"] == 20.0
    assert any(w.startswith("F-1: unit GEN.LOW") for w in c16["warnings"])
    assert any(w.startswith("F-2: frequency AREA.NTX quality 'S'") for w in c17["warnings"])
