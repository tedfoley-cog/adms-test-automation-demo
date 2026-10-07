"""The monolith's AGC dispatch delegates to the external ACE service (spec §5.3)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import app

client = TestClient(app)

REQUEST = {
    "balancing_state": {
        "tie_lines": [{"name": "TIE.A", "actual_mw": 150.0, "scheduled_mw": 100.0}],
        "actual_frequency_hz": 59.98,
        "frequency_bias_mw_per_0_1hz": -500.0,
        "meter_error_mw": 1.5,
    },
    "units": [
        {
            "name": "GEN.A",
            "output_mw": 100.0,
            "min_mw": 50.0,
            "max_mw": 200.0,
            "ramp_mw_per_min": 6.0,
            "participation": 0.5,
            "on_agc": False,
        }
    ],
}

SERVICE_RESULT = {
    "savecase": "",
    "ace_mw": -51.5,
    "deadband_mw": 5.0,
    "control_cycle_s": 4.0,
    "in_deadband": False,
    "setpoints": [
        {"unit": "GEN.A", "setpoint_delta_mw": 0.0, "target_mw": 100.0, "participating": False}
    ],
    "warnings": [],
}


class FakeAceService:
    def __init__(self) -> None:
        self.status = 200
        self.body: object = SERVICE_RESULT
        self.raw: bytes | None = None
        self.delay_s = 0.0
        self.requests: list[tuple[str, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["content-length"])
                fake.requests.append((self.path, json.loads(self.rfile.read(length))))
                time.sleep(fake.delay_s)
                payload = fake.raw if fake.raw is not None else json.dumps(fake.body).encode()
                try:
                    self.send_response(fake.status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client already gave up (timeout test)

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ace_service(monkeypatch):
    fake = FakeAceService()
    monkeypatch.setenv("ACE_SERVICE_URL", fake.url)
    yield fake
    fake.close()


def test_dispatch_forwards_area_state_and_maps_the_reply(ace_service):
    response = client.post("/agc/dispatch", json=REQUEST)

    assert response.status_code == 200
    assert response.json() == {
        "ace_mw": -51.5,
        "setpoint_deltas_mw": {"GEN.A": 0.0},
        "warnings": [],
    }
    path, body = ace_service.requests[0]
    assert path == "/v1/rtgenace/dispatch"
    assert body == {
        "frequency": {"actual_hz": 59.98, "scheduled_hz": 60.0, "bias_mw_per_0_1hz": -500.0},
        "meter_error_mw": 1.5,
        "tie_lines": [{"id": "TIE.A", "actual_mw": 150.0, "scheduled_mw": 100.0}],
        "units": [
            {
                "id": "GEN.A",
                "output_mw": 100.0,
                "min_mw": 50.0,
                "max_mw": 200.0,
                "ramp_mw_per_min": 6.0,
                "participation": 0.5,
                "on_agc": False,
            }
        ],
    }


def test_service_refusal_is_returned_as_422(ace_service):
    ace_service.status = 422
    ace_service.body = {"detail": [{"msg": "duplicate unit id GEN.A"}]}

    response = client.post("/agc/dispatch", json=REQUEST)

    assert response.status_code == 422
    assert "duplicate unit id GEN.A" in response.json()["detail"]


@pytest.mark.parametrize(
    ("raw", "body"),
    [
        (b"<html>not json</html>", None),
        (None, {"ace_mw": -51.5}),
        (None, ["not", "an", "object"]),
        (b'{"ace_mw": 1' + b"0" * 400 + b', "setpoints": []}', None),
        (b'{"ace_mw": NaN, "setpoints": []}', None),
    ],
)
def test_malformed_service_reply_fails_safe_with_503(ace_service, raw, body):
    ace_service.raw = raw
    ace_service.body = body

    response = client.post("/agc/dispatch", json=REQUEST)

    assert response.status_code == 503
    assert response.json()["detail"] == "ace-service returned a malformed reply"


def test_unparseable_refusal_is_still_422(ace_service):
    ace_service.status = 422
    ace_service.raw = b"refused"

    response = client.post("/agc/dispatch", json=REQUEST)

    assert response.status_code == 422
    assert "unparseable refusal" in response.json()["detail"]


def test_service_error_fails_safe_with_503(ace_service):
    ace_service.status = 500
    ace_service.body = {"detail": "boom"}

    response = client.post("/agc/dispatch", json=REQUEST)

    assert response.status_code == 503
    assert response.json()["detail"] == "ace-service returned HTTP 500"


def test_service_timeout_fails_safe_with_503(ace_service, monkeypatch):
    monkeypatch.setenv("ACE_SERVICE_TIMEOUT_S", "0.1")
    ace_service.delay_s = 0.5

    response = client.post("/agc/dispatch", json=REQUEST)

    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"]


def test_unreachable_service_fails_safe_with_503(monkeypatch):
    fake = FakeAceService()
    url = fake.url
    fake.close()
    monkeypatch.setenv("ACE_SERVICE_URL", url)

    response = client.post("/agc/dispatch", json=REQUEST)

    assert response.status_code == 503
    assert "setpoint" not in response.text


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("ACE_SERVICE_URL", raising=False)
    monkeypatch.delenv("ACE_SERVICE_TIMEOUT_S", raising=False)

    assert config.ace_service_url() == "http://127.0.0.1:8081"
    assert config.ace_service_timeout_s() == 2.0
