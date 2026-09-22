"""Merge firmware (gcov) and backend (coverage.py) results into one report.

Output: console/public/coverage.json, consumed by the QA console, plus an
appended entry in console/public/testruns.json so the run history is real.

Usage:
    python tools/build_coverage_report.py [--label "baseline"]
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIRMWARE = REPO / "firmware"
BACKEND = REPO / "backend"
PUBLIC = REPO / "console" / "public"

# Static metadata about each module: the control-room function it implements,
# the standard that governs it, and the verification tier it must reach.
CATALOG: dict[str, dict[str, str]] = {
    "firmware/src/fault_detect.c": {
        "function": "Feeder overcurrent protection (50/51)",
        "standard": "IEC 60255-151",
        "tier": "Tier 1",
        "team": "Protection & Control",
    },
    "firmware/src/recloser.c": {
        "function": "Autoreclose sequence control",
        "standard": "IEEE C37.60",
        "tier": "Tier 1",
        "team": "Protection & Control",
    },
    "firmware/src/dnp3_outstation.c": {
        "function": "DNP3 outstation point map and class 0 response",
        "standard": "IEEE 1815",
        "tier": "Tier 2",
        "team": "Substation Comms",
    },
    "app/flisr.py": {
        "function": "Fault location, isolation and service restoration",
        "standard": "IEEE 1366 (reliability impact)",
        "tier": "Tier 1",
        "team": "ADMS Applications",
    },
    "app/agc.py": {
        "function": "Automatic generation control / reporting ACE",
        "standard": "NERC BAL-001",
        "tier": "Tier 1",
        "team": "AEMS Applications",
    },
    "app/state_estimator.py": {
        "function": "Measurement conditioning and bad-data detection",
        "standard": "IEC 61970 (CIM)",
        "tier": "Tier 2",
        "team": "AEMS Applications",
    },
    "app/network.py": {
        "function": "Topology processing and connectivity trace",
        "standard": "IEC 61968",
        "tier": "Tier 2",
        "team": "ADMS Applications",
    },
    "app/savecase.py": {
        "function": "Legacy HDB savecase ingest for migration parity",
        "standard": "HDB record conventions",
        "tier": "Tier 2",
        "team": "AEMS Applications",
    },
    "app/api.py": {
        "function": "Control-room HTTP surface",
        "standard": "Internal API contract",
        "tier": "Tier 3",
        "team": "Platform",
    },
    "app/models.py": {
        "function": "CIM-aligned domain models",
        "standard": "IEC 61970 (CIM)",
        "tier": "Tier 3",
        "team": "Platform",
    },
}

TIER_TARGETS = {"Tier 1": 90, "Tier 2": 75, "Tier 3": 60}


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def firmware_modules() -> list[dict[str, object]]:
    run(["make", "coverage"], FIRMWARE)

    # Every test binary profiles the whole of src/, so a source file appears in
    # one gcov report per test. Merge the per-line hit counts first, otherwise a
    # module shows up once per test binary and the overall percentage is wrong.
    hits: dict[str, dict[int, int]] = {}
    pattern = str(FIRMWARE / "build" / "*.p" / "*.gcov.json.gz")
    for archive in sorted(glob.glob(pattern)):
        with gzip.open(archive, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        for file_entry in payload.get("files", []):
            source = file_entry["file"]
            if not source.startswith("src/"):
                continue
            counts = hits.setdefault(f"firmware/{source}", {})
            for line in file_entry.get("lines", []):
                number = line["line_number"]
                counts[number] = counts.get(number, 0) + line.get("count", 0)

    modules: list[dict[str, object]] = []
    for path, counts in sorted(hits.items()):
        total = len(counts)
        covered = sum(1 for count in counts.values() if count > 0)
        uncovered = sorted(number for number, count in counts.items() if count == 0)
        modules.append(build_module(path, "firmware", "C", total, covered, uncovered))
    return modules


def backend_modules() -> list[dict[str, object]]:
    venv_python = BACKEND / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else "python3"
    run(
        [python, "-m", "pytest", "-q", "--cov=app", "--cov-report=json:coverage.json"],
        BACKEND,
    )
    with (BACKEND / "coverage.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)

    modules: list[dict[str, object]] = []
    for path, entry in sorted(payload["files"].items()):
        summary = entry["summary"]
        modules.append(
            build_module(
                path,
                "backend",
                "Python",
                summary["num_statements"],
                summary["covered_lines"],
                entry.get("missing_lines", []),
            )
        )
    return modules


def build_module(
    path: str,
    layer: str,
    language: str,
    total: int,
    covered: int,
    uncovered: list[int],
) -> dict[str, object]:
    meta = CATALOG.get(path, {})
    tier = meta.get("tier", "Tier 3")
    pct = round((covered / total) * 100, 1) if total else 0.0
    target = TIER_TARGETS[tier]
    return {
        "id": path,
        "name": Path(path).name,
        "path": path,
        "layer": layer,
        "language": language,
        "function": meta.get("function", "Supporting module"),
        "standard": meta.get("standard", "—"),
        "team": meta.get("team", "Platform"),
        "tier": tier,
        "target_pct": target,
        "lines_total": total,
        "lines_covered": covered,
        "coverage_pct": pct,
        "gap_pct": round(max(target - pct, 0.0), 1),
        "uncovered_lines": uncovered[:40],
        "status": "meets target" if pct >= target else "below target",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline", help="label for this run")
    args = parser.parse_args()

    modules = firmware_modules() + backend_modules()
    total_lines = sum(int(m["lines_total"]) for m in modules)
    covered_lines = sum(int(m["lines_covered"]) for m in modules)
    overall = round((covered_lines / total_lines) * 100, 1) if total_lines else 0.0
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    report = {
        "generated_at": generated_at,
        "label": args.label,
        "overall_pct": overall,
        "lines_total": total_lines,
        "lines_covered": covered_lines,
        "tier_targets": TIER_TARGETS,
        "modules": sorted(modules, key=lambda m: (m["tier"], m["coverage_pct"])),
    }

    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    runs_path = PUBLIC / "testruns.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else []
    entry = {
        "label": args.label,
        "generated_at": generated_at,
        "overall_pct": overall,
        "modules_below_target": sum(1 for m in modules if m["status"] == "below target"),
        "lines_total": total_lines,
        "lines_covered": covered_lines,
    }
    # Re-running a label supersedes the earlier attempt rather than stacking a
    # second history row with the same name.
    runs = [run_entry for run_entry in runs if run_entry["label"] != args.label]
    runs.append(entry)
    runs_path.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")

    print(f"overall line coverage: {overall}% across {len(modules)} modules")


if __name__ == "__main__":
    main()
