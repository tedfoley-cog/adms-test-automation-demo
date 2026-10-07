"""The RTGENACE traceability matrix must resolve against the code, tests and corpus."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_traceability_matrix_resolves_and_is_rendered() -> None:
    result = subprocess.run(
        [sys.executable, "tools/build_traceability.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
