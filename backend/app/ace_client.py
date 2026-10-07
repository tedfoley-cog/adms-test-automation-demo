"""Client for the external ACE service (legacy RTGENACE, docs/specs/RTGENACE.md §5.3).

The monolith no longer computes ACE. If the service is unreachable it gets no setpoints
(fail-safe); there is no local fallback.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from . import config
from .models import BalancingState, Unit


class AceServiceError(Exception):
    status_code = 503


class AceServiceUnavailable(AceServiceError):
    status_code = 503


class AceServiceRejected(AceServiceError):
    status_code = 422

    def __init__(self, detail: object) -> None:
        super().__init__(f"ace-service refused the area state: {detail}")
        self.detail = detail


def area_payload(state: BalancingState, units: list[Unit]) -> dict[str, object]:
    return {
        "frequency": {
            "actual_hz": state.actual_frequency_hz,
            "scheduled_hz": state.scheduled_frequency_hz,
            "bias_mw_per_0_1hz": state.frequency_bias_mw_per_0_1hz,
        },
        "meter_error_mw": state.meter_error_mw,
        "tie_lines": [
            {"id": line.name, "actual_mw": line.actual_mw, "scheduled_mw": line.scheduled_mw}
            for line in state.tie_lines
        ],
        "units": [
            {
                "id": unit.name,
                "output_mw": unit.output_mw,
                "min_mw": unit.min_mw,
                "max_mw": unit.max_mw,
                "ramp_mw_per_min": unit.ramp_mw_per_min,
                "participation": unit.participation,
                "on_agc": unit.on_agc,
            }
            for unit in units
        ],
    }


def dispatch(state: BalancingState, units: list[Unit]) -> dict[str, object]:
    url = f"{config.ace_service_url()}/v1/rtgenace/dispatch"
    request = urllib.request.Request(
        url,
        data=json.dumps(area_payload(state, units)).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.ace_service_timeout_s()) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            raise AceServiceRejected(_refusal_detail(exc)) from exc
        raise AceServiceUnavailable(f"ace-service returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AceServiceUnavailable(f"ace-service unreachable at {url}: {exc}") from exc
    except ValueError as exc:
        raise AceServiceUnavailable("ace-service returned a malformed reply") from exc

    try:
        ace_mw = _finite(result["ace_mw"])
        deltas = {str(sp["unit"]): _finite(sp["setpoint_delta_mw"]) for sp in result["setpoints"]}
        warnings = list(result.get("warnings", []))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise AceServiceUnavailable("ace-service returned a malformed reply") from exc
    return {"ace_mw": ace_mw, "setpoint_deltas_mw": deltas, "warnings": warnings}


def _finite(value: object) -> float:
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number):
        raise ValueError("non-finite value in ace-service reply")
    return number


def _refusal_detail(exc: urllib.error.HTTPError) -> object:
    try:
        return json.load(exc).get("detail")
    except (ValueError, AttributeError):
        return "unparseable refusal"
