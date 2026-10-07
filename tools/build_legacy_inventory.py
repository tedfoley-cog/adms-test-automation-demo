"""Inventory the legacy HDB batch tasks and check them against the services that replace them.

Builds the legacy Fortran tasks, runs the characterization suites that pin them, replays the
reference savecase and a seeded random sweep through legacy RTGENACE and the external
ace-service, and writes console/public/modernization.json for the QA console.

Usage:
    python tools/build_legacy_inventory.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEGACY = REPO / "legacy" / "habitat"
ACE_SERVICE = REPO / "services" / "ace-service"
PUBLIC = REPO / "console" / "public"
SAVECASE = LEGACY / "savecases" / "rtnet_ems_0742.export"
SWEEP_CASES = 500
SWEEP_SEED = 742

UNIT_RE = re.compile(r"^\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\s+([A-Z_0-9]+)", re.IGNORECASE)

TASKS = [
    {
        "id": "RTGENACE",
        "source": "legacy/habitat/src/ace_calc.f90",
        "function": "Reporting ACE and regulation allocation",
        "standard": "NERC BAL-001",
        "cycle": "4 s",
        "target_module": "services/ace-service/ace_service/ace.py",
        "port_status": "extracted to service, verified",
        "spec": "docs/specs/RTGENACE.md",
        "deployment": "services/ace-service — POST /v1/rtgenace/dispatch via ACE_SERVICE_URL",
        "characterization_suite": "test_characterization_rtgenace.py",
    },
    {
        "id": "LOADSHED",
        "source": "legacy/habitat/src/loadshed.f90",
        "function": "Underfrequency load shedding arming",
        "standard": "PRC-006 (UFLS)",
        "cycle": "2 s",
        "target_module": None,
        "port_status": "not started",
        "spec": None,
        "deployment": None,
        "characterization_suite": None,
    },
    {
        "id": "HAB_SAVECASE",
        "source": "legacy/habitat/src/hab_savecase.f90",
        "function": "HDB savecase export reader",
        "standard": "HDB record conventions",
        "cycle": "library",
        "target_module": "app/savecase.py",
        "port_status": "ported, unverified",
        "spec": "docs/specs/RTGENACE.md §2.1",
        "deployment": None,
        "characterization_suite": "test_characterization_hab_savecase.py",
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


def characterization_counts() -> Counter[str]:
    """Run the characterization suites (they must pass) and count tests per suite file."""
    pytest = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m"]
    subprocess.run([*pytest, "characterization"], cwd=ACE_SERVICE, check=True, capture_output=True)
    listing = subprocess.run(
        [*pytest, "characterization", "--collect-only"],
        cwd=ACE_SERVICE,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return Counter(
        Path(line.split("::", 1)[0]).name for line in listing.splitlines() if "::" in line
    )


def harness():
    sys.path[:0] = [str(ACE_SERVICE), str(ACE_SERVICE / "tests")]
    import legacy_harness

    return legacy_harness


def parity_report() -> dict[str, object]:
    h = harness()
    from ace_service.ace import dispatch

    text = SAVECASE.read_text(encoding="utf-8")
    outcome = h.compare(text)
    area = h.area_from_text(text)
    service = dispatch(area)
    legacy = outcome.legacy

    deltas = [abs(service.ace_mw - legacy.ace)] + [
        abs(s.setpoint_delta_mw - mw)
        for s, (_, mw) in zip(service.setpoints, legacy.setpoints, strict=True)
    ]
    summary = h.sweep(SWEEP_CASES, SWEEP_SEED)
    return {
        "savecase": SAVECASE.name,
        "service": "services/ace-service",
        "legacy_ace_mw": round(legacy.ace, 4),
        "modern_ace_mw": round(service.ace_mw, 4),
        "max_abs_delta_mw": round(max(deltas), 4),
        "tolerance_mw": round(h.ace_bound(area), 4),
        "logic_delta_mw": round(outcome.ace_logic_delta, 4),
        "matches": not outcome.failures,
        "setpoints": [
            {"unit": unit, "legacy_mw": round(mw, 4), "modern_mw": round(s.setpoint_delta_mw, 4)}
            for (unit, mw), s in zip(legacy.setpoints, service.setpoints, strict=True)
        ],
        "sweep": {
            "cases": summary.cases,
            "seed": summary.seed,
            "failures": len(summary.failures),
            "deadband_ambiguous": summary.deadband_ambiguous,
            "max_ace_delta_mw": round(summary.max_ace_engineering_delta, 4),
            "max_setpoint_delta_mw": round(summary.max_setpoint_engineering_delta, 4),
            "max_logic_delta_mw": round(
                max(summary.max_ace_logic_delta, summary.max_setpoint_logic_delta), 4
            ),
            "categories": summary.categories,
        },
    }


def coverage_by_module() -> dict[str, float]:
    path = PUBLIC / "coverage.json"
    if not path.exists():
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {module["id"]: module["coverage_pct"] for module in report["modules"]}


def main() -> None:
    subprocess.run(["make", "--silent", "all"], cwd=LEGACY, check=True)
    counts = characterization_counts()
    parity = parity_report()
    coverage = coverage_by_module()

    tasks = []
    for task in TASKS:
        stats = source_stats(REPO / task["source"])
        target = task["target_module"]
        suite = task.pop("characterization_suite")
        tasks.append(
            {
                **task,
                **stats,
                "target_coverage_pct": coverage.get(target) if target else None,
                "characterization_tests": counts.get(suite, 0) if suite else 0,
                "parity_checked": task["id"] == "RTGENACE",
            }
        )

    payload = {
        "clone": "RTNET.EMS",
        "platform": "HDB / Fortran 2008 batch tasks",
        "tasks": tasks,
        "parity": parity,
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    out = PUBLIC / "modernization.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    sweep = parity["sweep"]
    print(
        f"legacy tasks: {len(tasks)}, ACE parity delta: {parity['max_abs_delta_mw']} MW "
        f"(tolerance {parity['tolerance_mw']} MW), seeded parity: {sweep['cases']} cases / "
        f"{sweep['failures']} failures, characterization tests: {sum(counts.values())}"
    )


if __name__ == "__main__":
    main()
