"""Focused tests for raw BTS reference CSV parsing and fingerprints."""

import csv
import hashlib

import pytest

from backend.app.data_ingestion.bts_reference_csv import (
    CARRIER_DECODE_DATASET,
    CARRIER_DECODE_HEADERS,
    MASTER_COORDINATE_DATASET,
    MASTER_COORDINATE_HEADERS,
    HeaderValidationError,
    MalformedCSVRowError,
    fingerprint_row,
    iter_reference_csv,
)


def _write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


def _carrier_values(**overrides):
    values = [""] * len(CARRIER_DECODE_HEADERS)
    for name, value in overrides.items():
        values[CARRIER_DECODE_HEADERS.index(name)] = value
    return values


def _golden_serialization(headers, values):
    """Independent test-only encoder for the documented v1 wire format."""

    def text_field(value):
        encoded = value.encode("utf-8")
        return len(encoded).to_bytes(8, "big", signed=False) + encoded

    result = bytearray()
    result.extend(text_field("flightpulse-bts-reference-row-v1"))
    result.extend(text_field("bts-aviation-support:carrier-decode"))
    result.extend(len(headers).to_bytes(8, "big", signed=False))
    for header, value in zip(headers, values):
        result.extend(text_field(header))
        if value is None:
            result.extend(b"\x00")
        else:
            result.extend(b"\x01")
            result.extend(text_field(value))
    return bytes(result)


def test_fingerprint_is_stable_across_repeated_runs():
    values = _carrier_values(AIRLINE_ID="000123", CARRIER_NAME="Example Air")
    first = fingerprint_row(CARRIER_DECODE_DATASET, CARRIER_DECODE_HEADERS, values)
    second = fingerprint_row(CARRIER_DECODE_DATASET, CARRIER_DECODE_HEADERS, values)
    assert first == second
    assert len(first) == 64
    assert first == first.lower()


def test_fingerprint_matches_independent_v1_golden_vector():
    # Literal header list pins the source order independently of the production
    # constants; the value list includes leading zeroes, UTF-8, and empty cells.
    headers = (
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
    values = (
        "000123",
        "",
        "",
        "M\u00fcnchen Air",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    )
    expected_bytes = _golden_serialization(headers, values)
    expected_digest = hashlib.sha256(expected_bytes).hexdigest()

    # Independently pinned from the v1 byte contract, not produced by the
    # production fingerprint function.
    assert len(expected_bytes) == 499
    assert expected_digest == (
        "576b96db08c06aad9e1ee16ac66d7c7404055704ce3cc0131daeccfd0542a5aa"
    )
    assert fingerprint_row(CARRIER_DECODE_DATASET, headers, values) == expected_digest


def test_fingerprint_changes_with_dataset_or_any_source_value():
    carrier_values = _carrier_values(AIRLINE_ID="00123")
    changed_values = _carrier_values(AIRLINE_ID="00124")
    assert fingerprint_row(
        CARRIER_DECODE_DATASET, CARRIER_DECODE_HEADERS, carrier_values
    ) != fingerprint_row(
        CARRIER_DECODE_DATASET, CARRIER_DECODE_HEADERS, changed_values
    )

    airport_values = [""] * len(MASTER_COORDINATE_HEADERS)
    assert fingerprint_row(
        CARRIER_DECODE_DATASET, CARRIER_DECODE_HEADERS, carrier_values
    ) != fingerprint_row(
        MASTER_COORDINATE_DATASET,
        MASTER_COORDINATE_HEADERS,
        airport_values,
    )


def test_empty_string_and_explicit_null_have_different_fingerprints():
    empty_values = _carrier_values(AIRLINE_ID="")
    null_values = list(empty_values)
    null_values[0] = None
    assert fingerprint_row(
        CARRIER_DECODE_DATASET, CARRIER_DECODE_HEADERS, empty_values
    ) != fingerprint_row(CARRIER_DECODE_DATASET, CARRIER_DECODE_HEADERS, null_values)


def test_parser_preserves_leading_zeroes_utf8_and_ordered_source_pairs(tmp_path):
    path = tmp_path / "carrier.csv"
    values = _carrier_values(AIRLINE_ID="000123", CARRIER_NAME="München Air")
    _write_csv(path, CARRIER_DECODE_HEADERS, [values])

    parsed = list(iter_reference_csv(path, CARRIER_DECODE_DATASET))[0]
    assert parsed.values[0] == "000123"
    assert parsed.values[3] == "München Air"
    assert parsed.source_values == [
        [header, value]
        for header, value in zip(CARRIER_DECODE_HEADERS, values)
    ]
    assert [pair[0] for pair in parsed.source_values] == list(CARRIER_DECODE_HEADERS)


@pytest.mark.parametrize(
    "source_value",
    [
        "Carrier, with comma",
        'Carrier says "hello"',
        "Carrier name with\nembedded newline",
    ],
)
def test_quoted_csv_values_and_source_pairs_are_preserved(tmp_path, source_value):
    path = tmp_path / "quoted.csv"
    values = _carrier_values(CARRIER_NAME=source_value, AIRLINE_ID="000007")
    _write_csv(path, CARRIER_DECODE_HEADERS, [values])

    parsed = list(iter_reference_csv(path, CARRIER_DECODE_DATASET))[0]

    assert parsed.values[3] == source_value
    assert parsed.values[0] == "000007"
    assert parsed.source_values == [
        [header, value]
        for header, value in zip(CARRIER_DECODE_HEADERS, values)
    ]


def test_header_order_must_match_exactly(tmp_path):
    path = tmp_path / "reordered.csv"
    _write_csv(path, tuple(reversed(CARRIER_DECODE_HEADERS)), [])
    with pytest.raises(HeaderValidationError, match="Unexpected headers"):
        list(iter_reference_csv(path, CARRIER_DECODE_DATASET))


@pytest.mark.parametrize(
    "headers",
    [
        CARRIER_DECODE_HEADERS[:-1],
        CARRIER_DECODE_HEADERS + ("UNEXPECTED_COLUMN",),
    ],
)
def test_missing_or_extra_header_columns_are_rejected(tmp_path, headers):
    path = tmp_path / "wrong_header.csv"
    _write_csv(path, headers, [])
    with pytest.raises(HeaderValidationError, match="Unexpected headers"):
        list(iter_reference_csv(path, CARRIER_DECODE_DATASET))


@pytest.mark.parametrize(
    "row_width",
    [len(CARRIER_DECODE_HEADERS) - 1, len(CARRIER_DECODE_HEADERS) + 1],
)
def test_missing_or_extra_row_fields_are_rejected(tmp_path, row_width):
    path = tmp_path / "wrong_width.csv"
    _write_csv(path, CARRIER_DECODE_HEADERS, [[""] * row_width])
    with pytest.raises(MalformedCSVRowError, match="expected .* fields"):
        list(iter_reference_csv(path, CARRIER_DECODE_DATASET))


def test_malformed_csv_syntax_is_rejected(tmp_path):
    path = tmp_path / "malformed.csv"
    path.write_text(
        ",".join(CARRIER_DECODE_HEADERS) + '\n"unterminated',
        encoding="utf-8",
    )
    with pytest.raises(MalformedCSVRowError, match="malformed CSV"):
        list(iter_reference_csv(path, CARRIER_DECODE_DATASET))

