"""Reader for legacy HDB savecase exports.

The legacy EMS keeps its real-time data in a memory-resident HDB database; the
nightly ``hdbexport`` job writes an ASCII snapshot of the RTNET.EMS clone.
Records use the platform's ``<FIELD>_<RECORD>`` naming convention, so the
export is the bridge between the legacy Fortran tasks and the ported services:
both sides can be replayed against the same savecase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import BalancingState, TieLine, Unit

# Record-table capacities of the legacy reader (MAXTIE, MAXUNT, MAXFDR in
# hab_savecase.f90). An export that overflows one is refused, not truncated.
MAX_TIE_LINES = 32
MAX_UNITS = 64
MAX_FEEDERS = 256

IERR_OPEN = 1
IERR_RECORD = 2


class SavecaseError(ValueError):
    """The export cannot be read; ``ierr`` matches HDB_READ_EXPORT's IERR."""

    def __init__(self, ierr: int, message: str) -> None:
        super().__init__(message)
        self.ierr = ierr


@dataclass
class FeederBlock:
    """A feeder as carried by the legacy FEEDER record."""

    id: str
    load_mw: float
    shed_block: int
    priority: int


@dataclass
class Savecase:
    name: str = ""
    actual_frequency_hz: float = 60.0
    scheduled_frequency_hz: float = 60.0
    frequency_bias_mw_per_0_1hz: float = 0.0
    frequency_quality: str = "N"
    meter_error_mw: float = 0.0
    tie_lines: list[TieLine] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    feeders: list[FeederBlock] = field(default_factory=list)

    def balancing_state(self) -> BalancingState:
        return BalancingState(
            tie_lines=self.tie_lines,
            actual_frequency_hz=self.actual_frequency_hz,
            scheduled_frequency_hz=self.scheduled_frequency_hz,
            frequency_bias_mw_per_0_1hz=self.frequency_bias_mw_per_0_1hz,
            meter_error_mw=self.meter_error_mw,
        )


def load_savecase(path: Path) -> Savecase:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SavecaseError(IERR_OPEN, f"cannot open savecase export {path}: {exc}") from exc

    case = Savecase()
    record = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.startswith("END"):
            break
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        head, _, rest = line.partition(" ")
        if head == "RECORD":
            record = rest.strip()
            continue
        if head == "SAVECASE":
            case.name = rest.strip()
            continue
        if head in {"CLONE", "TIMESTAMP"}:
            continue
        try:
            _read_record(case, record, line.split())
        except (IndexError, ValueError) as exc:
            raise SavecaseError(
                IERR_RECORD, f"{path.name}:{number}: unreadable {record} record: {exc}"
            ) from exc
    return case


def _read_record(case: Savecase, record: str, fields: list[str]) -> None:
    if record == "FREQ":
        case.actual_frequency_hz = float(fields[1])
        case.scheduled_frequency_hz = float(fields[2])
        case.frequency_bias_mw_per_0_1hz = float(fields[3])
        case.frequency_quality = fields[4]
    elif record == "TIELINE":
        _check_capacity(case.tie_lines, MAX_TIE_LINES, record)
        case.tie_lines.append(
            TieLine(name=fields[0], actual_mw=float(fields[1]), scheduled_mw=float(fields[2]))
        )
        fields[3]  # noqa: B018 - quality flag is mandatory, as in the legacy reader
    elif record == "METERR":
        case.meter_error_mw = float(fields[1])
    elif record == "UNIT":
        _check_capacity(case.units, MAX_UNITS, record)
        case.units.append(
            Unit(
                name=fields[0],
                output_mw=float(fields[1]),
                min_mw=float(fields[2]),
                max_mw=float(fields[3]),
                ramp_mw_per_min=float(fields[4]),
                participation=float(fields[5]),
                on_agc=fields[6] == "T",
            )
        )
    elif record == "FEEDER":
        _check_capacity(case.feeders, MAX_FEEDERS, record)
        case.feeders.append(
            FeederBlock(
                id=fields[0],
                load_mw=float(fields[1]),
                shed_block=int(fields[2]),
                priority=int(fields[3]),
            )
        )


def _check_capacity(table: list, capacity: int, record: str) -> None:
    if len(table) >= capacity:
        raise ValueError(f"more than {capacity} {record} records")
