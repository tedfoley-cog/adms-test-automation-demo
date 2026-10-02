"""Characterization tests for the legacy RTGENACE batch task.

These pin the behaviour of the Fortran task (``legacy/habitat/src/ace_calc.f90``)
before the ported service (``app/agc.py`` + ``app/savecase.py``) is trusted: every
case here replays the same savecase export through both implementations and
compares Reporting ACE and the per-unit regulation setpoints.

Tolerance: the legacy task carries every quantity in Fortran ``REAL`` (IEEE
binary32, ~7 significant digits) and prints with ``F12.4``, while the service
computes in double precision. The difference is dominated by the bias term
``10 * B * (F_a - F_s)``, where a bias of several hundred MW/0.1 Hz multiplies a
frequency deviation of order 0.05 Hz; on the operating points exercised here that
leaves an ACE residual below 0.02 MW. Anything larger is a behavioural difference,
not arithmetic.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.agc import allocate_regulation, reporting_ace
from app.savecase import load_savecase

REPO = Path(__file__).resolve().parents[2]
LEGACY = REPO / "legacy" / "habitat"
RTGENACE = LEGACY / "build" / "rtgenace"
SAVECASE = LEGACY / "savecases" / "rtnet_ems_0742.export"

ACE_TOL_MW = 0.02
SETPOINT_TOL_MW = 0.01

pytestmark = pytest.mark.skipif(
    shutil.which("gfortran") is None, reason="gfortran is required to replay the legacy task"
)


@pytest.fixture(scope="session")
def rtgenace() -> Path:
    subprocess.run(["make", "--silent", "all"], cwd=LEGACY, check=True)
    return RTGENACE


def legacy_replay(binary: Path, path: Path) -> dict[str, float]:
    """Run the Fortran task and parse its ACE_MW / SETPT report."""
    completed = subprocess.run([str(binary), str(path)], capture_output=True, text=True, check=True)
    result: dict[str, float] = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if fields[0] == "ACE_MW":
            result["ACE_MW"] = float(fields[1])
        elif fields[0] == "SETPT":
            result[fields[1]] = float(fields[2])
    return result


def modern_replay(path: Path) -> dict[str, float]:
    case = load_savecase(path)
    ace = reporting_ace(case.balancing_state())
    result = {"ACE_MW": ace}
    result.update(allocate_regulation(case.units, ace))
    return result


def export(
    units: list[str], freq: str = "59.968", bias: str = "-412.0", meterr: str = "2.5"
) -> str:
    unit_lines = "\n".join(f"  {unit}" for unit in units)
    return f"""* synthetic savecase for characterization
CLONE    RTNET.EMS
SAVECASE RTNET_EMS_SYNTH
TIMESTAMP 2026-02-11T07:42:00Z
RECORD FREQ
  AREA.CEDARVALLEY {freq} 60.000 {bias} N
RECORD TIELINE
  TIE.NORTH340 418.2 400.0 N
  TIE.EAST115 -132.6 -140.0 N
  TIE.SOUTH230 97.4 105.0 N
RECORD METERR
  AREA.CEDARVALLEY {meterr}
RECORD UNIT
{unit_lines}
END
"""


def assert_parity(binary: Path, path: Path) -> dict[str, float]:
    legacy = legacy_replay(binary, path)
    modern = modern_replay(path)

    assert set(legacy) == set(modern)
    assert modern["ACE_MW"] == pytest.approx(legacy["ACE_MW"], abs=ACE_TOL_MW)
    for unit, setpoint in legacy.items():
        if unit == "ACE_MW":
            continue
        assert modern[unit] == pytest.approx(setpoint, abs=SETPOINT_TOL_MW), unit
    return legacy


@pytest.mark.characterization
def test_shipped_savecase_reporting_ace(rtgenace: Path):
    legacy = legacy_replay(rtgenace, SAVECASE)
    modern = modern_replay(SAVECASE)

    assert legacy["ACE_MW"] == pytest.approx(-116.3462, abs=1e-4)
    assert modern["ACE_MW"] == pytest.approx(legacy["ACE_MW"], abs=ACE_TOL_MW)


@pytest.mark.characterization
def test_shipped_savecase_unit_setpoints(rtgenace: Path):
    legacy = legacy_replay(rtgenace, SAVECASE)
    modern = modern_replay(SAVECASE)

    assert legacy == pytest.approx(
        {
            "ACE_MW": -116.3462,
            "GEN.HARBOR1": 0.4,
            "GEN.HARBOR2": 0.4,
            "GEN.MESQUITE_CT": 1.2,
            "GEN.CEDAR_STM": 0.0,
        },
        abs=1e-4,
    )
    for unit in ("GEN.HARBOR1", "GEN.HARBOR2", "GEN.MESQUITE_CT", "GEN.CEDAR_STM"):
        assert modern[unit] == pytest.approx(legacy[unit], abs=SETPOINT_TOL_MW)


@pytest.mark.characterization
def test_deadband_holds_every_unit(rtgenace: Path, tmp_path: Path):
    """On-schedule interchange and frequency put ACE inside the 5 MW deadband."""
    path = tmp_path / "deadband.export"
    path.write_text(
        """CLONE    RTNET.EMS
SAVECASE RTNET_EMS_DEADBAND
RECORD FREQ
  AREA.CEDARVALLEY 60.000 60.000 -412.0 N
RECORD TIELINE
  TIE.NORTH340 402.0 400.0 N
RECORD METERR
  AREA.CEDARVALLEY 0.0
