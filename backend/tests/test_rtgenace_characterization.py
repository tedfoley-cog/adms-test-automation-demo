"""Characterization tests for the RTGENACE port.

These pin the *legacy* behaviour, not the behaviour we would like: the Fortran
batch task ``legacy/habitat/src/ace_calc.f90`` is built and executed against
``savecases/rtnet_ems_0742.export``, and the ported ``app.savecase`` +
``app.agc`` path is required to reproduce its printed Reporting ACE and
per-unit regulation setpoints.

Tolerance: the Fortran task carries every quantity in default REAL (IEEE
single precision) and prints with ``F12.4``; the Python services work in
double precision. The accumulated difference on this savecase is ~6.2e-3 MW on
ACE, so parity is asserted to PARITY_TOLERANCE_MW = 1.0e-2 MW — two orders of
magnitude below the 5.0 MW AGC deadband, so no allocation decision can turn on
it. Setpoints are compared to 1.0e-4 MW because they are clipped to ramp/unit
limits that are exactly representable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.agc import allocate_regulation, reporting_ace
from app.savecase import load_savecase

pytestmark = pytest.mark.characterization

REPO = Path(__file__).resolve().parents[2]
HABITAT = REPO / "legacy" / "habitat"
SAVECASE = HABITAT / "savecases" / "rtnet_ems_0742.export"

PARITY_TOLERANCE_MW = 1.0e-2
SETPOINT_TOLERANCE_MW = 1.0e-4
CONTROL_CYCLE_S = 4.0  # RTGENACE calls ALLOCR with CYCSEC = 4.0


@pytest.fixture(scope="module")
def legacy_replay() -> dict[str, object]:
    """Build and run the Fortran RTGENACE task, returning its printed results."""
    if shutil.which("gfortran") is None:  # pragma: no cover - CI always has gfortran
        pytest.skip("gfortran is required to replay the legacy RTGENACE task")

    subprocess.run(["make", "build/rtgenace"], cwd=HABITAT, check=True, capture_output=True)
    completed = subprocess.run(
        [str(HABITAT / "build" / "rtgenace"), str(SAVECASE)],
        cwd=HABITAT,
        check=True,
        capture_output=True,
        text=True,
    )

    name = ""
    ace = None
    setpoints: dict[str, float] = {}
    for line in completed.stdout.splitlines():
        if line.startswith("SAVECASE "):
            name = line.split(maxsplit=1)[1].strip()
        elif line.startswith("ACE_MW"):
            ace = float(line.split()[1])
        elif line.startswith("SETPT"):
            _, unit, value = line.split()
            setpoints[unit] = float(value)

    assert ace is not None, completed.stdout
    return {"name": name, "ace_mw": ace, "setpoints": setpoints}


@pytest.fixture(scope="module")
def modern_replay() -> dict[str, object]:
    case = load_savecase(SAVECASE)
    ace = reporting_ace(case.balancing_state())
    return {
        "name": case.name,
        "ace_mw": ace,
        "setpoints": allocate_regulation(case.units, ace, interval_s=CONTROL_CYCLE_S),
        "case": case,
    }


def test_savecase_name_matches_the_legacy_task(legacy_replay, modern_replay):
    assert modern_replay["name"] == legacy_replay["name"] == "RTNET_EMS_0742"


def test_reporting_ace_matches_the_fortran_replay(legacy_replay, modern_replay):
    assert modern_replay["ace_mw"] == pytest.approx(
        legacy_replay["ace_mw"], abs=PARITY_TOLERANCE_MW
    )


def test_reporting_ace_sign_and_magnitude_are_pinned(legacy_replay):
    # A negative ACE means the area is under-generating and AGC must raise.
    assert legacy_replay["ace_mw"] < 0.0
    assert legacy_replay["ace_mw"] == pytest.approx(-116.3462, abs=1e-4)


def test_ace_parity_delta_stays_inside_the_documented_tolerance(legacy_replay, modern_replay):
    delta = abs(modern_replay["ace_mw"] - legacy_replay["ace_mw"])

    assert delta < PARITY_TOLERANCE_MW
    # Single-precision accumulation in Fortran, not a modelling difference:
    # the relative error is at the edge of float32 resolution.
    assert delta < 1e-4 * abs(legacy_replay["ace_mw"])


def test_every_unit_in_the_savecase_gets_a_setpoint(legacy_replay, modern_replay):
    assert set(modern_replay["setpoints"]) == set(legacy_replay["setpoints"])
    assert set(legacy_replay["setpoints"]) == {
        "GEN.HARBOR1",
        "GEN.HARBOR2",
        "GEN.MESQUITE_CT",
        "GEN.CEDAR_STM",
    }


@pytest.mark.parametrize(
    "unit",
    ["GEN.HARBOR1", "GEN.HARBOR2", "GEN.MESQUITE_CT", "GEN.CEDAR_STM"],
)
def test_unit_setpoint_matches_the_fortran_replay(unit, legacy_replay, modern_replay):
    assert modern_replay["setpoints"][unit] == pytest.approx(
        legacy_replay["setpoints"][unit], abs=SETPOINT_TOLERANCE_MW
    )


def test_ramp_limits_bind_on_this_savecase(legacy_replay):
    # 6 MW/min and 18 MW/min over a 4 s cycle: the legacy task clips to these.
    assert legacy_replay["setpoints"]["GEN.HARBOR1"] == pytest.approx(0.4, abs=1e-4)
    assert legacy_replay["setpoints"]["GEN.MESQUITE_CT"] == pytest.approx(1.2, abs=1e-4)


def test_unit_off_agc_never_moves(legacy_replay, modern_replay):
    assert legacy_replay["setpoints"]["GEN.CEDAR_STM"] == pytest.approx(0.0, abs=1e-6)
    assert modern_replay["setpoints"]["GEN.CEDAR_STM"] == pytest.approx(0.0, abs=1e-6)


def test_regulation_is_raised_against_a_negative_ace(modern_replay):
    assert all(value >= 0.0 for value in modern_replay["setpoints"].values())
    assert sum(modern_replay["setpoints"].values()) == pytest.approx(2.0, abs=1e-4)


def test_the_replay_output_format_is_stable(legacy_replay):
    # The demo and tools/build_legacy_inventory.py both scrape this output.
    completed = subprocess.run(
        [str(HABITAT / "build" / "rtgenace"), str(SAVECASE)],
        cwd=HABITAT,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = completed.stdout.splitlines()

    assert lines[0].startswith("SAVECASE ")
    assert re.match(r"^ACE_MW\s+-?\d+\.\d{4}$", lines[1])
    assert len(lines) == 2 + len(legacy_replay["setpoints"])


def test_rtgenace_rejects_a_missing_savecase(legacy_replay):
    completed = subprocess.run(
        [str(HABITAT / "build" / "rtgenace"), str(HABITAT / "savecases" / "does_not_exist")],
        cwd=HABITAT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "savecase read failed" in completed.stdout
