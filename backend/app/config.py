"""Runtime configuration, read from the environment with typed defaults."""

from __future__ import annotations

import os

DEFAULT_ACE_SERVICE_URL = "http://127.0.0.1:8081"
DEFAULT_ACE_SERVICE_TIMEOUT_S = 2.0


def ace_service_url() -> str:
    return os.environ.get("ACE_SERVICE_URL", DEFAULT_ACE_SERVICE_URL).rstrip("/")


def ace_service_timeout_s() -> float:
    return float(os.environ.get("ACE_SERVICE_TIMEOUT_S", DEFAULT_ACE_SERVICE_TIMEOUT_S))
