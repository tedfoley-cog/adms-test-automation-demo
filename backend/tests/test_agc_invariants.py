"""Safety invariants of AGC regulation and live legacy/port parity for RTGENACE."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from rtgenace_corpus import build_legacy_binary, parse_report, run_binary

from app import rtgenace
from app.agc import DEADBAND_MW, allocate_regulation, reporting_ace
from app.models import BalancingState, TieLine, Unit
from app.savecase import load_savecase

INVARIANT_CASES = 1000
PARITY_CASES = 500
ROUNDING = 5e-5  # setpoints are rounded to 4 decimals


def random_fleet(rng: random.Random, in_limits: bool) -> list[Unit]:
    units = []
    for index in range(rng.randint(1, 10)):
        lo = rng.uniform(0.0, 300.0)
        hi = lo + rng.uniform(1.0, 400.0)
        mw = rng.uniform(lo, hi) if in_limits else rng.uniform(lo - 50.0, hi + 50.0)
        units.append(
            Unit(
                name=f"GEN.{index:02d}",
                output_mw=mw,
                min_mw=lo,
                max_mw=hi,
                ramp_mw_per_min=rng.uniform(0.0, 60.0),
                participation=rng.choice([0.0, -0.1, rng.uniform(0.0, 1.0), rng.uniform(0.0, 1.0)]),
                on_agc=rng.random() > 0.2,
            )
        )
    return units


@pytest.mark.parametrize("seed", range(INVARIANT_CASES))
def test_regulation_never_overcorrects_or_violates_ramp_and_limits(seed: int) -> None:
    rng = random.Random(seed)
    units = random_fleet(rng, in_limits=True)
    ace = rng.choice([rng.uniform(-DEADBAND_MW, DEADBAND_MW), rng.uniform(-600.0, 600.0)])

    setpoints = allocate_regulation(units, ace)

    assert list(setpoints) == [unit.name for unit in units]
    if abs(ace) <= DEADBAND_MW:
        assert all(mw == 0.0 for mw in setpoints.values())
        return
    for unit in units:
        delta = setpoints[unit.name]
        if not unit.on_agc or unit.participation <= 0.0:
            assert delta == 0.0
            continue
        assert delta * ace <= 0.0, "regulation must oppose ACE"
        assert abs(delta) <= unit.ramp_mw_per_min * 4.0 / 60.0 + ROUNDING
        assert unit.min_mw - ROUNDING <= unit.output_mw + delta <= unit.max_mw + ROUNDING
    assert abs(sum(setpoints.values())) <= abs(ace) + len(units) * ROUNDING


@pytest.mark.parametrize("seed", range(0, INVARIANT_CASES, 10))
def test_regulation_returns_out_of_limit_units_to_their_band(seed: int) -> None:
    rng = random.Random(seed)
    units = random_fleet(rng, in_limits=False)
    ace = rng.uniform(DEADBAND_MW + 0.1, 600.0) * rng.choice([-1, 1])

    setpoints = allocate_regulation(units, ace)

    for unit in units:
        if unit.on_agc and unit.participation > 0.0:
            assert unit.min_mw - ROUNDING <= unit.output_mw + setpoints[unit.name]
            assert unit.output_mw + setpoints[unit.name] <= unit.max_mw + ROUNDING


def test_no_regulation_when_participation_pool_is_empty() -> None:
    units = [
        Unit(name="A", output_mw=100, min_mw=0, max_mw=200, ramp_mw_per_min=30, participation=0.0),
        Unit(
            name="B",
            output_mw=100,
            min_mw=0,
            max_mw=200,
            ramp_mw_per_min=30,
            participation=0.5,
            on_agc=False,
        ),
    ]
    assert allocate_regulation(units, -80.0) == {"A": 0.0, "B": 0.0}


def test_reporting_ace_sign_conventions() -> None:
    def ace(actual: float, scheduled: float, freq: float, meter_error: float = 0.0) -> float:
        return reporting_ace(
            BalancingState(
                tie_lines=[TieLine(name="T", actual_mw=actual, scheduled_mw=scheduled)],
                actual_frequency_hz=freq,
                frequency_bias_mw_per_0_1hz=-100.0,
                meter_error_mw=meter_error,
            )
        )

    assert ace(110.0, 100.0, 60.0) == pytest.approx(10.0)  # over-exporting: ACE positive
    assert ace(100.0, 100.0, 59.99) == pytest.approx(-10.0)  # low frequency: bias term
    assert ace(100.0, 100.0, 60.0, meter_error=3.0) == pytest.approx(-3.0)


def random_export(rng: random.Random, index: int) -> str:
    fs = rng.choice([60.0, 59.98, 60.02])
    fa = round(fs + rng.gauss(0.0, 0.02), 3)
    bias = -round(rng.uniform(20.0, 2000.0), 1)
    lines = [
        "CLONE    RTNET.EMS",
        f"SAVECASE FUZZ_{index:04d}",
        "RECORD FREQ",
        f"  AREA.FUZZ  {fa:.3f}  {fs:.3f}  {bias:.1f}  N",
        "RECORD TIELINE",
    ]
    for t in range(rng.randint(0, 8)):
        sched = round(rng.uniform(-900.0, 900.0), 2)
        lines.append(f"  TIE.F{t:02d}  {sched + rng.gauss(0.0, 20.0):.3f}  {sched:.2f}  N")
    lines += ["RECORD METERR", f"  AREA.FUZZ  {rng.uniform(-10.0, 10.0):.2f}", "RECORD UNIT"]
    for u in range(rng.randint(0, 12)):
        lo = round(rng.uniform(0.0, 400.0), 1)
        hi = round(lo + rng.uniform(-20.0, 500.0), 1)
        lines.append(
            f"  GEN.F{u:02d}  {rng.uniform(lo - 30.0, hi + 30.0):.2f}  {lo:.1f}  {hi:.1f}  "
            f"{rng.uniform(0.0, 60.0):.1f}  {rng.uniform(-0.2, 1.0):.3f}  "
            f"{'T' if rng.random() > 0.15 else 'F'}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def legacy_binary() -> Path:
    binary = build_legacy_binary()
    if binary is None:
        pytest.skip("gfortran not installed: live parity needs the legacy binary")
    return binary


def test_port_matches_live_legacy_binary_on_seeded_savecases(
    legacy_binary: Path, tmp_path: Path
) -> None:
    rng = random.Random(20260742)
    failures = []
    for index in range(PARITY_CASES):
        path = tmp_path / f"fuzz_{index:04d}.export"
        path.write_text(random_export(rng, index), encoding="utf-8")
        golden = run_binary(legacy_binary, str(path))
        assert golden["exit_code"] == 0, golden
        legacy = parse_report(golden["stdout"])
        case = load_savecase(path)
        modern = rtgenace.run(case)

        if abs(modern.ace_mw - legacy.ace_mw) > rtgenace.ace_parity_bound(case):
            failures.append((index, "ace", modern.ace_mw, legacy.ace_mw))
            continue
        if rtgenace.deadband_indeterminate(case, modern.ace_mw):
            expected = allocate_regulation(case.units, legacy.ace_mw)
            if [mw for _, mw in legacy.setpoints] != [expected[u.name] for u in case.units]:
                failures.append((index, "deadband", modern.ace_mw, legacy.ace_mw))
            continue
        for unit, ((name, ours), (_, theirs)) in enumerate(
            zip(modern.setpoints, legacy.setpoints, strict=True)
        ):
            if abs(ours - theirs) > rtgenace.setpoint_parity_bound(case, unit, modern.ace_mw):
                failures.append((index, name, ours, theirs))
    assert failures == []
