"""Reader for hdbexport ASCII savecases, with the semantics of the legacy HDB_READ_EXPORT.

Requirement IDs (SC-n, D-n) refer to docs/specs/RTGENACE.md. The reader reproduces the
Fortran list-directed read for the forms hdbexport writes and refuses the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LINE_LENGTH = 256
ID_LENGTH = 20
NAME_LENGTH = 32
MAX_TIE_LINES = 32
MAX_UNITS = 64
MAX_FEEDERS = 256

_REAL = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$")
_INTEGER = re.compile(r"^[+-]?\d+$")
_REPEAT = re.compile(r"^\d+\*")


class SavecaseError(ValueError):
    """The legacy reader's IERR: 2 = malformed or over-capacity record."""

    def __init__(self, ierr: int, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.ierr = ierr
        self.line = line
        self.message = message


@dataclass
class ExportRecords:
    name: str = ""
    frequency_id: str = ""
    actual_hz: float = 60.0
    scheduled_hz: float = 60.0
    bias_mw_per_0_1hz: float = 0.0
    frequency_quality: str = "N"
    meter_error_mw: float = 0.0
    tie_lines: list[dict[str, object]] = field(default_factory=list)
    units: list[dict[str, object]] = field(default_factory=list)
    feeders: list[dict[str, object]] = field(default_factory=list)


_BLANKS = " \t"


def split_fields(text: str) -> list[str]:
    """List-directed field split: blanks/tabs or one comma separate, quotes group (SC-7).
    Null values, repeat counts and slash terminators are refused (D-5)."""
    fields: list[str] = []
    index, length = 0, len(text)
    while True:
        while index < length and text[index] in _BLANKS:
            index += 1
        if index >= length:
            return fields
        char = text[index]
        if char == ",":
            raise ValueError("null value in list-directed input")
        if char == "/":
            raise ValueError("slash terminator in list-directed input")
        if char in "'\"":
            quote, index, token = char, index + 1, []
            while True:
                if index >= length:
                    raise ValueError("unterminated quoted field")
                if text[index] == quote:
                    if index + 1 < length and text[index + 1] == quote:
                        token.append(quote)
                        index += 2
                        continue
                    index += 1
                    break
                token.append(text[index])
                index += 1
            fields.append("".join(token))
        else:
            start = index
            while index < length and text[index] not in _BLANKS + ",/":
                index += 1
            token = text[start:index]
            if _REPEAT.match(token):
                raise ValueError(f"repeat count {token!r} in list-directed input")
            fields.append(token)
        while index < length and text[index] in _BLANKS:
            index += 1
        if index < length and text[index] == ",":
            index += 1


def _real(token: str) -> float:
    if not _REAL.match(token):
        raise ValueError(f"{token!r} is not a finite real number")
    return float(token.replace("d", "e").replace("D", "e"))


def _integer(token: str) -> int:
    if not _INTEGER.match(token):
        raise ValueError(f"{token!r} is not an integer")
    return int(token)


def _take(fields: list[str], count: int, record: str) -> list[str]:
    if len(fields) < count:
        raise ValueError(f"{record} record needs {count} fields, found {len(fields)}")
    return fields[:count]


def parse_export(text: str) -> ExportRecords:
    case = ExportRecords()
    record = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")[:LINE_LENGTH].ljust(LINE_LENGTH)
        if not line.strip() or line.startswith("*"):
            continue
        if line.startswith("SAVECASE "):
            case.name = line[9:].lstrip()[:NAME_LENGTH].rstrip()
            continue
        if line.startswith("RECORD "):
            record = line[7:].strip()[:ID_LENGTH]
            continue
        if line.startswith("END"):
            break
        if line.startswith(("CLONE", "TIMESTAMP")):
            continue
        if record not in {"FREQ", "TIELINE", "METERR", "UNIT", "FEEDER"}:
            continue
        try:
            _apply(case, record, line)
        except ValueError as exc:
            raise SavecaseError(2, number, f"{record}: {exc}") from exc
    return case


def _apply(case: ExportRecords, record: str, line: str) -> None:
    fields = split_fields(line)
    if record == "FREQ":
        ident, actual, scheduled, bias, quality = _take(fields, 5, record)
        case.frequency_id = ident[:ID_LENGTH]
        case.actual_hz = _real(actual)
        case.scheduled_hz = _real(scheduled)
        case.bias_mw_per_0_1hz = _real(bias)
        case.frequency_quality = quality[:1] or " "
    elif record == "TIELINE":
        if len(case.tie_lines) >= MAX_TIE_LINES:
            raise ValueError(f"more than {MAX_TIE_LINES} tie lines")
        ident, actual, scheduled, quality = _take(fields, 4, record)
        case.tie_lines.append(
            {
                "id": ident[:ID_LENGTH],
                "actual_mw": _real(actual),
                "scheduled_mw": _real(scheduled),
                "quality": quality[:1] or " ",
            }
        )
    elif record == "METERR":
        _, value = _take(fields, 2, record)
        case.meter_error_mw = _real(value)
    elif record == "UNIT":
        if len(case.units) >= MAX_UNITS:
            raise ValueError(f"more than {MAX_UNITS} units")
        ident, output, low, high, ramp, share, agc = _take(fields, 7, record)
        case.units.append(
            {
                "id": ident[:ID_LENGTH],
                "output_mw": _real(output),
                "min_mw": _real(low),
                "max_mw": _real(high),
                "ramp_mw_per_min": _real(ramp),
                "participation": _real(share),
                "on_agc": agc[:1] == "T",
            }
        )
    else:
        if len(case.feeders) >= MAX_FEEDERS:
            raise ValueError(f"more than {MAX_FEEDERS} feeders")
        ident, load, block, priority = _take(fields, 4, record)
        case.feeders.append(
            {
                "id": ident[:ID_LENGTH],
                "load_mw": _real(load),
                "shed_block": _integer(block),
                "priority": _integer(priority),
            }
        )


def to_area_payload(case: ExportRecords) -> dict[str, object]:
    """Shape the export as the service's AreaState payload."""
    return {
        "savecase": case.name,
        "frequency": {
            "id": case.frequency_id or "AREA",
            "actual_hz": case.actual_hz,
            "scheduled_hz": case.scheduled_hz,
            "bias_mw_per_0_1hz": case.bias_mw_per_0_1hz,
            "quality": case.frequency_quality,
        },
        "meter_error_mw": case.meter_error_mw,
        "tie_lines": case.tie_lines,
        "units": case.units,
    }
