"""Port/legacy parity on savecase shapes outside the golden corpus.

Each case is written to a temporary export and, where gfortran is available, run
through the live legacy binary as well as the port.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rtgenace_corpus import GOLDEN, build_legacy_binary, case_path, run_binary

from app import rtgenace
from app.models import Unit
from app.savecase import Savecase, load_savecase

HEADER = """CLONE    RTNET.EMS
SAVECASE {name}
RECORD FREQ
  AREA.CEDARVALLEY   60.0000  60.0000  -412.0  N
RECORD TIELINE
  TIE.NORTH340       {actual}  {scheduled}  N
RECORD METERR
  AREA.CEDARVALLEY   0.00
RECORD UNIT
"""


def export(tmp_path: Path, name: str, actual: str, scheduled: str, units: list[str]) -> Path:
    path = tmp_path / f"{name.lower()}.export"
    text = HEADER.format(name=name, actual=actual, scheduled=scheduled)
    path.write_text(text + "".join(f"  {row}\n" for row in units) + "END\n", encoding="ascii")
    return path


def port_output(path: Path, capsys: pytest.CaptureFixture) -> dict[str, object]:
    exit_code = rtgenace.main([str(path)])
    return {"exit_code": exit_code, "stdout": capsys.readouterr().out.splitlines()}


@pytest.fixture(scope="module")
def legacy_binary() -> Path:
    binary = build_legacy_binary()
    if binary is None:
        pytest.skip("gfortran not installed: live legacy comparison unavailable")
    return binary


def test_duplicate_unit_names_keep_one_setpoint_per_row(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = export(
        tmp_path,
        "TWIN_NAMES",
        "360.000",
        "400.000",
        [
            "GEN.TWIN           100.00 20.00 200.00 30.00 0.500 T",
            "GEN.TWIN           150.00 20.00 160.00 60.00 0.500 T",
        ],
    )
    assert rtgenace.run(load_savecase(path)).setpoints == [("GEN.TWIN", 2.0), ("GEN.TWIN", 4.0)]
    assert port_output(path, capsys)["stdout"][2:] == [
        "SETPT    GEN.TWIN                  2.0000",
        "SETPT    GEN.TWIN                  4.0000",
    ]


def test_duplicate_unit_names_match_legacy(
    legacy_binary: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = export(
        tmp_path,
        "TWIN_NAMES",
        "360.000",
        "400.000",
        [
            "GEN.TWIN           100.00 20.00 200.00 30.00 0.500 T",
            "GEN.TWIN           150.00 20.00 160.00 60.00 0.500 T",
        ],
    )
    assert port_output(path, capsys) == run_binary(legacy_binary, str(path))


def test_ace_too_wide_for_f12_4_prints_asterisks() -> None:
    result = rtgenace.RtgenaceResult(savecase="WIDE", ace_mw=1.0e8, setpoints=[("G", -1.0e9)])
    assert rtgenace.format_report(result)[1:] == [
        "ACE_MW   ************",
        "SETPT    G                   ************",
    ]


def test_ace_too_wide_for_f12_4_matches_legacy(
    legacy_binary: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = export(
        tmp_path,
        "WIDE_ACE",
        "100000000.000",
        "0.000",
        ["GEN.PEAKER         100.00 20.00 200.00 30.00 1.000 T"],
    )
    assert port_output(path, capsys) == run_binary(legacy_binary, str(path))


def test_non_utf8_comment_is_accepted_like_legacy(tmp_path: Path) -> None:
    source = case_path("clamp_at_max")
    path = tmp_path / "latin1_comment.export"
    path.write_bytes(b"* operator note: caf\xe9 \xff\n" + source.read_bytes())
    assert rtgenace.run(load_savecase(path)) == rtgenace.run(load_savecase(source))


def test_non_utf8_comment_matches_legacy(legacy_binary: Path, tmp_path: Path) -> None:
    path = tmp_path / "latin1_comment.export"
    path.write_bytes(b"* operator note: caf\xe9 \xff\n" + case_path("clamp_at_max").read_bytes())
    assert run_binary(legacy_binary, str(path)) == GOLDEN["clamp_at_max"]


def test_knife_edge_legacy_ace_printed_as_deadband_value_is_still_consistent() -> None:
    # True ACE just above 5 MW prints as 5.0000; the legacy unit still regulated.
    unit = Unit(
        name="G",
        output_mw=100.0,
        min_mw=0.0,
        max_mw=200.0,
        ramp_mw_per_min=600.0,
        participation=1.0,
    )
    case = Savecase(name="EDGE", units=[unit])
    assert rtgenace.legacy_setpoints_consistent(case, 5.0, [-5.0])
    assert rtgenace.legacy_setpoints_consistent(case, 5.0, [0.0])
    assert not rtgenace.legacy_setpoints_consistent(case, 5.0, [-4.0])
