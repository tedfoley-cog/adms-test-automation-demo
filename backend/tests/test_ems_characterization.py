from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agc import allocate_regulation
from app.api import app
from app.models import Measurement, Unit
from app.savecase import FeederBlock, load_savecase
from app.state_estimator import EstimationResult, convergence_metric, estimate

pytestmark = pytest.mark.characterization

SAVECASE = (
    Path(__file__).resolve().parents[2]
    / "legacy" / "habitat" / "savecases" / "rtnet_ems_0742.export"
)


def test_savecase_ingest_preserves_replay_inputs():
    case = load_savecase(SAVECASE)

    assert case.name == "RTNET_EMS_0742"
    assert case.frequency_quality == "N"
    assert case.balancing_state().model_dump() == {
        "actual_frequency_hz": 59.968,
        "scheduled_frequency_hz": 60.0,
        "frequency_bias_mw_per_0_1hz": -412.0,
        "meter_error_mw": 2.5,
        "tie_lines": [
            {"name": "TIE.NORTH340", "actual_mw": 418.2, "scheduled_mw": 400.0},
            {"name": "TIE.EAST115", "actual_mw": -132.6, "scheduled_mw": -140.0},
            {"name": "TIE.SOUTH230", "actual_mw": 97.4, "scheduled_mw": 105.0},
        ],
    }
    assert case.units[-1] == Unit(
        name="GEN.CEDAR_STM", output_mw=305.0, min_mw=240.0, max_mw=340.0,
        ramp_mw_per_min=3.0, participation=0.0, on_agc=False,
    )
    assert case.feeders == [
        FeederBlock("FDR.1201", 6.4, 1, 3),
        FeederBlock("FDR.1405", 8.1, 1, 2),
        FeederBlock("FDR.2210", 11.7, 2, 3),
        FeederBlock("FDR.2255", 4.9, 3, 1),
    ]


def test_agc_dispatch_reports_ace_and_ramp_limited_deltas():
    case = load_savecase(SAVECASE)
    response = TestClient(app).post(
        "/agc/dispatch",
        json={
            "balancing_state": case.balancing_state().model_dump(),
            "units": [unit.model_dump() for unit in case.units],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ace_mw": pytest.approx(-116.34),
        "setpoint_deltas_mw": {
            "GEN.HARBOR1": 0.4,
            "GEN.HARBOR2": 0.4,
            "GEN.MESQUITE_CT": 1.2,
            "GEN.CEDAR_STM": 0.0,
        },
    }


@pytest.mark.parametrize("ace_mw", [-5.0, 5.0])
def test_agc_deadband_includes_both_boundaries(ace_mw):
    assert allocate_regulation(load_savecase(SAVECASE).units, ace_mw) == {
        "GEN.HARBOR1": 0.0, "GEN.HARBOR2": 0.0, "GEN.MESQUITE_CT": 0.0, "GEN.CEDAR_STM": 0.0,
    }


def test_agc_excludes_ineligible_units_and_clips_at_minimum():
    units = [
        Unit(name="ACTIVE", output_mw=10.1, min_mw=10.0, max_mw=40.0,
             ramp_mw_per_min=60.0, participation=1.0),
        Unit(name="NO-SHARE", output_mw=20.0, min_mw=10.0, max_mw=40.0,
             ramp_mw_per_min=60.0, participation=0.0),
    ]

    assert allocate_regulation(units, 50.0) == {"ACTIVE": -0.1, "NO-SHARE": 0.0}
    assert allocate_regulation(units[1:], 50.0) == {"NO-SHARE": 0.0}


def test_estimator_rejects_outlier_before_reporting_reconciled_measurements():
    measurements = [
        {"mrid": "FDR-TEST", "kind": "P", "value": 10.0, "sigma": 1.0},
        {"mrid": "FDR-TEST", "kind": "P", "value": 12.0, "sigma": 1.0},
        {"mrid": "FDR-TEST", "kind": "P", "value": 50.0, "sigma": 1.0},
        {"mrid": "FDR-TEST", "kind": "V", "value": 1.0, "sigma": 0.1},
    ]
    response = TestClient(app).post("/state-estimator/run", json={"measurements": measurements})

    assert response.status_code == 200
    assert response.json() == {
        "estimated": {"FDR-TEST:P": 11.0, "FDR-TEST:V": pytest.approx(1.0)},
        "residuals": {"FDR-TEST:P": 1.0, "FDR-TEST:V": pytest.approx(0.0)},
        "rejected": ["FDR-TEST:P"],
        "observable": True,
        "iterations": 2,
        "rms_residual": pytest.approx(2**-0.5),
    }


def test_estimator_does_not_use_bad_quality_or_zero_uncertainty():
    result = estimate([
        Measurement(mrid="FDR-TEST", kind="P", value=10.0, sigma=0.0),
        Measurement(mrid="FDR-TEST", kind="P", value=20.0, sigma=1.0, valid=False),
    ])

    assert result == EstimationResult({}, {}, [], observable=False, iterations=0)
    assert convergence_metric(result) == 0.0
