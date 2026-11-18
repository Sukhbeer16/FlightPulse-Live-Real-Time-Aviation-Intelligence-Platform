"""Streaming parsing and row fingerprints for BTS reference CSV files."""

from __future__ import annotations

import csv
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


FINGERPRINT_SCHEMA_VERSION = "flightpulse-bts-reference-row-v1"
CARRIER_DECODE_DATASET = "bts-aviation-support:carrier-decode"
MASTER_COORDINATE_DATASET = "bts-aviation-support:master-coordinate"

CARRIER_DECODE_HEADERS = (
    "AIRLINE_ID",
    "CARRIER",
    "CARRIER_ENTITY",
    "CARRIER_NAME",
    "UNIQUE_CARRIER",
    "UNIQUE_CARRIER_ENTITY",
    "UNIQUE_CARRIER_NAME",
    "WAC",
    "CARRIER_GROUP",
    "CARRIER_GROUP_NEW",
    "REGION",
    "START_DATE_SOURCE",
    "THRU_DATE_SOURCE",
)

MASTER_COORDINATE_HEADERS = (
    "AIRPORT_SEQ_ID",
    "AIRPORT_ID",
    "AIRPORT",
    "DISPLAY_AIRPORT_NAME",
    "DISPLAY_AIRPORT_CITY_NAME_FULL",
    "AIRPORT_WAC_SEQ_ID2",
    "AIRPORT_WAC",
    "AIRPORT_COUNTRY_NAME",
    "AIRPORT_COUNTRY_CODE_ISO",
    "AIRPORT_STATE_NAME",
    "AIRPORT_STATE_CODE",
    "AIRPORT_STATE_FIPS",
    "CITY_MARKET_SEQ_ID",
    "CITY_MARKET_ID",
    "DISPLAY_CITY_MARKET_NAME_FULL",
    "CITY_MARKET_WAC_SEQ_ID2",
    "CITY_MARKET_WAC",
    "LAT_DEGREES",
    "LAT_HEMISPHERE",
    "LAT_MINUTES",
    "LAT_SECONDS",
    "LATITUDE",
    "LON_DEGREES",
    "LON_HEMISPHERE",
    "LON_MINUTES",
    "LON_SECONDS",
    "LONGITUDE",
    "UTC_LOCAL_TIME_VARIATION",
    "AIRPORT_START_DATE",
    "AIRPORT_THRU_DATE",
    "AIRPORT_IS_CLOSED",
    "AIRPORT_IS_LATEST",
)

EXPECTED_HEADERS = {
    CARRIER_DECODE_DATASET: CARRIER_DECODE_HEADERS,
    MASTER_COORDINATE_DATASET: MASTER_COORDINATE_HEADERS,
}


class HeaderValidationError(ValueError):
    """Raised when a CSV header does not exactly match its BTS export schema."""


class MalformedCSVRowError(ValueError):
    """Raised when a data row has a different number of fields than its header."""


@dataclass(frozen=True)
class BTSReferenceCSVRow:
    """One parsed row, retaining source text and its ordered headers."""

    dataset_identifier: str
    row_number: int
    headers: tuple[str, ...]
    values: tuple[str, ...]
    fingerprint: str

    @property
    def source_values(self) -> list[list[str | None]]:
        """Return ordered header/value pairs suitable for a JSONB array."""
        return [[header, value] for header, value in zip(self.headers, self.values)]


def _expected_headers(dataset_identifier: str) -> tuple[str, ...]:
    try:
        return EXPECTED_HEADERS[dataset_identifier]
    except KeyError as error:
        raise ValueError(f"Unsupported BTS reference dataset: {dataset_identifier}") from error


def validate_headers(
    dataset_identifier: str, headers: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Require an exact ordered match for a supported BTS export header."""
    expected = _expected_headers(dataset_identifier)
    actual = tuple(headers)
    if actual != expected:
        raise HeaderValidationError(
            f"Unexpected headers for {dataset_identifier}: expected {expected!r}, "
            f"received {actual!r}"
        )
    return expected


def _length_prefix(value: str) -> bytes:
    """Encode one string as an unsigned 64-bit byte length and UTF-8 payload."""
    encoded = value.encode("utf-8", errors="strict")
    return struct.pack(">Q", len(encoded)) + encoded


def fingerprint_row(
    dataset_identifier: str,
    headers: tuple[str, ...] | list[str],
    values: tuple[str | None, ...] | list[str | None],
) -> str:
    """Fingerprint one raw row using the approved v1 byte serialization.

    Strings are encoded exactly as provided, without trimming or normalization.
    ``None`` has its own marker and differs from an empty string. CSV parsing
    itself returns empty cells as ``""`` and never converts them to ``None``.
    """
    exact_headers = validate_headers(dataset_identifier, headers)
    if len(values) != len(exact_headers):
        raise MalformedCSVRowError(
            f"Expected {len(exact_headers)} values, received {len(values)}"
        )

    digest = hashlib.sha256()
    digest.update(_length_prefix(FINGERPRINT_SCHEMA_VERSION))
    digest.update(_length_prefix(dataset_identifier))
    digest.update(struct.pack(">Q", len(exact_headers)))

    for header, value in zip(exact_headers, values):
        digest.update(_length_prefix(header))
        if value is None:
            digest.update(b"\x00")
        elif isinstance(value, str):
            digest.update(b"\x01")
            digest.update(_length_prefix(value))
        else:
            raise TypeError(f"CSV field values must be str or None, got {type(value)!r}")

    return digest.hexdigest()


def iter_reference_csv(
    path: str | Path, dataset_identifier: str
) -> Iterator[BTSReferenceCSVRow]:
    """Stream a strict UTF-8 CSV, preserving every field as original text.

    A UTF-8 BOM is accepted and removed by the decoder. Cell contents are not
    trimmed, case-folded, normalized, parsed as dates, or converted to numbers.
    Malformed CSV syntax, header drift, and rows with the wrong width fail fast.
    """
    expected = _expected_headers(dataset_identifier)
    source_path = Path(path)
    with source_path.open(
        "r", encoding="utf-8-sig", errors="strict", newline=""
    ) as csv_file:
        reader = csv.reader(csv_file, strict=True)
        try:
            headers = tuple(next(reader))
        except StopIteration as error:
            raise HeaderValidationError(f"CSV is empty: {source_path}") from error
        validate_headers(dataset_identifier, headers)

        try:
            for row_number, row in enumerate(reader, start=1):
                if len(row) != len(expected):
                    raise MalformedCSVRowError(
                        f"{source_path}: data row {row_number} ends at physical line "
                        f"{reader.line_num}; expected {len(expected)} fields, "
                        f"received {len(row)}"
                    )
                values = tuple(row)
                yield BTSReferenceCSVRow(
                    dataset_identifier=dataset_identifier,
                    row_number=row_number,
                    headers=expected,
                    values=values,
                    fingerprint=fingerprint_row(
                        dataset_identifier, expected, values
                    ),
                )
        except csv.Error as error:
            raise MalformedCSVRowError(
                f"{source_path}: malformed CSV near physical line {reader.line_num}: "
                f"{error}"
            ) from error
