"""Characterization of the legacy RTGENACE task (legacy/habitat/src/ace_calc.f90).

The goldens in legacy/habitat/characterization/rtgenace/golden.json are what the
gfortran-built binary prints for every savecase in the corpus. These tests pin that
behaviour from both sides:

* the legacy binary still produces every golden byte for byte, and
* the ported service (app.rtgenace) reproduces every golden: the same accept/refuse
  verdict, the same unit roster in the same order, and Reporting ACE and every
  regulation setpoint within the single-precision error bound of the legacy value.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rtgenace_corpus import (
    ACCEPTED,
    CASES,
    GOLDEN,
    LEGACY,
    REFUSED,
    build_legacy_binary,
    case_path,
    parse_report,
    run_binary,
)

from app import rtgenace
from app.savecase import load_savecase

PRODUCTION_SAVECASE = LEGACY / "savecases" / "rtnet_ems_0742.export"

pytestmark = pytest.mark.characterization


@pytest.fixture(scope="module")
def legacy_binary() -> Path:
    binary = build_legacy_binary()
    if binary is None:
        pytest.skip("gfortran not installed: goldens stay pinned, live binary not rebuilt")
    return binary


@pytest.mark.parametrize("case", CASES)
def test_legacy_binary_reproduces_golden(legacy_binary: Path, case: str) -> None:
    assert run_binary(legacy_binary, str(case_path(case))) == GOLDEN[case]


def test_legacy_binary_without_argument_prints_usage_and_stops_2(legacy_binary: Path) -> None:
    assert run_binary(legacy_binary) == {
        "exit_code": 2,
        "stdout": ["RTGENACE: usage: rtgenace <savecase-export>"],
    }


def test_legacy_binary_missing_savecase_reports_ierr_1_and_stops_3(
    legacy_binary: Path, tmp_path: Path
) -> None:
    assert run_binary(legacy_binary, str(tmp_path / "missing.export")) == {
        "exit_code": 3,
        "stdout": ["RTGENACE: savecase read failed, ierr= 1"],
    }


@pytest.mark.parametrize("case", REFUSED)
def test_port_refuses_what_legacy_refuses(case: str, capsys: pytest.CaptureFixture) -> None:
    exit_code = rtgenace.main([str(case_path(case))])
    assert {"exit_code": exit_code, "stdout": capsys.readouterr().out.splitlines()} == GOLDEN[case]


@pytest.mark.parametrize("case", ACCEPTED)
def test_port_reproduces_legacy_ace_and_setpoints(case: str) -> None:
    legacy = parse_report(GOLDEN[case]["stdout"])
    savecase = load_savecase(case_path(case))
    modern = rtgenace.run(savecase)

    assert modern.savecase == legacy.savecase
    assert [name for name, _ in modern.setpoints] == [name for name, _ in legacy.setpoints]
    assert abs(modern.ace_mw - legacy.ace_mw) <= rtgenace.ace_parity_bound(savecase)

    if rtgenace.deadband_indeterminate(savecase, modern.ace_mw):
        # Single precision alone can put ACE on either side of the deadband here, so
        # the deadband decision is checked from the legacy ACE rather than our own.
        assert rtgenace.legacy_setpoints_consistent(
            savecase, legacy.ace_mw, [mw for _, mw in legacy.setpoints]
        )
        return

    for index, ((_, ours), (_, theirs)) in enumerate(
        zip(modern.setpoints, legacy.setpoints, strict=True)
    ):
        assert abs(ours - theirs) <= rtgenace.setpoint_parity_bound(savecase, index, modern.ace_mw)


def test_port_cli_matches_legacy_on_usage_and_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert rtgenace.main([]) == 2
    assert capsys.readouterr().out == "RTGENACE: usage: rtgenace <savecase-export>\n"
    assert rtgenace.main([str(tmp_path / "missing.export")]) == 3
    assert capsys.readouterr().out == "RTGENACE: savecase read failed, ierr= 1\n"


def test_port_prints_the_legacy_report_layout_for_the_production_savecase(
    capsys: pytest.CaptureFixture,
) -> None:
    assert rtgenace.main([str(PRODUCTION_SAVECASE)]) == 0
    modern = capsys.readouterr().out.splitlines()
    legacy = GOLDEN["production_rtnet_ems_0742"]["stdout"]
    assert [line[:9] for line in modern] == [line[:9] for line in legacy]
    assert [line[9:29] for line in modern[2:]] == [line[9:29] for line in legacy[2:]]
