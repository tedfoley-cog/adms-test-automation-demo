"""Savecase parity: legacy RTGENACE vs the ACE service (spec §5.4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from legacy_harness import REFERENCE_SAVECASE, compare, sweep

from ace_service.service import app

SWEEP_CASES = 500
SWEEP_SEED = 742


def test_reference_savecase_parity_in_process():
    outcome = compare(REFERENCE_SAVECASE.read_text())

    assert outcome.failures == []
    assert outcome.legacy.ace == pytest.approx(-116.3462, abs=1e-9)
    assert outcome.ace_service == pytest.approx(-116.34, abs=1e-9)
    assert outcome.ace_logic_delta < 2e-4
    assert not outcome.deadband_ambiguous


def test_reference_savecase_parity_over_http():
    legacy = compare(REFERENCE_SAVECASE.read_text()).legacy
    body = (
        TestClient(app)
        .post("/v1/rtgenace/savecase", content=REFERENCE_SAVECASE.read_text(), headers={"content-type": "text/plain"})
        .json()
    )

    assert body["savecase"] == "RTNET_EMS_0742"
    assert abs(body["ace_mw"] - legacy.ace) < 0.01
    assert [(s["unit"], s["setpoint_delta_mw"]) for s in body["setpoints"]] == legacy.setpoints


def test_seeded_random_savecases_match_legacy():
    summary = sweep(SWEEP_CASES, SWEEP_SEED)

    assert summary.failures == []
    assert summary.cases == SWEEP_CASES
    for category in ("deadband", "ramp clipped", "limit clipped", "out-of-limit unit", "non-participating unit"):
        assert summary.categories.get(category, 0) >= 10, summary.categories
