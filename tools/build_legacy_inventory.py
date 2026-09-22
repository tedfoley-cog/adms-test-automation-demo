"""Inventory the legacy HDB batch tasks and check them against the ported services.

Builds the legacy Fortran tasks, replays a savecase export through them, runs the
same savecase through whatever modern service claims to replace them, and writes
console/public/modernization.json for the QA console's Modernization view.

Usage:
    python tools/build_legacy_inventory.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEGACY = REPO / "legacy" / "habitat"
BACKEND = REPO / "backend"
PUBLIC = REPO / "console" / "public"
SAVECASE = LEGACY / "savecases" / "rtnet_ems_0742.export"

UNIT_RE = re.compile(r"^\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\s+([A-Z_0-9]+)", re.IGNORECASE)

TASKS = [
    {
        "id": "RTGENACE",
        "source": "legacy/habitat/src/ace_calc.f90",
        "function": "Reporting ACE and regulation allocation",
        "standard": "NERC BAL-001",
        "cycle": "4 s",
        "target_module": "app/agc.py",
        "port_status": "ported, unverified",
    },
    {
        "id": "LOADSHED",
        "source": "legacy/habitat/src/loadshed.f90",
        "function": "Underfrequency load shedding arming",
        "standard": "PRC-006 (UFLS)",
        "cycle": "2 s",
        "target_module": None,
        "port_status": "not started",
    },
    {
        "id": "HAB_SAVECASE",
        "source": "legacy/habitat/src/hab_savecase.f90",
        "function": "HDB savecase export reader",
        "standard": "HDB record conventions",
        "cycle": "library",
        "target_module": "app/savecase.py",
        "port_status": "ported, unverified",
    },
]


def source_stats(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    executable = 0
    units: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        executable += 1
        match = UNIT_RE.match(stripped)
        if match and not stripped.upper().startswith("END"):
            units.append(match.group(2).upper())
    return {"source_lines": len(lines), "executable_lines": executable, "program_units": units}


def legacy_ace() -> dict[str, float]:
    subprocess.run(["make", "--silent", "all"], cwd=LEGACY, check=True)
    output = subprocess.run(
        [str(LEGACY / "build" / "rtgenace"), str(SAVECASE)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    result: dict[str, float] = {}
    for line in output.splitlines():
        fields = line.split()
        if fields[0] == "ACE_MW":
            result["ACE_MW"] = float(fields[1])
        elif fields[0] == "SETPT":
            result[fields[1]] = float(fields[2])
    return result


def modern_ace() -> dict[str, float]:
    sys.path.insert(0, str(BACKEND))
    from app.agc import allocate_regulation, reporting_ace
    from app.savecase import load_savecase

    case = load_savecase(SAVECASE)
    ace = reporting_ace(case.balancing_state())
    result = {"ACE_MW": ace}
    result.update(allocate_regulation(case.units, ace))
    return result


def coverage_by_module() -> dict[str, float]:
    path = PUBLIC / "coverage.json"
    if not path.exists():
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {module["id"]: module["coverage_pct"] for module in report["modules"]}


def main() -> None:
    legacy = legacy_ace()
    modern = modern_ace()
    coverage = coverage_by_module()

    max_delta = max(abs(legacy[key] - modern.get(key, 0.0)) for key in legacy)
    parity = {
        "savecase": SAVECASE.name,
        "legacy_ace_mw": round(legacy["ACE_MW"], 4),
        "modern_ace_mw": round(modern["ACE_MW"], 4),
        "max_abs_delta_mw": round(max_delta, 4),
        "matches": max_delta < 0.01,
        "setpoints": [
            {
                "unit": key,
                "legacy_mw": round(legacy[key], 4),
                "modern_mw": round(modern.get(key, 0.0), 4),
            }
            for key in legacy
            if key != "ACE_MW"
        ],
    }

    tasks = []
    for task in TASKS:
        stats = source_stats(REPO / task["source"])
        target = task["target_module"]
        tasks.append(
            {
                **task,
                **stats,
                "target_coverage_pct": coverage.get(target) if target else None,
                "characterization_tests": 0,
                "parity_checked": bool(target) and task["id"] == "RTGENACE",
            }
        )

    payload = {
        "clone": "RTNET.EMS",
        "platform": "HDB / Fortran 2008 batch tasks",
        "tasks": tasks,
        "parity": parity,
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "modernization.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"legacy tasks: {len(tasks)}, ACE parity delta: {parity['max_abs_delta_mw']} MW, "
        f"characterization tests: 0"
    )


if __name__ == "__main__":
    main()
