"""Characterization tests for the HDB savecase reader.

``app/savecase.py`` replaces the Fortran ``HAB_SAVECASE`` module
(``legacy/habitat/src/hab_savecase.f90``). These tests pin the record types the
legacy reader accepts, the way it terminates a file, and what it does with
malformed input, so the ported reader can be compared against it rather than
against assumptions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.savecase import Savecase, load_savecase

REPO = Path(__file__).resolve().parents[2]
SAVECASE = REPO / "legacy" / "habitat" / "savecases" / "rtnet_ems_0742.export"


def write(tmp_path: Path, body: str, name: str = "case.export") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.characterization
def test_shipped_savecase_header_and_frequency_record():
    case = load_savecase(SAVECASE)

    assert case.name == "RTNET_EMS_0742"
    assert case.actual_frequency_hz == pytest.approx(59.968)
    assert case.scheduled_frequency_hz == pytest.approx(60.0)
    assert case.frequency_bias_mw_per_0_1hz == pytest.approx(-412.0)
    assert case.frequency_quality == "N"
    assert case.meter_error_mw == pytest.approx(2.5)


@pytest.mark.characterization
def test_shipped_savecase_tieline_records():
    case = load_savecase(SAVECASE)

    assert [(tie.name, tie.actual_mw, tie.scheduled_mw) for tie in case.tie_lines] == [
        ("TIE.NORTH340", 418.2, 400.0),
        ("TIE.EAST115", -132.6, -140.0),
        ("TIE.SOUTH230", 97.4, 105.0),
    ]


@pytest.mark.characterization
def test_shipped_savecase_unit_records():
    case = load_savecase(SAVECASE)
    harbor1, harbor2, mesquite, cedar = case.units

    assert (harbor1.name, harbor1.output_mw, harbor1.participation, harbor1.on_agc) == (
        "GEN.HARBOR1",
        212.0,
        0.45,
        True,
    )
    assert (harbor2.min_mw, harbor2.max_mw, harbor2.ramp_mw_per_min) == (120.0, 260.0, 6.0)
    assert (mesquite.name, mesquite.ramp_mw_per_min) == ("GEN.MESQUITE_CT", 18.0)
    assert (cedar.name, cedar.on_agc, cedar.participation) == ("GEN.CEDAR_STM", False, 0.0)


@pytest.mark.characterization
def test_shipped_savecase_feeder_records():
    case = load_savecase(SAVECASE)

    assert [(f.id, f.load_mw, f.shed_block, f.priority) for f in case.feeders] == [
        ("FDR.1201", 6.4, 1, 3),
        ("FDR.1405", 8.1, 1, 2),
        ("FDR.2210", 11.7, 2, 3),
        ("FDR.2255", 4.9, 3, 1),
    ]


@pytest.mark.characterization
def test_balancing_state_carries_the_ace_inputs():
    state = load_savecase(SAVECASE).balancing_state()

    assert len(state.tie_lines) == 3
    assert state.actual_frequency_hz == pytest.approx(59.968)
    assert state.frequency_bias_mw_per_0_1hz == pytest.approx(-412.0)
    assert state.meter_error_mw == pytest.approx(2.5)


@pytest.mark.characterization
def test_comments_blank_lines_and_clone_header_are_ignored(tmp_path: Path):
    path = write(
        tmp_path,
        """* a comment line

CLONE    RTNET.EMS
SAVECASE RTNET_EMS_MINIMAL
TIMESTAMP 2026-02-11T07:42:00Z
RECORD FREQ
* ID_FREQ VALUE_FREQ SCHED_FREQ BIAS_FREQ QUAL_FREQ
  AREA.CEDARVALLEY 59.980 60.000 -412.0 S
END
""",
    )

    case = load_savecase(path)

    assert case.name == "RTNET_EMS_MINIMAL"
    assert case.actual_frequency_hz == pytest.approx(59.98)
    assert case.frequency_quality == "S"


@pytest.mark.characterization
def test_unknown_record_types_are_skipped(tmp_path: Path):
    """The legacy reader's SELECT CASE default is CONTINUE, not an error."""
    path = write(
        tmp_path,
        """SAVECASE RTNET_EMS_UNKNOWN
RECORD WIDGET
  WDG.1 1.0 2.0 3.0
RECORD FREQ
  AREA.CEDARVALLEY 59.990 60.000 -412.0 N
END
""",
    )

    case = load_savecase(path)

    assert case.actual_frequency_hz == pytest.approx(59.99)
    assert case.units == []
    assert case.tie_lines == []


