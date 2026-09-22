"""Characterization tests for the HDB savecase reader port.

``backend/app/savecase.py`` replaces ``HDB_READ_EXPORT`` in
``legacy/habitat/src/hab_savecase.f90``. Rather than restating what the
Fortran source looks like, every test here runs a real legacy binary
(``rtgenace`` for FREQ/TIELINE/METERR/UNIT, ``loadshed`` for FEEDER and
frequency quality) over a crafted export and requires the Python reader to
agree with what the Fortran reader actually did.

Tolerance: the Fortran side is single precision and prints F12.4/F10.3, so
field values are compared to TOL = 1.0e-3 MW / Hz. Reporting ACE accumulates
several single-precision terms, so it is compared to ACE_TOL = 1.0e-2 MW, the
same tolerance the RTGENACE parity suite documents.
"""

from __future__ import annotations

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

TOL = 1.0e-3
ACE_TOL = 1.0e-2


@pytest.fixture(scope="module", autouse=True)
def legacy_binaries() -> None:
    if shutil.which("gfortran") is None:  # pragma: no cover - CI always has gfortran
        pytest.skip("gfortran is required to run the legacy savecase reader")
    subprocess.run(["make", "all"], cwd=HABITAT, check=True, capture_output=True)


def run_legacy(task: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HABITAT / "build" / task), str(path)],
        cwd=HABITAT,
        capture_output=True,
        text=True,
    )


def legacy_fields(task: str, path: Path) -> dict[str, str]:
    completed = run_legacy(task, path)
    assert completed.returncode == 0, completed.stdout
    fields: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if line.startswith(("SETPT", "TRIP")):
            _, key, value = line.split()
            fields[key] = value
        else:
            key, _, value = line.partition(" ")
            fields[key] = value.strip()
    return fields


def write_export(tmp_path: Path, body: str, name: str = "case.export") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = """\
CLONE    RTNET.EMS
SAVECASE CHARACTERIZATION
TIMESTAMP 2026-02-11T07:42:00Z
RECORD FREQ
  AREA.TEST             59.900       60.000      -100.0    N
RECORD TIELINE
  TIE.A                  100.0          60.0        N
RECORD METERR
  AREA.TEST                1.5
RECORD UNIT
  GEN.A                  100.0     50.0     200.0      60.0      1.00     T
RECORD FEEDER
  FDR.A                    5.0          1            2
END
"""


def test_header_records_are_read_the_same_way(tmp_path):
    path = write_export(tmp_path, MINIMAL)

    assert legacy_fields("rtgenace", path)["SAVECASE"] == "CHARACTERIZATION"
    assert load_savecase(path).name == "CHARACTERIZATION"


def test_freq_record_fields_reach_the_ace_calculation(tmp_path):
    path = write_export(tmp_path, MINIMAL)
    case = load_savecase(path)

    assert case.actual_frequency_hz == pytest.approx(59.9, abs=TOL)
    assert case.scheduled_frequency_hz == pytest.approx(60.0, abs=TOL)
    assert case.frequency_bias_mw_per_0_1hz == pytest.approx(-100.0, abs=TOL)
    assert case.frequency_quality == "N"
    assert float(legacy_fields("loadshed", path)["FREQ_HZ"]) == pytest.approx(59.9, abs=TOL)


def test_freq_quality_flag_is_carried_through(tmp_path):
    path = write_export(tmp_path, MINIMAL.replace("-100.0    N", "-100.0    Q"))

    assert load_savecase(path).frequency_quality == "Q"
    assert "quality not normal" in run_legacy("loadshed", path).stdout


def test_tieline_records_accumulate_in_file_order(tmp_path):
    body = MINIMAL.replace(
        "  TIE.A                  100.0          60.0        N\n",
        "  TIE.A                  100.0          60.0        N\n"
        "  TIE.B                  -40.0         -55.0        N\n",
    )
    path = write_export(tmp_path, body)
    case = load_savecase(path)

    assert [line.name for line in case.tie_lines] == ["TIE.A", "TIE.B"]
    assert [line.actual_mw for line in case.tie_lines] == [100.0, -40.0]
    assert [line.scheduled_mw for line in case.tie_lines] == [60.0, -55.0]


