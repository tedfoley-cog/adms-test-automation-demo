"""Run the legacy RTGENACE binary and compare it with the ACE service.

Used by the characterization and parity tests and by tools/build_legacy_inventory.py.
Tolerances follow docs/specs/RTGENACE.md §5.4.
"""

from __future__ import annotations

import math
import os
import random
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from ace_service.ace import CONTROL_CYCLE_S, DEADBAND_MW, allocate_regulation, reporting_ace
from ace_service.hdb_export import parse_export, to_area_payload
from ace_service.schemas import AreaState

REPO = Path(__file__).resolve().parents[3]
LEGACY = REPO / "legacy" / "habitat"
REFERENCE_SAVECASE = LEGACY / "savecases" / "rtnet_ems_0742.export"
PRINT_RESOLUTION = 2e-4
RELATIVE_F32 = 1e-6


@dataclass
class LegacyRun:
    returncode: int
    stdout: str
    name: str | None = None
    ace: float | None = None
    setpoints: list[tuple[str, float]] = field(default_factory=list)
    ierr: int | None = None


@cache
def legacy_binary() -> Path:
    override = os.environ.get("RTGENACE_BIN")
    if override:
        return Path(override)
    subprocess.run(["make", "--silent", "all"], cwd=LEGACY, check=True)
    return LEGACY / "build" / "rtgenace"


def parse_legacy_output(returncode: int, stdout: str) -> LegacyRun:
    run = LegacyRun(returncode=returncode, stdout=stdout)
    for line in stdout.splitlines():
        if line.startswith("SAVECASE "):
            run.name = line[9:].strip()
        elif line.startswith("ACE_MW"):
            run.ace = float(line.split()[1])
        elif line.startswith("SETPT"):
            run.setpoints.append((line[9:29].rstrip(), float(line[29:])))
        elif "ierr=" in line:
            run.ierr = int(line.split("ierr=")[1])
    return run


def run_legacy_path(*args: str) -> LegacyRun:
    proc = subprocess.run([str(legacy_binary()), *args], capture_output=True, text=True, check=False)
    return parse_legacy_output(proc.returncode, proc.stdout + proc.stderr)


def run_legacy(text: str) -> LegacyRun:
    with tempfile.NamedTemporaryFile("w", suffix=".export", delete=False) as handle:
        handle.write(text)
        path = handle.name
    try:
        return run_legacy_path(path)
    finally:
        os.unlink(path)


def area_from_text(text: str) -> AreaState:
    return AreaState.model_validate(to_area_payload(parse_export(text)))


def f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def half_ulp32(value: float) -> float:
    if value == 0.0:
        return 2.0**-150
    _, exponent = math.frexp(abs(f32(value)))
    return 2.0 ** (exponent - 25)


def quantised(area: AreaState) -> AreaState:
    """The same area with every real rounded to REAL*4, as the Fortran stores it."""
    payload = area.model_dump()

    def walk(node: object) -> object:
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, float):
            return f32(node)
        return node

    return AreaState.model_validate(walk(payload))


def ace_terms(area: AreaState) -> float:
    ties = sum(abs(t.actual_mw) + abs(t.scheduled_mw) for t in area.tie_lines)
    freq = area.frequency
    bias = abs(10.0 * freq.bias_mw_per_0_1hz * (freq.actual_hz - freq.scheduled_hz))
    return ties + bias + abs(area.meter_error_mw)


def ace_bound(area: AreaState) -> float:
    """Analytic float32 bound on |ACE_legacy - ACE_service| (spec §5.4)."""
    freq = area.frequency
    bound = 10.0 * abs(freq.bias_mw_per_0_1hz) * (half_ulp32(freq.actual_hz) + half_ulp32(freq.scheduled_hz))
    bound += 10.0 * half_ulp32(freq.bias_mw_per_0_1hz) * abs(freq.actual_hz - freq.scheduled_hz)
    bound += sum(half_ulp32(t.actual_mw) + half_ulp32(t.scheduled_mw) for t in area.tie_lines)
    bound += half_ulp32(area.meter_error_mw)
    return bound + RELATIVE_F32 * ace_terms(area) + PRINT_RESOLUTION


