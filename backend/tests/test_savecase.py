"""HDB savecase export reader (behaviour pinned against the legacy reader)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.savecase import MAX_FEEDERS, SavecaseError, load_savecase

HEADER = "CLONE    RTNET.EMS\nSAVECASE UNIT_TEST\nTIMESTAMP 2026-10-07T07:42:00\n"


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "case.export"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_reads_every_record_kind_without_end_marker(tmp_path: Path) -> None:
    case = load_savecase(
        write(
            tmp_path,
            "RECORD FREQ\n  AREA.X  59.990  60.000  -412.0  N\n"
            "RECORD TIELINE\n  TIE.A  101.5  100.0  N\n"
            "RECORD METERR\n  AREA.X  1.25\n"
            "RECORD UNIT\n  GEN.A  150.0  50.0  250.0  12.0  0.5  F\n"
            "RECORD FEEDER\n  FDR-1201  6.2  3  2\n",
        )
    )

    assert case.name == "UNIT_TEST"
    assert (case.actual_frequency_hz, case.frequency_bias_mw_per_0_1hz) == (59.99, -412.0)
    assert case.tie_lines[0].actual_mw == 101.5
    assert case.meter_error_mw == 1.25
    assert case.units[0].on_agc is False
    assert (case.feeders[0].id, case.feeders[0].shed_block, case.feeders[0].priority) == (
        "FDR-1201",
        3,
        2,
    )
    state = case.balancing_state()
    assert state.scheduled_frequency_hz == 60.0 and len(state.tie_lines) == 1


def test_feeder_table_overflow_is_refused(tmp_path: Path) -> None:
    rows = "".join(f"  FDR-{n:04d}  1.0  1  1\n" for n in range(MAX_FEEDERS + 1))
    with pytest.raises(SavecaseError) as refused:
        load_savecase(write(tmp_path, "RECORD FEEDER\n" + rows))
    assert refused.value.ierr == 2
    assert f"more than {MAX_FEEDERS} FEEDER records" in str(refused.value)


def test_feeder_table_at_capacity_is_accepted(tmp_path: Path) -> None:
    rows = "".join(f"  FDR-{n:04d}  1.0  1  1\n" for n in range(MAX_FEEDERS))
    assert len(load_savecase(write(tmp_path, "RECORD FEEDER\n" + rows)).feeders) == MAX_FEEDERS


def test_unreadable_file_reports_ierr_1(tmp_path: Path) -> None:
    with pytest.raises(SavecaseError) as refused:
        load_savecase(tmp_path / "absent.export")
    assert refused.value.ierr == 1


def test_tieline_without_quality_flag_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SavecaseError, match="case.export:5: unreadable TIELINE record"):
        load_savecase(write(tmp_path, "RECORD TIELINE\n  TIE.A  101.5  100.0\n"))