def test_meterr_record_is_subtracted_exactly_as_the_legacy_task_does(tmp_path):
    with_error = write_export(tmp_path, MINIMAL, "with.export")
    without_error = write_export(
        tmp_path,
        MINIMAL.replace("  AREA.TEST                1.5\n", ""),
        "without.export",
    )

    legacy_delta = float(legacy_fields("rtgenace", with_error)["ACE_MW"]) - float(
        legacy_fields("rtgenace", without_error)["ACE_MW"]
    )
    modern_delta = reporting_ace(load_savecase(with_error).balancing_state()) - reporting_ace(
        load_savecase(without_error).balancing_state()
    )

    assert load_savecase(with_error).meter_error_mw == pytest.approx(1.5, abs=TOL)
    assert legacy_delta == pytest.approx(-1.5, abs=TOL)
    assert modern_delta == pytest.approx(legacy_delta, abs=TOL)


def test_unit_record_fields_and_agc_flag(tmp_path):
    body = MINIMAL.replace(
        "  GEN.A                  100.0     50.0     200.0      60.0      1.00     T\n",
        "  GEN.A                  100.0     50.0     200.0      60.0      1.00     T\n"
        "  GEN.B                  300.0    240.0     340.0       3.0      0.50     F\n",
    )
    path = write_export(tmp_path, body)
    case = load_savecase(path)

    first, second = case.units
    assert (first.name, first.output_mw, first.min_mw, first.max_mw) == (
        "GEN.A",
        100.0,
        50.0,
        200.0,
    )
    assert (first.ramp_mw_per_min, first.participation, first.on_agc) == (60.0, 1.0, True)
    assert second.on_agc is False
    # The Fortran task prints a setpoint line per unit, in savecase order.
    assert list(legacy_fields("rtgenace", path))[2:] == ["GEN.A", "GEN.B"]


def test_unit_setpoints_match_the_legacy_task_on_a_crafted_case(tmp_path):
    path = write_export(tmp_path, MINIMAL)
    case = load_savecase(path)
    legacy = legacy_fields("rtgenace", path)

    modern = allocate_regulation(
        case.units, reporting_ace(case.balancing_state()), interval_s=4.0
    )

    assert modern["GEN.A"] == pytest.approx(float(legacy["GEN.A"]), abs=TOL)


def test_feeder_record_fields_match_the_load_shedding_task(tmp_path):
    body = MINIMAL.replace(
        "  FDR.A                    5.0          1            2\n",
        "  FDR.A                    5.0          1            2\n"
        "  FDR.CRITICAL             7.25         1            1\n"
        "  FDR.C                    3.5          3            3\n",
    )
    path = write_export(tmp_path, body)
    case = load_savecase(path)
    legacy = legacy_fields("loadshed", path)

    assert [(f.id, f.load_mw, f.shed_block, f.priority) for f in case.feeders] == [
        ("FDR.A", 5.0, 1, 2),
        ("FDR.CRITICAL", 7.25, 1, 1),
        ("FDR.C", 3.5, 3, 3),
    ]
    # Priority 1 feeders are manual-drop only; the Fortran task sums their load.
    manual = sum(f.load_mw for f in case.feeders if f.priority == 1)
    assert float(legacy["MANUAL_MW"]) == pytest.approx(manual, abs=TOL)


def test_feeder_blocks_shed_by_the_legacy_task_are_the_ones_we_parsed(tmp_path):
    body = MINIMAL.replace("59.900", "58.600").replace(
        "  FDR.A                    5.0          1            2\n",
        "  FDR.A                    5.0          1            2\n"
        "  FDR.B                    4.0          2            2\n",
    )
    path = write_export(tmp_path, body)
    case = load_savecase(path)
    legacy = legacy_fields("loadshed", path)

    shed = sum(f.load_mw for f in case.feeders if f.priority != 1 and f.shed_block <= 3)
    assert int(legacy["BLOCK"]) == 3
    assert float(legacy["SHED_MW"]) == pytest.approx(shed, abs=TOL)