@dataclass
class ParityOutcome:
    legacy: LegacyRun
    ace_service: float
    ace_logic_delta: float
    ace_engineering_delta: float
    setpoint_logic_delta: float
    setpoint_engineering_delta: float
    deadband_ambiguous: bool
    failures: list[str]
    categories: set[str]


def compare(text: str) -> ParityOutcome:
    """Replay one savecase through the Fortran and the service (spec §5.4, checks 1 and 2)."""
    legacy = run_legacy(text)
    if legacy.returncode != 0 or legacy.ace is None:
        raise AssertionError(f"legacy run failed: {legacy.stdout}")
    area = area_from_text(text)
    area32 = quantised(area)

    ace = reporting_ace(area)
    ace32 = reporting_ace(area32)
    deltas = allocate_regulation(area.units, ace)
    deltas32 = allocate_regulation(area32.units, ace32)

    logic_tol = PRINT_RESOLUTION + RELATIVE_F32 * ace_terms(area)
    eng_tol = ace_bound(area)
    failures: list[str] = []

    ace_logic = abs(ace32 - legacy.ace)
    ace_eng = abs(ace - legacy.ace)
    if ace_logic > logic_tol:
        failures.append(f"ACE logic delta {ace_logic:.6f} > {logic_tol:.6f}")
    if ace_eng > eng_tol:
        failures.append(f"ACE delta {ace_eng:.6f} > bound {eng_tol:.6f}")

    if [name for name, _ in legacy.setpoints] != [unit.id for unit in area.units]:
        failures.append("unit order or identity differs")

    ambiguous = abs(abs(ace) - DEADBAND_MW) <= eng_tol or abs(abs(ace32) - DEADBAND_MW) <= logic_tol
    sp_logic = sp_eng = 0.0
    if not ambiguous:
        for unit, (_, legacy_mw), delta, delta32 in zip(area.units, legacy.setpoints, deltas, deltas32, strict=True):
            unit_scale = abs(unit.output_mw) + abs(unit.max_mw) + abs(unit.min_mw)
            unit_logic_tol = logic_tol + RELATIVE_F32 * unit_scale
            unit_eng_tol = (
                eng_tol
                + RELATIVE_F32 * unit_scale
                + 2 * half_ulp32(unit.output_mw)
                + half_ulp32(unit.min_mw)
                + half_ulp32(unit.max_mw)
            )
            sp_logic = max(sp_logic, abs(delta32 - legacy_mw))
            sp_eng = max(sp_eng, abs(delta - legacy_mw))
            if abs(delta32 - legacy_mw) > unit_logic_tol:
                failures.append(f"{unit.id} logic delta {abs(delta32 - legacy_mw):.6f}")
            if abs(delta - legacy_mw) > unit_eng_tol:
                failures.append(f"{unit.id} delta {abs(delta - legacy_mw):.6f}")

    return ParityOutcome(
        legacy=legacy,
        ace_service=ace,
        ace_logic_delta=ace_logic,
        ace_engineering_delta=ace_eng,
        setpoint_logic_delta=sp_logic,
        setpoint_engineering_delta=sp_eng,
        deadband_ambiguous=ambiguous,
        failures=failures,
        categories=categorise(area, ace),
    )


def categorise(area: AreaState, ace: float) -> set[str]:
    found: set[str] = set()
    if abs(ace) <= DEADBAND_MW:
        found.add("deadband")
    participating = [u for u in area.units if u.on_agc and u.participation > 0.0]
    if len(participating) < len(area.units):
        found.add("non-participating unit")
    if area.units and not participating:
        found.add("no participation")
    if area.frequency.quality != "N":
        found.add("suspect frequency quality")
    total = sum(u.participation for u in participating)
    if abs(ace) > DEADBAND_MW and total > 0.0:
        for unit in participating:
            share = -ace * unit.participation / total
            ramp = unit.ramp_mw_per_min * CONTROL_CYCLE_S / 60.0
            if abs(share) > ramp:
                found.add("ramp clipped")
            target = unit.output_mw + max(-ramp, min(ramp, share))
            if not unit.min_mw <= unit.output_mw <= unit.max_mw:
                found.add("out-of-limit unit")
            elif target < unit.min_mw or target > unit.max_mw:
                found.add("limit clipped")
            if abs(share) <= ramp:
                found.add("pro-rata share")
    return found


