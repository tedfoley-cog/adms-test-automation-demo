"""Inventory the legacy HDB batch tasks and check them against the ported services.

Builds the legacy Fortran tasks, replays the production savecase and the RTGENACE
characterization corpus through them, runs the same savecases through the ported
service, and writes console/public/modernization.json for the QA console's
Modernization view. Legacy/modern differences are judged against the per-savecase
single-precision bound from app.rtgenace, not a fixed tolerance.

Usage:
    python tools/build_legacy_inventory.py
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEGACY = REPO / "legacy" / "habitat"
BACKEND = REPO / "backend"
PUBLIC = REPO / "console" / "public"
SAVECASE = LEGACY / "savecases" / "rtnet_ems_0742.export"
CORPUS = LEGACY / "characterization" / "rtgenace"

# Characterization tests that pin HDB_READ_EXPORT itself: refusals, record-table
# capacity, END handling, record ordering and unknown records.
READER_TEST_RE = re.compile(
    r"refuse|missing|usage|records_|unknown_record|table_|malformed|non_numeric"
)

UNIT_RE = re.compile(r"^\s*(PROGRAM|SUBROUTINE|FUNCTION|MODULE)\s+([A-Z_0-9]+)", re.IGNORECASE)

TASKS = [
    {
        "id": "RTGENACE",
        "source": "legacy/habitat/src/ace_calc.f90",
        "function": "Reporting ACE and regulation allocation",
        "standard": "NERC BAL-001",
        "cycle": "4 s",
        "target_module": "app/rtgenace.py",
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


def build_legacy() -> None:
    # FC must be explicit: make's built-in FC=f77 defeats the Makefile's `FC ?= gfortran`.
    subprocess.run(["make", "--silent", "FC=gfortran", "all"], cwd=LEGACY, check=True)


def run_legacy(path: Path) -> dict[str, object]:
    proc = subprocess.run(
        [str(LEGACY / "build" / "rtgenace"), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"exit_code": proc.returncode, "stdout": proc.stdout.splitlines()}


def parse_report(lines: list[str]) -> tuple[float, list[tuple[str, float]]]:
    ace = float("nan")
    setpoints: list[tuple[str, float]] = []
    for line in lines:
        if line.startswith("ACE_MW"):
            ace = float(line[9:])
        elif line.startswith("SETPT"):
            setpoints.append((line[9:29].strip(), float(line[29:])))
    return ace, setpoints


def compare(path: Path, legacy: dict[str, object]) -> dict[str, object]:
    """Replay one savecase through the port and judge it against the legacy output."""
    from app import rtgenace
    from app.savecase import load_savecase

    if legacy["exit_code"] != 0:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exit_code = rtgenace.main([str(path)])
        modern = {"exit_code": exit_code, "stdout": out.getvalue().splitlines()}
        return {"refused": True, "matches": modern == legacy}

    legacy_ace, legacy_setpoints = parse_report(legacy["stdout"])
    case = load_savecase(path)
    result = rtgenace.run(case)
    ace_bound = rtgenace.ace_parity_bound(case)
    ace_delta = abs(result.ace_mw - legacy_ace)
    roster_matches = [n for n, _ in result.setpoints] == [n for n, _ in legacy_setpoints]
    indeterminate = rtgenace.deadband_indeterminate(case, result.ace_mw)
    if not roster_matches:
        setpoints_match = False
    elif indeterminate:
        setpoints_match = rtgenace.legacy_setpoints_consistent(
            case, legacy_ace, [mw for _, mw in legacy_setpoints]
        )
    else:
        setpoints_match = all(
            abs(ours - theirs) <= rtgenace.setpoint_parity_bound(case, i, result.ace_mw)
            for i, ((_, ours), (_, theirs)) in enumerate(
                zip(result.setpoints, legacy_setpoints, strict=True)
            )
        )
    return {
        "refused": False,
        "matches": ace_delta <= ace_bound and setpoints_match,
        "legacy_ace_mw": legacy_ace,
        "modern_ace_mw": result.ace_mw,
        "ace_delta_mw": ace_delta,
        "ace_bound_mw": ace_bound,
        "deadband_indeterminate": indeterminate,
        "setpoints": [
            {"unit": name, "legacy_mw": theirs, "modern_mw": ours}
            for (name, ours), (_, theirs) in zip(
                result.setpoints, legacy_setpoints, strict=roster_matches
            )
        ],
    }


def corpus_parity() -> dict[str, object]:
    goldens = json.loads((CORPUS / "golden.json").read_text(encoding="utf-8"))
    results = {}
    reproduced = 0
    for name in sorted(goldens):
        path = CORPUS / "cases" / f"{name}.export"
        live = run_legacy(path)
        reproduced += live == goldens[name]
        results[name] = compare(path, live)
    accepted = [r for r in results.values() if not r["refused"]]
    return {
        "cases": len(results),
        "accepted": len(accepted),
        "refused": len(results) - len(accepted),
        "goldens_reproduced": reproduced,
        "matched": sum(1 for r in results.values() if r["matches"]),
        "diverging": sorted(name for name, r in results.items() if not r["matches"]),
        "deadband_indeterminate": sum(1 for r in accepted if r["deadband_indeterminate"]),
        "max_ace_delta_mw": round(max(r["ace_delta_mw"] for r in accepted), 4),
        # Knife-edge cases are judged on the legacy ACE, so their setpoints are excluded.
        "max_setpoint_delta_mw": round(
            max(
                (
                    abs(s["modern_mw"] - s["legacy_mw"])
                    for r in accepted
                    if not r["deadband_indeterminate"]
                    for s in r["setpoints"]
                ),
                default=0.0,
            ),
            4,
        ),
        "worst_bound_use_pct": round(
            100 * max(r["ace_delta_mw"] / r["ace_bound_mw"] for r in accepted), 1
        ),
    }


def characterization_tests() -> dict[str, bool]:
    """Run every @characterization test; map test id -> passed (failures count against)."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "characterization.xml"
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-m", "characterization", f"--junitxml={report}"],
            cwd=BACKEND,
            stdout=subprocess.DEVNULL,
            check=False,
        )
        cases = ET.parse(report).getroot().iter("testcase")
        return {
            f"{case.get('classname')}::{case.get('name')}": not any(
                child.tag in ("failure", "error", "skipped") for child in case
            )
            for case in cases
        }


