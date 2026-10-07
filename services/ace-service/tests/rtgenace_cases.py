"""Characterization cases for the legacy RTGENACE task and its savecase reader.

Every LEGACY value below was observed by running the unmodified gfortran build of
legacy/habitat/src/ace_calc.f90 and is pinned. ``service`` says what the ACE service must do
with the same input: "same" (match the Fortran) or "refuse" (spec §6 deviation, 422).
Requirement IDs refer to docs/specs/RTGENACE.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from legacy_harness import REFERENCE_SAVECASE


@dataclass(frozen=True)
class Legacy:
    rc: int
    name: str | None = None
    ace: float | None = None
    setpoints: list[tuple[str, float]] = field(default_factory=list)
    ierr: int | None = None


nan, inf = math.nan, math.inf


@dataclass(frozen=True)
class Case:
    id: str
    requirements: str
    title: str
    text: str
    service: str = "same"


def export(
    name: str,
    freq: str | None = "AREA.NTX  60.000  60.000  -500.0  N",
    ties: tuple[str, ...] = (),
    meterr: str | None = None,
    units: tuple[str, ...] = (),
) -> str:
    lines = ["CLONE    RTNET.EMS", f"SAVECASE {name}"]
    if freq is not None:
        lines += ["RECORD FREQ", f"  {freq}"]
    if ties:
        lines += ["RECORD TIELINE", *(f"  {t}" for t in ties)]
    if meterr is not None:
        lines += ["RECORD METERR", f"  AREA.NTX  {meterr}"]
    if units:
        lines += ["RECORD UNIT", *(f"  {u}" for u in units)]
    return "\n".join([*lines, "END"]) + "\n"


def tie(net_mw: float) -> str:
    return f"TIE.A  {100.0 + net_mw:.4f}  100.0  N"


G1 = "GEN.G1  100.0  50.0  200.0  6.0  0.50  T"

RTGENACE_CASES = [
    Case("C01", "ACE-1 AL-5 AL-6", "Reference savecase RTNET_EMS_0742", REFERENCE_SAVECASE.read_text()),
    Case(
        "C02",
        "AL-2",
        "ACE exactly +5.0 MW is inside the deadband",
        export("C02", ties=(tie(5.0),), units=(G1,)),
    ),
    Case("C03", "AL-2 AL-6", "ACE +5.25 MW leaves the deadband", export("C03", ties=(tie(5.25),), units=(G1,))),
    Case("C04", "AL-2", "ACE -4.99 MW is inside the deadband", export("C04", ties=(tie(-4.99),), units=(G1,))),
    Case(
        "C05",
        "AL-5",
        "Pro-rata split 0.75/0.25 without ramp clipping",
        export(
            "C05",
            ties=(tie(10.0),),
            units=("GEN.A  100.0  50.0  200.0  600.0  0.75  T", "GEN.B  100.0  50.0  200.0  600.0  0.25  T"),
        ),
    ),
    Case(
        "C06",
        "AL-6",
        "Ramp clip in both directions",
        export("C06", ties=(tie(-300.0),), units=("GEN.UP  100.0  50.0  200.0  9.0  1.00  T",)),
    ),
    Case(
        "C07",
        "AL-7",
        "Target clipped to max",
        export("C07", ties=(tie(-200.0),), units=("GEN.HI  199.9  50.0  200.0  6.0  0.50  T",)),
    ),
    Case(
        "C08",
        "AL-7",
        "Target clipped to min",
        export("C08", ties=(tie(200.0),), units=("GEN.LO  50.1  50.0  200.0  6.0  0.50  T",)),
    ),
    Case(
        "C09",
        "AL-1 AL-3",
        "Unit off AGC gets 0 and is excluded from total participation",
        export(
            "C09",
            ties=(tie(15.0),),
            units=(
                "GEN.ON  100.0  50.0  200.0  600.0  0.50  T",
                "GEN.OFF  100.0  50.0  200.0  600.0  0.50  F",
            ),
        ),
    ),
    Case(
        "C10",
        "AL-3",
        "Zero and negative participation do not participate",
        export(
            "C10",
            ties=(tie(15.0),),
            units=(
                "GEN.POS  100.0  50.0  200.0  600.0  0.30  T",
                "GEN.ZERO  100.0  50.0  200.0  600.0  0.00  T",
                "GEN.NEG  100.0  50.0  200.0  600.0  -0.40  T",
            ),
        ),
    ),
    Case(
        "C11",
        "AL-4",
        "No participating units: all deltas 0",
        export("C11", ties=(tie(50.0),), units=("GEN.F  100.0  50.0  200.0  6.0  0.50  F",)),
    ),
    Case(
        "C12",
        "SC-12 ACE-3",
        "No FREQ, no TIELINE: ACE is minus meter error",
        export("C12", freq=None, meterr="-12.5", units=(G1,)),
    ),
    Case("C13", "AL-1", "No units: ACE only", export("C13", ties=(tie(-40.0),))),
    Case(
        "C14",
        "ACE-1 ACE-2",
        "Tie lines summed, meter error subtracted",
        export(
            "C14",
            ties=("TIE.X  250.0  240.0  N", "TIE.Y  -80.0  -95.5  N", "TIE.Z  12.0  0.0  N"),
            meterr="3.5",
            units=(G1,),
        ),
    ),
    Case(
        "C15",
        "ACE-1",
        "Over-frequency with negative bias raises ACE",
        export("C15", freq="AREA.NTX  60.020  60.000  -500.0  N", ties=(tie(0.0),), units=(G1,)),
    ),
    Case(
        "C16",
        "AL-7 F-1",
        "Unit below min snapped up 20 MW against ACE",
        export("C16", ties=(tie(200.0),), units=("GEN.LOW  30.0  50.0  200.0  6.0  0.50  T",)),
    ),
    Case(
        "C17",
        "ACE-2 F-2",
        "Suspect frequency quality still drives ACE",
        export("C17", freq="AREA.NTX  59.900  60.000  -412.0  S", ties=(tie(0.0),), units=(G1,)),
    ),
    Case(
        "C18",
        "SC-10",
        "AGC flag: TRUE is on, lower-case t is off",
        export(
            "C18",
            ties=(tie(15.0),),
            units=(
                "GEN.TRUE  100.0  50.0  200.0  600.0  0.50  TRUE",
                "GEN.LOWER  100.0  50.0  200.0  600.0  0.50  t",
            ),
        ),
    ),
    Case(
        "C19",
        "SC-7",
        "Quoted id with a blank and comma separators",
        export("C19", ties=(tie(15.0),), units=("'GEN ALPHA',100.0,50.0,200.0,600.0,0.50,T",)),
    ),
    Case(
        "C20",
        "SC-8",
        "Unit id truncated to 20 characters",
        export(
            "C20",
            ties=(tie(15.0),),
            units=("GEN.ABCDEFGHIJKLMNOPQRSTUVWXYZ  100.0  50.0  200.0  600.0  0.50  T",),
        ),
    ),
    Case(
        "C21",
        "SC-4 SC-7 F-4",
        "Extra fields ignored; unknown and lower-case RECORD types skipped",
        "SAVECASE C21\nRECORD TIELINE\n  TIE.A  120.0  100.0  N  EXTRA  999\n"
        "RECORD BREAKER\n  CB.1  garbage\nrecord UNIT\nRECORD unit\n  GEN.HIDDEN  100.0  50.0  200.0  6.0  0.50  T\n"
        "RECORD UNIT\n  GEN.SEEN  100.0  50.0  200.0  6.0  0.50  T  TRAILING\n",
    ),
    Case(
        "C22",
        "SC-5 F-3",
        "ENDOFDATA in column 1 ends the read; later units are dropped",
        "SAVECASE C22\nRECORD TIELINE\n  TIE.A  120.0  100.0  N\nRECORD UNIT\n"
        "  GEN.FIRST  100.0  50.0  200.0  6.0  0.50  T\nENDOFDATA\n  GEN.LOST  100.0  50.0  200.0  6.0  0.50  T\n",
    ),
    Case(
        "C23",
        "SC-11",
        "Repeated FREQ and METERR: last wins",
        "SAVECASE C23\nRECORD FREQ\n  AREA.A  59.000  60.000  -500.0  N\n  AREA.B  60.010  60.000  -500.0  N\n"
        "RECORD METERR\n  AREA.A  50.0\n  AREA.B  1.0\nRECORD UNIT\n  " + G1 + "\n",
    ),
    Case(
        "D01",
        "D-1",
        "NaN frequency propagates into ACE and setpoints",
        export("D01", freq="AREA.NTX  NaN  60.000  -500.0  N", ties=(tie(0.0),), units=(G1,)),
        service="refuse",
    ),
    Case(
        "D02",
        "D-1",
        "Infinite tie flow gives infinite ACE and a full ramp move",
        export("D02", ties=("TIE.A  Infinity  100.0  N",), units=(G1,)),
        service="refuse",
    ),
    Case(
        "D03",
        "D-2 SC-8",
        "Duplicate unit id after truncation gets two setpoints",
        export(
            "D03",
            ties=(tie(15.0),),
            units=(
                "GEN.DUPLICATE_UNIT_A  100.0  50.0  200.0  600.0  0.50  T",
                "GEN.DUPLICATE_UNIT_AB  100.0  50.0  200.0  600.0  0.50  T",
            ),
        ),
        service="refuse",
    ),
    Case(
        "D04",
        "D-3",
        "min > max collapses target to max",
        export("D04", ties=(tie(200.0),), units=("GEN.INV  100.0  150.0  120.0  6.0  0.50  T",)),
        service="refuse",
    ),
    Case(
        "D05",
        "D-4",
        "Negative ramp inverts the clip: unit moves with ACE",
        export("D05", ties=(tie(200.0),), units=("GEN.NEG  100.0  50.0  200.0  -6.0  0.50  T",)),
        service="refuse",
    ),
    Case(
        "D06",
        "D-5",
        "Repeat count 2*300 sets actual and scheduled",
        export("D06", ties=("TIE.A  2*300  N",), units=(G1,)),
        service="refuse",
    ),
]

_padding = " " * 250
HAB_SAVECASE_CASES = [
    Case("H02", "SC-14", "Malformed number", export("H02", ties=("TIE.A  12O.0  100.0  N",)), service="refuse"),
    Case("H03", "SC-14", "Missing field", export("H03", ties=("TIE.A  120.0  100.0",)), service="refuse"),
    Case(
        "H04",
        "SC-2",
        "Indented * is data, not a comment",
        "SAVECASE H04\nRECORD TIELINE\n  * note\n",
        service="refuse",
    ),
    Case("H05", "SC-5", "Indented END is data", "SAVECASE H05\nRECORD UNIT\n  END\n", service="refuse"),
    Case(
        "H06",
        "SC-13",
        "65 units exceed MAXUNT",
        export("H06", units=tuple(f"GEN.U{i}  100.0  50.0  200.0  6.0  0.10  T" for i in range(65))),
        service="refuse",
    ),
    Case(
        "H07",
        "SC-13",
        "33 tie lines exceed MAXTIE",
        export("H07", ties=tuple(f"TIE.T{i}  1.0  1.0  N" for i in range(33))),
        service="refuse",
    ),
    Case("H08", "SC-15", "Empty export", ""),
    Case(
        "H10",
        "SC-7",
        "D exponent accepted",
        export("H10", ties=("TIE.A  1.2D2  1.0E2  N",), units=(G1,)),
    ),
    Case(
        "H11",
        "SC-3",
        "Indented SAVECASE is ignored",
        "  SAVECASE IGNORED\nRECORD TIELINE\n  TIE.A  110.0  100.0  N\n",
    ),
    Case(
        "H12",
        "SC-1",
        "Fields beyond column 256 are lost",
        export("H12", ties=(f"TIE.A  120.0  100.0{_padding}N",)),
        service="refuse",
    ),
    Case(
        "H13",
        "SC-3",
        "Case name truncated to 32 characters",
        "SAVECASE RTNET_EMS_0742_WITH_A_VERY_LONG_SUFFIX\nRECORD TIELINE\n  TIE.A  110.0  100.0  N\n",
    ),
]

# Observed on the unmodified legacy build (gfortran, REAL*4).
LEGACY = {
    "C01": Legacy(
        rc=0,
        name="RTNET_EMS_0742",
        ace=-116.3462,
        setpoints=[
            ("GEN.HARBOR1", 0.4),
            ("GEN.HARBOR2", 0.4),
            ("GEN.MESQUITE_CT", 1.2),
            ("GEN.CEDAR_STM", 0.0),
        ],
    ),
    "C02": Legacy(rc=0, name="C02", ace=5.0, setpoints=[("GEN.G1", 0.0)]),
    "C03": Legacy(rc=0, name="C03", ace=5.25, setpoints=[("GEN.G1", -0.4)]),
    "C04": Legacy(rc=0, name="C04", ace=-4.99, setpoints=[("GEN.G1", 0.0)]),
    "C05": Legacy(rc=0, name="C05", ace=10.0, setpoints=[("GEN.A", -7.5), ("GEN.B", -2.5)]),
    "C06": Legacy(rc=0, name="C06", ace=-300.0, setpoints=[("GEN.UP", 0.6)]),
    "C07": Legacy(rc=0, name="C07", ace=-200.0, setpoints=[("GEN.HI", 0.1)]),
    "C08": Legacy(rc=0, name="C08", ace=200.0, setpoints=[("GEN.LO", -0.1)]),
    "C09": Legacy(rc=0, name="C09", ace=15.0, setpoints=[("GEN.ON", -15.0), ("GEN.OFF", 0.0)]),
    "C10": Legacy(rc=0, name="C10", ace=15.0, setpoints=[("GEN.POS", -15.0), ("GEN.ZERO", 0.0), ("GEN.NEG", 0.0)]),
    "C11": Legacy(rc=0, name="C11", ace=50.0, setpoints=[("GEN.F", 0.0)]),
    "C12": Legacy(rc=0, name="C12", ace=12.5, setpoints=[("GEN.G1", -0.4)]),
    "C13": Legacy(rc=0, name="C13", ace=-40.0),
    "C14": Legacy(rc=0, name="C14", ace=34.0, setpoints=[("GEN.G1", -0.4)]),
    "C15": Legacy(rc=0, name="C15", ace=100.0023, setpoints=[("GEN.G1", -0.4)]),
    "C16": Legacy(rc=0, name="C16", ace=200.0, setpoints=[("GEN.LOW", 20.0)]),
    "C17": Legacy(rc=0, name="C17", ace=-411.9937, setpoints=[("GEN.G1", 0.4)]),
    "C18": Legacy(rc=0, name="C18", ace=15.0, setpoints=[("GEN.TRUE", -15.0), ("GEN.LOWER", 0.0)]),
    "C19": Legacy(rc=0, name="C19", ace=15.0, setpoints=[("GEN ALPHA", -15.0)]),
    "C20": Legacy(rc=0, name="C20", ace=15.0, setpoints=[("GEN.ABCDEFGHIJKLMNOP", -15.0)]),
    "C21": Legacy(rc=0, name="C21", ace=20.0, setpoints=[("GEN.SEEN", -0.4)]),
    "C22": Legacy(rc=0, name="C22", ace=20.0, setpoints=[("GEN.FIRST", -0.4)]),
    "C23": Legacy(rc=0, name="C23", ace=48.9916, setpoints=[("GEN.G1", -0.4)]),
    "D01": Legacy(rc=0, name="D01", ace=nan, setpoints=[("GEN.G1", nan)]),
    "D02": Legacy(rc=0, name="D02", ace=inf, setpoints=[("GEN.G1", -0.4)]),
    "D03": Legacy(
        rc=0, name="D03", ace=15.0, setpoints=[("GEN.DUPLICATE_UNIT_A", -7.5), ("GEN.DUPLICATE_UNIT_A", -7.5)]
    ),
    "D04": Legacy(rc=0, name="D04", ace=200.0, setpoints=[("GEN.INV", 20.0)]),
    "D05": Legacy(rc=0, name="D05", ace=200.0, setpoints=[("GEN.NEG", 0.4)]),
    "D06": Legacy(rc=0, name="D06", ace=0.0, setpoints=[("GEN.G1", 0.0)]),
    "H02": Legacy(rc=3, ierr=2),
    "H03": Legacy(rc=3, ierr=2),
    "H04": Legacy(rc=3, ierr=2),
    "H05": Legacy(rc=3, ierr=2),
    "H06": Legacy(rc=3, ierr=2),
    "H07": Legacy(rc=3, ierr=2),
    "H08": Legacy(rc=0, name="", ace=0.0),
    "H10": Legacy(rc=0, name="H10", ace=20.0, setpoints=[("GEN.G1", -0.4)]),
    "H11": Legacy(rc=0, name="", ace=10.0),
    "H12": Legacy(rc=3, ierr=2),
    "H13": Legacy(rc=0, name="RTNET_EMS_0742_WITH_A_VERY_LONG_", ace=10.0),
}