def test_comment_and_blank_lines_are_ignored(tmp_path):
    noisy = MINIMAL.replace(
        "RECORD TIELINE\n",
        "*\n* a comment between records\n\n   \nRECORD TIELINE\n",
    )
    clean = write_export(tmp_path, MINIMAL, "clean.export")
    path = write_export(tmp_path, noisy, "noisy.export")

    assert legacy_fields("rtgenace", path) == legacy_fields("rtgenace", clean)
    assert load_savecase(path) == load_savecase(clean)


def test_unknown_record_types_are_skipped(tmp_path):
    body = MINIMAL.replace(
        "RECORD METERR\n",
        "RECORD SCADAMOM\n  POINT.A   1.0   2.0\nRECORD METERR\n",
    )
    path = write_export(tmp_path, body)

    assert legacy_fields("rtgenace", path)["ACE_MW"] == legacy_fields(
        "rtgenace", write_export(tmp_path, MINIMAL, "base.export")
    )["ACE_MW"]
    assert load_savecase(path) == load_savecase(write_export(tmp_path, MINIMAL, "base.export"))


def test_reading_stops_at_the_end_record(tmp_path):
    """The Fortran reader terminates on END; anything after it is not data."""
    body = MINIMAL + (
        "RECORD TIELINE\n"
        "  TIE.AFTER_END        9999.0        0.0        N\n"
        "RECORD UNIT\n"
        "  GEN.AFTER_END        500.0   0.0  900.0   90.0  1.00     T\n"
    )
    path = write_export(tmp_path, body)
    case = load_savecase(path)
    legacy = legacy_fields("rtgenace", path)

    assert [line.name for line in case.tie_lines] == ["TIE.A"]
    assert [unit.name for unit in case.units] == ["GEN.A"]
    assert "GEN.AFTER_END" not in legacy
    assert reporting_ace(case.balancing_state()) == pytest.approx(
        float(legacy["ACE_MW"]), abs=ACE_TOL
    )


def test_a_savecase_without_an_end_record_reads_to_eof(tmp_path):
    path = write_export(tmp_path, MINIMAL.replace("END\n", ""))

    assert len(load_savecase(path).units) == 1
    assert legacy_fields("rtgenace", path)["SAVECASE"] == "CHARACTERIZATION"


def test_a_malformed_numeric_field_is_rejected_by_both_readers(tmp_path):
    path = write_export(
        tmp_path, MINIMAL.replace("  TIE.A                  100.0", "  TIE.A                  ABC")
    )
    completed = run_legacy("rtgenace", path)

    assert completed.returncode != 0
    assert "savecase read failed, ierr= 2" in completed.stdout
    with pytest.raises(ValueError):
        load_savecase(path)


def test_a_truncated_record_line_is_rejected_by_both_readers(tmp_path):
    path = write_export(
        tmp_path,
        MINIMAL.replace(
            "  GEN.A                  100.0     50.0     200.0      60.0      1.00     T",
            "  GEN.A                  100.0     50.0",
        ),
    )
    completed = run_legacy("rtgenace", path)

    assert completed.returncode != 0
    assert "savecase read failed" in completed.stdout
    with pytest.raises(IndexError):
        load_savecase(path)


def test_a_missing_savecase_file_is_an_error_on_both_sides(tmp_path):
    missing = tmp_path / "nope.export"
    completed = run_legacy("rtgenace", missing)

    assert completed.returncode != 0
    assert "ierr= 1" in completed.stdout
    with pytest.raises(FileNotFoundError):
        load_savecase(missing)


def test_the_shipped_savecase_round_trips_through_both_readers():
    case = load_savecase(SAVECASE)
    legacy = legacy_fields("rtgenace", SAVECASE)

    assert case.name == legacy["SAVECASE"]
    assert len(case.tie_lines) == 3
    assert len(case.units) == 4
    assert len(case.feeders) == 4
    assert reporting_ace(case.balancing_state()) == pytest.approx(
        float(legacy["ACE_MW"]), abs=ACE_TOL
    )