@pytest.mark.characterization
def test_reading_stops_at_the_end_marker(tmp_path: Path):
    """``HDB_READ_EXPORT`` jumps to the close on END; trailing records are not read."""
    path = write(
        tmp_path,
        """SAVECASE RTNET_EMS_TRAILER
RECORD UNIT
  GEN.HARBOR1 212.0 120.0 260.0 6.0 0.45 T
END
  GEN.TRAILER 100.0 50.0 200.0 6.0 0.50 T
""",
    )

    case = load_savecase(path)

    assert [unit.name for unit in case.units] == ["GEN.HARBOR1"]


@pytest.mark.characterization
def test_agc_flag_is_an_exact_uppercase_t(tmp_path: Path):
    path = write(
        tmp_path,
        """SAVECASE RTNET_EMS_FLAGS
RECORD UNIT
  GEN.ON 100.0 50.0 200.0 6.0 0.50 T
  GEN.OFF 100.0 50.0 200.0 6.0 0.50 F
  GEN.LOWER 100.0 50.0 200.0 6.0 0.50 t
END
""",
    )

    case = load_savecase(path)

    assert [unit.on_agc for unit in case.units] == [True, False, False]


@pytest.mark.characterization
def test_last_frequency_and_meter_error_record_wins(tmp_path: Path):
    path = write(
        tmp_path,
        """SAVECASE RTNET_EMS_REPEAT
RECORD FREQ
  AREA.CEDARVALLEY 59.900 60.000 -400.0 N
  AREA.CEDARVALLEY 59.950 60.000 -412.0 N
RECORD METERR
  AREA.CEDARVALLEY 1.0
  AREA.CEDARVALLEY 2.5
END
""",
    )

    case = load_savecase(path)

    assert case.actual_frequency_hz == pytest.approx(59.95)
    assert case.meter_error_mw == pytest.approx(2.5)


@pytest.mark.characterization
def test_records_before_any_record_header_are_ignored(tmp_path: Path):
    path = write(
        tmp_path,
        """SAVECASE RTNET_EMS_ORPHAN
  GEN.ORPHAN 100.0 50.0 200.0 6.0 0.50 T
RECORD UNIT
  GEN.HARBOR1 212.0 120.0 260.0 6.0 0.45 T
END
""",
    )

    case = load_savecase(path)

    assert [unit.name for unit in case.units] == ["GEN.HARBOR1"]


@pytest.mark.characterization
def test_truncated_record_is_rejected(tmp_path: Path):
    """The legacy reader returns IERR=2 and RTGENACE stops; the port raises."""
    path = write(
        tmp_path,
        """SAVECASE RTNET_EMS_SHORT
RECORD UNIT
  GEN.HARBOR1 212.0 120.0 260.0 6.0
END
""",
    )

    with pytest.raises(IndexError):
        load_savecase(path)


@pytest.mark.characterization
def test_non_numeric_field_is_rejected(tmp_path: Path):
    path = write(
        tmp_path,
        """SAVECASE RTNET_EMS_BAD
RECORD TIELINE
  TIE.NORTH340 four_hundred 400.0 N
END
""",
    )

    with pytest.raises(ValueError):
        load_savecase(path)


@pytest.mark.characterization
def test_missing_file_is_rejected(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_savecase(tmp_path / "does_not_exist.export")


@pytest.mark.characterization
def test_empty_savecase_defaults_match_the_fortran_record_defaults():
    case = Savecase()

    assert case.actual_frequency_hz == 60.0
    assert case.scheduled_frequency_hz == 60.0
    assert case.frequency_bias_mw_per_0_1hz == 0.0
    assert case.frequency_quality == "N"
    assert case.meter_error_mw == 0.0
    assert case.balancing_state().tie_lines == []