RECORD UNIT
  GEN.HARBOR1 212.0 120.0 260.0 6.0 0.45 T
  GEN.HARBOR2 188.5 120.0 260.0 6.0 0.35 T
END
""",
        encoding="utf-8",
    )

    legacy = assert_parity(rtgenace, path)

    assert legacy["ACE_MW"] == pytest.approx(2.0, abs=ACE_TOL_MW)
    assert legacy["GEN.HARBOR1"] == 0.0
    assert legacy["GEN.HARBOR2"] == 0.0


@pytest.mark.characterization
def test_ramp_bound_allocation(rtgenace: Path, tmp_path: Path):
    path = tmp_path / "ramp.export"
    path.write_text(
        export(
            [
                "GEN.HARBOR1 212.0 120.0 260.0 6.0 0.45 T",
                "GEN.MESQUITE_CT 44.0 20.0 120.0 18.0 0.20 T",
            ]
        ),
        encoding="utf-8",
    )

    legacy = assert_parity(rtgenace, path)

    assert legacy["GEN.HARBOR1"] == pytest.approx(0.4, abs=1e-4)
    assert legacy["GEN.MESQUITE_CT"] == pytest.approx(1.2, abs=1e-4)


@pytest.mark.characterization
def test_participation_split_when_ramp_is_not_binding(rtgenace: Path, tmp_path: Path):
    path = tmp_path / "participation.export"
    path.write_text(
        export(
            [
                "GEN.HARBOR1 212.0 120.0 400.0 900.0 0.45 T",
                "GEN.HARBOR2 188.5 120.0 400.0 900.0 0.35 T",
                "GEN.MESQUITE_CT 44.0 20.0 400.0 900.0 0.20 T",
            ]
        ),
        encoding="utf-8",
    )

    legacy = assert_parity(rtgenace, path)

    # ACE = -116.34, correction split 45/35/20
    assert legacy["GEN.HARBOR1"] == pytest.approx(52.35, abs=0.02)
    assert legacy["GEN.HARBOR2"] == pytest.approx(40.72, abs=0.02)
    assert legacy["GEN.MESQUITE_CT"] == pytest.approx(23.27, abs=0.02)


@pytest.mark.characterization
def test_unit_high_limit_truncates_the_share(rtgenace: Path, tmp_path: Path):
    path = tmp_path / "high_limit.export"
    path.write_text(
        export(["GEN.HARBOR1 259.9 120.0 260.0 900.0 1.00 T"]),
        encoding="utf-8",
    )

    legacy = assert_parity(rtgenace, path)

    assert legacy["GEN.HARBOR1"] == pytest.approx(0.1, abs=1e-3)


@pytest.mark.characterization
def test_unit_low_limit_truncates_the_share(rtgenace: Path, tmp_path: Path):
    """Over-generation (positive ACE) against a unit already near its minimum."""
    path = tmp_path / "low_limit.export"
    path.write_text(
        export(["GEN.HARBOR1 120.05 120.0 260.0 900.0 1.00 T"], freq="60.040"),
        encoding="utf-8",
    )

    legacy = assert_parity(rtgenace, path)

    assert legacy["ACE_MW"] > 5.0
    assert legacy["GEN.HARBOR1"] == pytest.approx(-0.05, abs=1e-3)


@pytest.mark.characterization
def test_units_off_agc_or_without_participation_are_skipped(rtgenace: Path, tmp_path: Path):
    path = tmp_path / "off_agc.export"
    path.write_text(
        export(
            [
                "GEN.HARBOR1 212.0 120.0 260.0 6.0 0.45 T",
                "GEN.CEDAR_STM 305.0 240.0 340.0 3.0 0.50 F",
                "GEN.ZEROPF 100.0 50.0 200.0 9.0 0.00 T",
            ]
        ),
        encoding="utf-8",
    )

    legacy = assert_parity(rtgenace, path)

    assert legacy["GEN.HARBOR1"] == pytest.approx(0.4, abs=1e-4)
    assert legacy["GEN.CEDAR_STM"] == 0.0
    assert legacy["GEN.ZEROPF"] == 0.0


@pytest.mark.characterization
def test_no_units_on_agc_leaves_everything_at_zero(rtgenace: Path, tmp_path: Path):
    path = tmp_path / "none_on_agc.export"
    path.write_text(
        export(["GEN.CEDAR_STM 305.0 240.0 340.0 3.0 0.50 F"]),
        encoding="utf-8",
    )

    legacy = assert_parity(rtgenace, path)

    assert legacy["GEN.CEDAR_STM"] == 0.0


@pytest.mark.characterization
@pytest.mark.parametrize(
    "frequency,bias",
    [("59.900", "-412.0"), ("60.050", "-412.0"), ("59.968", "-180.0"), ("60.000", "-600.0")],
)
def test_parity_across_operating_points(rtgenace: Path, tmp_path: Path, frequency: str, bias: str):
    path = tmp_path / f"op_{frequency}_{bias}.export"
    path.write_text(
        export(
            [
                "GEN.HARBOR1 212.0 120.0 260.0 6.0 0.45 T",
                "GEN.HARBOR2 188.5 120.0 260.0 6.0 0.35 T",
                "GEN.MESQUITE_CT 44.0 20.0 120.0 18.0 0.20 T",
                "GEN.CEDAR_STM 305.0 240.0 340.0 3.0 0.00 F",
            ],
            freq=frequency,
            bias=bias,
        ),
        encoding="utf-8",
    )

    assert_parity(rtgenace, path)
