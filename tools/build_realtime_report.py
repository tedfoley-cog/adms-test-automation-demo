"""Build the console's real-time report from the emulated target.

Runs every secondary-injection scenario on the STM32F407 image under Renode
(tools/run_renode.py), the host PMU compliance suites
(firmware/build/pmu_compliance), and the target memory footprint, and writes
console/public/realtime.json.

    python tools/build_realtime_report.py [--label baseline]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_renode

REPO = Path(__file__).resolve().parent.parent
FIRMWARE = REPO / "firmware"
PUBLIC = REPO / "console" / "public"

SCENARIO_T0_SOC = 1790000003  # SOC_AT_BOOT + preroll in target/stm32f407/main.c
FAULT_START_S = 0.30

ELEMENTS = ["50P", "50G", "51P", "51G", "21Z1", "21Z2", "81U", "81O", "81R",
            "50BF-RT", "50BF-86B"]

# What a correct relay must do in each scenario.
EXPECTED = {
    "steady_load": {"description": "Balanced 320 A load, 0.95 pf, 60 Hz",
                    "elements": [], "bus_trip": False},
    "fault_ag_zone1": {"description": "A-G fault at 40% of the line, 0.5 ohm",
                       "elements": ["21Z1"], "bus_trip": False},
    "fault_bc_zone2": {"description": "B-C fault at 110% of the line (adjacent section)",
                       "elements": ["21Z2"], "bus_trip": False},
    "fault_ag_high_resistance": {"description": "A-G fault through 10 ohm at 50%",
                                 "elements": ["51G"], "bus_trip": False},
    "breaker_failure": {"description": "A-G zone 1 fault, feeder breaker stuck closed",
                        "elements": ["21Z1", "50BF-86B"], "bus_trip": True},
}

# IEEE C37.118.1-2011 (+1a-2014) P-class test matrix. `suite` names a host
# compliance suite that exercises the point; None means no automated test yet.
COMPLIANCE = [
    {"id": "ss-magnitude", "test": "Steady-state magnitude, 10-120% Vnom",
     "clause": "5.5.5 Table 3", "limit": "TVE <= 1%", "suite": "magnitude"},
    {"id": "ss-phase", "test": "Steady-state phase angle, +/-180 deg",
     "clause": "5.5.5 Table 3", "limit": "TVE <= 1%", "suite": "phase"},
    {"id": "ss-frequency", "test": "Steady-state frequency range, fnom +/-2 Hz",
     "clause": "5.5.5 Table 3", "limit": "TVE <= 1%, FE <= 5 mHz, RFE <= 0.4 Hz/s",
     "suite": None},
    {"id": "harmonics", "test": "Harmonic distortion, 1% each to 50th",
     "clause": "5.5.5 Table 3", "limit": "TVE <= 1%, FE <= 5 mHz", "suite": None},
    {"id": "freq-ramp", "test": "Frequency ramp, +/-1 Hz/s",
     "clause": "5.5.8 Table 7", "limit": "TVE <= 1%, FE <= 10 mHz, RFE <= 0.4 Hz/s",
     "suite": None},
    {"id": "modulation", "test": "Amplitude and phase modulation bandwidth, 2 Hz",
     "clause": "5.5.6 Table 5", "limit": "TVE <= 3%, FE <= 60 mHz", "suite": None},
    {"id": "step", "test": "Magnitude and phase step response",
     "clause": "5.5.9 Table 8", "limit": "Response <= 2/fnom, overshoot <= 5%",
     "suite": None},
    {"id": "latency", "test": "Reporting latency",
     "clause": "5.5.10", "limit": "<= 2/Fs (33.3 ms)", "suite": None},
]


def target_footprint() -> dict[str, int]:
    out = subprocess.run(
        ["arm-none-eabi-size", "-A", str(run_renode.ELF)],
        check=True, capture_output=True, text=True,
    ).stdout
    sizes = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith(".") and parts[1].isdigit():
            sizes[parts[0]] = int(parts[1])
    flash = sum(sizes.get(s, 0) for s in (".isr_vector", ".text", ".rodata", ".ARM.exidx",
                                          ".init_array", ".fini_array", ".data"))
    ram = sum(sizes.get(s, 0) for s in (".data", ".bss", ".noinit"))
    return {"flash_bytes": flash, "ram_bytes": ram}


def renode_version() -> str:
    out = subprocess.run(["renode", "--version"], check=False, capture_output=True, text=True).stdout
    m = re.search(r"v?(\d+\.\d+\.\d+)", out)
    return f"Renode {m.group(1)}" if m else "Renode"


def run_compliance(suite: str) -> dict:
    exe = FIRMWARE / "build" / "pmu_compliance"
    proc = subprocess.run([str(exe), "--suite", suite], check=False, capture_output=True, text=True)
    return json.loads(proc.stdout)


def scenario_row(name: str, r: run_renode.RunResult) -> dict:
    target = int(r.result.get("target", "0x0"), 16) if r.result else 0
    observed = [e for bit, e in enumerate(ELEMENTS) if target & (1 << bit)]
    if r.result.get("tripb") and "50BF-86B" not in observed:
        observed.append("50BF-86B")
    expected = EXPECTED[name]
    trips = [e for e in r.events if e["code"] == "TRIP1"]
    clear_ms = None
    if trips:
        t = trips[0]["soc"] - SCENARIO_T0_SOC + trips[0]["usec"] / 1e6
        clear_ms = round((t - FAULT_START_S) * 1000.0, 1)
    passed = (
        r.completed
        and sorted(observed) == sorted(expected["elements"])
        and bool(r.result.get("tripb")) == expected["bus_trip"]
    )
    return {
        "name": name,
        "description": expected["description"],
        "expected": expected["elements"] or ["no trip"],
        "observed": observed or ["no trip"],
        "bus_trip": bool(r.result.get("tripb")),
        "trip_ms": clear_ms,
        "util_pct": round(r.util_ppm / 10000.0, 2),
        "pass": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline")
    args = parser.parse_args()

    subprocess.run(["make", "-s", "-C", str(FIRMWARE), "sim"], check=True,
                   stdout=subprocess.DEVNULL)
    run_renode.build()

    names = sorted(run_renode.SCENARIOS, key=lambda n: run_renode.SCENARIOS[n][0])
    results = {}
    for name in names:
        print(f"renode: {name}", flush=True)
        results[name] = run_renode.run(name)

    tasks: dict[str, dict] = {}
    for name, r in results.items():
        for t in r.timing:
            if not t["budget"]:
                continue
            cur = tasks.get(t["task"])
            if cur is None or t["max"] > cur["max"]:
                tasks[t["task"]] = {**t, "worst_scenario": name}
    task_rows = []
    for t in tasks.values():
        headroom = round(100.0 * (1 - t["max"] / t["budget"]), 1)
        task_rows.append({
            "task": t["task"], "rate_hz": t["rate_hz"], "budget_cycles": t["budget"],
            "max_cycles": t["max"], "mean_cycles": t["mean"],
            "max_us": round(t["max"] / 168.0, 1), "headroom_pct": headroom,
            "worst_scenario": t["worst_scenario"],
            "status": "within budget" if t["max"] <= t["budget"] else "over budget",
        })

    compliance = []
    for c in COMPLIANCE:
        row = {k: v for k, v in c.items() if k != "suite"}
        if c["suite"] is None:
            row.update({"automated": False, "status": "not automated", "points": 0,
                        "worst_tve_pct": None})
        else:
            res = run_compliance(c["suite"])
            row.update({
                "automated": True,
                "status": "pass" if res["failed"] == 0 else "fail",
                "points": len(res["points"]),
                "worst_tve_pct": round(max(p["tve_pct"] for p in res["points"]), 4),
            })
        compliance.append(row)

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "label": args.label,
        "target": {
            "mcu": "STM32F407VG", "core": "Cortex-M4F", "cpu_hz": 168_000_000,
            "emulator": renode_version(),
            "resolution_cycles": run_renode.RESOLUTION_CYCLES,
            **target_footprint(),
            "method": "DWT cycle counter on the emulated core; instruction-accurate at "
                      "168 MIPS, no pipeline or flash wait-state model",
        },
        "rates": {"sample_hz": 1920, "protection_hz": 480, "pmu_hz": 60, "comms_hz": 120},
        "worst_util_pct": max(r["util_pct"] for r in
                              (scenario_row(n, results[n]) for n in names)),
        "tasks": task_rows,
        "scenarios": [scenario_row(n, results[n]) for n in names],
        "compliance": compliance,
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "realtime.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    over = [t["task"] for t in task_rows if t["status"] != "within budget"]
    failed = [s["name"] for s in report["scenarios"] if not s["pass"]]
    print(f"tasks over budget: {over or 'none'}; scenarios failed: {failed or 'none'}")
    return 1 if over or failed else 0


if __name__ == "__main__":
    sys.exit(main())