def coverage_by_module() -> dict[str, float]:
    path = PUBLIC / "coverage.json"
    if not path.exists():
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {module["id"]: module["coverage_pct"] for module in report["modules"]}


def main() -> None:
    build_legacy()
    sys.path.insert(0, str(BACKEND))
    production = compare(SAVECASE, run_legacy(SAVECASE))
    corpus = corpus_parity()
    tests = characterization_tests()
    coverage = coverage_by_module()

    deltas = [production["ace_delta_mw"]] + [
        abs(s["modern_mw"] - s["legacy_mw"]) for s in production["setpoints"]
    ]
    parity = {
        "savecase": SAVECASE.name,
        "legacy_ace_mw": round(production["legacy_ace_mw"], 4),
        "modern_ace_mw": round(production["modern_ace_mw"], 4),
        "max_abs_delta_mw": round(max(deltas), 4),
        "ace_bound_mw": round(production["ace_bound_mw"], 4),
        "matches": production["matches"],
        "setpoints": [
            {
                "unit": s["unit"],
                "legacy_mw": round(s["legacy_mw"], 4),
                "modern_mw": round(s["modern_mw"], 4),
            }
            for s in production["setpoints"]
        ],
        "corpus": corpus,
    }

    suites = {
        "RTGENACE": [t for t in tests if "rtgenace" in t],
        "HAB_SAVECASE": [t for t in tests if "rtgenace" in t and READER_TEST_RE.search(t)],
    }
    # Only passing tests pin behaviour; any failing or skipped test blocks "verified".
    pinned = {task: [t for t in ids if tests[t]] for task, ids in suites.items()}
    all_pass = {task: len(pinned[task]) == len(ids) for task, ids in suites.items()}
    corpus_proven = corpus["matched"] == corpus["cases"] == corpus["goldens_reproduced"]
    tasks = []
    for task in TASKS:
        stats = source_stats(REPO / task["source"])
        target = task["target_module"]
        count = len(pinned.get(task["id"], []))
        verified = (
            bool(target)
            and count > 0
            and all_pass.get(task["id"], False)
            and corpus_proven
            and production["matches"]
        )
        tasks.append(
            {
                **task,
                **stats,
                "port_status": "ported, verified" if verified else task["port_status"],
                "target_coverage_pct": coverage.get(target) if target else None,
                "characterization_tests": count,
                "parity_checked": verified,
            }
        )

    payload = {
        "clone": "RTNET.EMS",
        "platform": "HDB / Fortran 2008 batch tasks",
        "tasks": tasks,
        "parity": parity,
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "modernization.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"legacy tasks: {len(tasks)}, ACE parity delta: {parity['max_abs_delta_mw']} MW "
        f"(bound {parity['ace_bound_mw']} MW), corpus: {corpus['matched']}/{corpus['cases']} "
        f"savecases match, characterization tests: {len(tests)}"
    )


if __name__ == "__main__":
    main()
