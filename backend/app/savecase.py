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
    case = Savecase()
    record = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
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
        if head == "END":
            break
        if head in {"CLONE", "TIMESTAMP"}:
            continue

        fields = line.split()
        if record == "FREQ":
            case.actual_frequency_hz = float(fields[1])
            case.scheduled_frequency_hz = float(fields[2])
            case.frequency_bias_mw_per_0_1hz = float(fields[3])
            case.frequency_quality = fields[4]
        elif record == "TIELINE":
            case.tie_lines.append(
                TieLine(name=fields[0], actual_mw=float(fields[1]), scheduled_mw=float(fields[2]))
            )
        elif record == "METERR":
            case.meter_error_mw = float(fields[1])
        elif record == "UNIT":
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
            case.feeders.append(
                FeederBlock(
                    id=fields[0],
                    load_mw=float(fields[1]),
                    shed_block=int(fields[2]),
                    priority=int(fields[3]),
                )
            )
    return case
