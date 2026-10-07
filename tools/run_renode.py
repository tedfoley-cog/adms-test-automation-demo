"""Run the feeder IED firmware on an emulated STM32F407 (Renode).

Boots firmware/target/stm32f407/build/ied.elf once per scenario, writes the
harness block (scenario, uptime preset, frequency override) into .noinit RAM
before the core starts, runs for the scenario's virtual duration and parses
the UART log into events, PMU frames and per-task cycle measurements.

    python tools/run_renode.py --scenario fault_ag_zone1
    python tools/run_renode.py --scenario steady_load --freq 59.5 --duration 4
    python tools/run_renode.py --scenario fault_ag_zone1 --uptime-days 25
    python tools/run_renode.py --all --json out.json

Cycle counts come from DWT->CYCCNT in Renode, which counts executed
instructions at the configured 168 MIPS with 1 us (168-cycle) resolution:
deterministic run to run, but not a model of pipeline stalls or flash wait
states on silicon.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware"
TARGET = FIRMWARE / "target" / "stm32f407"
ELF = TARGET / "build" / "ied.elf"
RESC = FIRMWARE / "renode" / "ied.resc"
REPL = FIRMWARE / "renode" / "ied_stm32f407.repl"

HARNESS_MAGIC = 0x49454421
PREROLL_S = 3.0
SLACK_S = 0.25
QUANTUM_S = "0.000001"
RESOLUTION_CYCLES = 168

# Mirrors the scenario table in firmware/testset/testset.c.
SCENARIOS = {
    "steady_load": (0, 1.0),
    "fault_ag_zone1": (1, 0.8),
    "fault_bc_zone2": (2, 1.0),
    "fault_ag_high_resistance": (3, 2.2),
    "breaker_failure": (4, 0.8),
}

TIMING_RE = re.compile(
    r"TIMING task=(\S+) rate_hz=(\d+) runs=(\d+) min=(\d+) mean=(\d+) max=(\d+) "
    r"budget=(\d+) overruns=(\d+)"
)
PMU_RE = re.compile(r"PMU (\d+)\.(\d+) f=(\S+) rocof=(\S+) v1=(\S+) stat=0x([0-9a-f]+) len=(\d+)")
SOE_RE = re.compile(r"SOE (\d+)\.(\d+) tick=(\d+) (\S+)(.*?) value=(\S+)")
RESULT_RE = re.compile(r"RESULT trip1=(\d) 86B=(\d) breaker_open=(\d) bus_dead=(\d) target=(\S+)")
UTIL_RE = re.compile(r"UTIL worst_case_ppm=(\d+) ring_overruns=(\d+) pmu_overruns=(\d+)")


@dataclass
class RunResult:
    scenario: str
    uptime_s: int
    freq_hz: float | None
    timing: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    pmu: list[dict] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    util_ppm: int = 0
    ring_overruns: int = 0
    pmu_overruns: int = 0
    completed: bool = False
    log: str = ""


def build() -> None:
    subprocess.run(["make", "-s", "-C", str(TARGET)], check=True, stdout=subprocess.DEVNULL)


def symbol_address(name: str) -> int:
    out = subprocess.run(
        ["arm-none-eabi-nm", str(ELF)], check=True, capture_output=True, text=True
    ).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == name:
            return int(parts[0], 16)
    raise SystemExit(f"symbol {name} not found in {ELF}")


def run(scenario: str, uptime_s: int = 0, freq_hz: float | None = None,
        duration_s: float | None = None) -> RunResult:
    if shutil.which("renode") is None:
        raise SystemExit("renode not found on PATH")
    index, default_duration = SCENARIOS[scenario]
    duration = duration_s if duration_s is not None else default_duration
    harness = symbol_address("g_harness")
    words = [
        HARNESS_MAGIC,
        index,
        uptime_s,
        round(freq_hz * 1000) & 0xFFFFFFFF if freq_hz else 0,
        round(duration * 1000) if duration_s is not None else 0,
    ]

    with tempfile.TemporaryDirectory() as tmp:
        uart = Path(tmp) / "uart.log"
        pokes = "; ".join(
            f"sysbus WriteDoubleWord {harness + 4 * k:#x} {w:#x}" for k, w in enumerate(words)
        )
        # Warm-up with the default quantum, then a 1 us quantum (168 cycles at
        # 168 MIPS) so DWT->CYCCNT resolves individual task executions.
        warmup = PREROLL_S - 0.05
        measured = 0.05 + duration + SLACK_S
        commands = (
            f"$elf=@{ELF}; $uart=@{uart}; $repl=@{REPL}; include @{RESC}; {pokes}; "
            f'emulation RunFor "{warmup:.3f}"; emulation SetGlobalQuantum "{QUANTUM_S}"; '
            f'emulation RunFor "{measured:.3f}"; quit'
        )
        subprocess.run(
            ["renode", "--disable-xwt", "--console", "--plain", "-e", commands],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=900,
        )
        log = uart.read_text(errors="replace") if uart.exists() else ""

    return parse(scenario, uptime_s, freq_hz, log)


def parse(scenario: str, uptime_s: int, freq_hz: float | None, log: str) -> RunResult:
    r = RunResult(scenario=scenario, uptime_s=uptime_s, freq_hz=freq_hz, log=log)
    for line in log.splitlines():
        if m := TIMING_RE.search(line):
            name, rate, runs, mn, mean, mx, budget, over = m.groups()
            r.timing.append({
                "task": name, "rate_hz": int(rate), "runs": int(runs), "min": int(mn),
                "mean": int(mean), "max": int(mx), "budget": int(budget), "overruns": int(over),
            })
        elif m := PMU_RE.search(line):
            soc, frac, f, rocof, v1, stat, length = m.groups()
            r.pmu.append({
                "soc": int(soc), "fracsec_us": int(frac), "freq_hz": float(f),
                "rocof_hz_s": float(rocof), "v1": float(v1), "stat": int(stat, 16),
                "len": int(length),
            })
        elif m := SOE_RE.search(line):
            soc, usec, tick, code, detail, value = m.groups()
            r.events.append({
                "soc": int(soc), "usec": int(usec), "tick": int(tick), "code": code,
                "detail": detail.strip(), "value": float(value),
            })
        elif m := RESULT_RE.search(line):
            t1, b, bo, bd, tgt = m.groups()
            r.result = {"trip1": t1 == "1", "tripb": b == "1", "breaker_open": bo == "1",
                        "bus_dead": bd == "1", "target": tgt}
        elif m := UTIL_RE.search(line):
            r.util_ppm, r.ring_overruns, r.pmu_overruns = (int(x) for x in m.groups())
        elif line.strip() == "DONE":
            r.completed = True
    return r


def summarise(r: RunResult) -> str:
    lines = [f"== {r.scenario} (uptime {r.uptime_s} s"
             + (f", {r.freq_hz} Hz" if r.freq_hz else "") + ")"]
    for e in r.events:
        lines.append(f"  SOE {e['soc']}.{e['usec']:06d} {e['code']} {e['detail']} {e['value']}")
    if r.pmu:
        f = [p["freq_hz"] for p in r.pmu]
        rc = [abs(p["rocof_hz_s"]) for p in r.pmu]
        lines.append(f"  PMU frames={len(r.pmu)} f=[{min(f):.4f}, {max(f):.4f}] "
                     f"max|rocof|={max(rc):.3f}")
    for t in r.timing:
        flag = "OVER" if t["budget"] and t["max"] > t["budget"] else "ok"
        lines.append(f"  {t['task']:<10} max={t['max']:>7} mean={t['mean']:>7} "
                     f"budget={t['budget']:>7} {flag}")
    lines.append(f"  util={r.util_ppm / 10000:.2f}%  result={r.result}  completed={r.completed}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--uptime-s", type=int, default=0)
    ap.add_argument("--uptime-days", type=float)
    ap.add_argument("--freq", type=float)
    ap.add_argument("--duration", type=float)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--log", action="store_true", help="print the raw UART log")
    args = ap.parse_args(argv)
    if not args.scenario and not args.all:
        ap.error("--scenario or --all is required")

    build()
    uptime = int(args.uptime_days * 86400) if args.uptime_days is not None else args.uptime_s
    names = sorted(SCENARIOS, key=lambda n: SCENARIOS[n][0]) if args.all else [args.scenario]
    results = []
    for name in names:
        r = run(name, uptime, args.freq, args.duration)
        results.append(r)
        print(summarise(r))
        if args.log:
            print(r.log)
    if args.json:
        args.json.write_text(json.dumps(
            [{k: v for k, v in asdict(r).items() if k != "log"} for r in results], indent=2))
    over = any(t["budget"] and t["max"] > t["budget"] for r in results for t in r.timing)
    incomplete = any(not r.completed for r in results)
    return 1 if over or incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
