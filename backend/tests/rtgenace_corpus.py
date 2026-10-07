"""Shared access to the RTGENACE characterization corpus and its legacy goldens."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEGACY = REPO / "legacy" / "habitat"
CORPUS = LEGACY / "characterization" / "rtgenace"
CASES_DIR = CORPUS / "cases"
GOLDEN: dict[str, dict] = json.loads((CORPUS / "golden.json").read_text(encoding="utf-8"))
CASES = sorted(GOLDEN)
ACCEPTED = [name for name in CASES if GOLDEN[name]["exit_code"] == 0]
REFUSED = [name for name in CASES if GOLDEN[name]["exit_code"] != 0]


@dataclass(frozen=True)
class LegacyReport:
    savecase: str
    ace_mw: float
    setpoints: list[tuple[str, float]]


def case_path(name: str) -> Path:
    return CASES_DIR / f"{name}.export"


def parse_report(lines: list[str]) -> LegacyReport:
    """Parse RTGENACE stdout: SAVECASE, ACE_MW (F12.4), SETPT (A20, F12.4) per unit."""
    savecase = ""
    ace = float("nan")
    setpoints: list[tuple[str, float]] = []
    for line in lines:
        if line.startswith("SAVECASE "):
            savecase = line[9:].strip()
        elif line.startswith("ACE_MW"):
            ace = float(line[9:])
        elif line.startswith("SETPT"):
            setpoints.append((line[9:29].strip(), float(line[29:])))
    return LegacyReport(savecase, ace, setpoints)


def build_legacy_binary() -> Path | None:
    """Build RTGENACE with gfortran; None when no Fortran compiler is installed."""
    if shutil.which("gfortran") is None:
        return None
    subprocess.run(["make", "--silent", "FC=gfortran", "all"], cwd=LEGACY, check=True)
    return LEGACY / "build" / "rtgenace"


def run_binary(binary: Path, *args: str) -> dict[str, object]:
    proc = subprocess.run([str(binary), *args], capture_output=True, text=True, check=False)
    return {"exit_code": proc.returncode, "stdout": proc.stdout.splitlines()}