def random_savecase(rng: random.Random, index: int) -> str:
    """A savecase drawn from RTGENACE's own input space."""
    lines = ["CLONE    RTNET.EMS", f"SAVECASE RANDOM_{index:04d}", "*"]
    bias = -round(rng.uniform(50.0, 1500.0), 1)
    near_deadband = rng.random() < 0.15
    if near_deadband:
        actual_hz, scheduled_hz = 60.0, 60.0
    else:
        actual_hz = round(rng.uniform(59.95, 60.05), 3)
        scheduled_hz = rng.choice([60.0, 60.0, 60.0, 59.98, 60.02])
    quality = "S" if rng.random() < 0.1 else "N"
    lines += ["RECORD FREQ", f"  AREA.RANDOM  {actual_hz:.3f}  {scheduled_hz:.3f}  {bias:.1f}  {quality}"]

    lines.append("RECORD TIELINE")
    for tie in range(rng.randint(1, 6)):
        scheduled = round(rng.uniform(-600.0, 600.0), 1)
        drift = rng.uniform(-6.0, 6.0) if near_deadband else rng.uniform(-80.0, 80.0)
        actual = round(scheduled + drift, 1)
        lines.append(f"  TIE.R{index}_{tie}  {actual:.1f}  {scheduled:.1f}  N")

    lines += ["RECORD METERR", f"  AREA.RANDOM  {round(rng.uniform(-3.0, 3.0), 1):.1f}"]

    lines.append("RECORD UNIT")
    for unit in range(rng.randint(1, 12)):
        low = round(rng.uniform(10.0, 300.0), 1)
        high = round(low + rng.uniform(20.0, 400.0), 1)
        roll = rng.random()
        if roll < 0.08:
            output = round(rng.choice([low - rng.uniform(1.0, 40.0), high + rng.uniform(1.0, 40.0)]), 1)
        elif roll < 0.2:
            output = round(rng.choice([low + rng.uniform(0.0, 0.6), high - rng.uniform(0.0, 0.6)]), 1)
        else:
            output = round(rng.uniform(low, high), 1)
        ramp = round(rng.uniform(0.5, 30.0), 1)
        share = 0.0 if rng.random() < 0.2 else round(rng.uniform(0.01, 1.0), 2)
        agc = "T" if rng.random() < 0.85 else "F"
        lines.append(f"  GEN.R{index}_{unit}  {output:.1f}  {low:.1f}  {high:.1f}  {ramp:.1f}  {share:.2f}  {agc}")
    lines.append("END")
    return "\n".join(lines) + "\n"


@dataclass
class SweepSummary:
    cases: int
    seed: int
    failures: list[str]
    deadband_ambiguous: int
    max_ace_logic_delta: float
    max_ace_engineering_delta: float
    max_setpoint_logic_delta: float
    max_setpoint_engineering_delta: float
    categories: dict[str, int]


def sweep(cases: int = 500, seed: int = 742) -> SweepSummary:
    rng = random.Random(seed)
    failures: list[str] = []
    ambiguous = 0
    maxima = [0.0, 0.0, 0.0, 0.0]
    categories: dict[str, int] = {}
    for index in range(cases):
        outcome = compare(random_savecase(rng, index))
        failures += [f"RANDOM_{index:04d}: {failure}" for failure in outcome.failures]
        ambiguous += int(outcome.deadband_ambiguous)
        maxima = [
            max(maxima[0], outcome.ace_logic_delta),
            max(maxima[1], outcome.ace_engineering_delta),
            max(maxima[2], outcome.setpoint_logic_delta),
            max(maxima[3], outcome.setpoint_engineering_delta),
        ]
        for category in outcome.categories:
            categories[category] = categories.get(category, 0) + 1
    return SweepSummary(cases, seed, failures, ambiguous, *maxima, dict(sorted(categories.items())))
