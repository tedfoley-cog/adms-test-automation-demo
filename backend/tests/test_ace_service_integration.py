"""End to end: monolith /agc/dispatch -> real ace-service over HTTP, on the reference savecase.

Skipped when the ace-service package is not installed in this environment.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.savecase import load_savecase

uvicorn = pytest.importorskip("uvicorn")
service = pytest.importorskip("ace_service.service")

SAVECASE = Path(__file__).resolve().parents[2] / "legacy/habitat/savecases/rtnet_ems_0742.export"
LEGACY_SETPOINTS = {
    "GEN.HARBOR1": 0.4,
    "GEN.HARBOR2": 0.4,
    "GEN.MESQUITE_CT": 1.2,
    "GEN.CEDAR_STM": 0.0,
}


@pytest.fixture(scope="module")
def ace_service_url():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(service.app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_reference_savecase_through_the_monolith(ace_service_url, monkeypatch):
    monkeypatch.setenv("ACE_SERVICE_URL", ace_service_url)
    case = load_savecase(SAVECASE)
    request = {
        "balancing_state": case.balancing_state().model_dump(),
        "units": [unit.model_dump() for unit in case.units],
    }

    response = TestClient(app).post("/agc/dispatch", json=request)

    assert response.status_code == 200, response.text
    body = response.json()
    assert abs(body["ace_mw"] - -116.3462) < 0.01
    assert body["setpoint_deltas_mw"] == LEGACY_SETPOINTS
