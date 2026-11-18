"""Tests for read-only BTS reference ZIP preflight behavior."""

import csv
import hashlib
import io
import struct
import zipfile
from pathlib import Path

import pytest

import backend.app.data_ingestion.bts_reference_preflight as preflight_module
from backend.app.data_ingestion.bts_reference_csv import (
    CARRIER_DECODE_DATASET,
    CARRIER_DECODE_HEADERS,
    MASTER_COORDINATE_DATASET,
    MASTER_COORDINATE_HEADERS,
)
from backend.app.data_ingestion.bts_reference_preflight import (
    BTSReferencePreflightReport,
    EXPECTED_CSV_MEMBER,
    EXPECTED_ZIP_SHA256,
    _finalize_dry_run_readiness,
    _reconcile_report_counts,
    preflight_reference_zip,
)


def _csv_bytes(headers, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _write_zip(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return path


def _set_expected_checksum(monkeypatch, dataset_identifier, path):
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(EXPECTED_ZIP_SHA256, dataset_identifier, checksum)
    return checksum


def _carrier_row(**overrides):
    values = [""] * len(CARRIER_DECODE_HEADERS)
    values[CARRIER_DECODE_HEADERS.index("AIRLINE_ID")] = "00019031"
    values[CARRIER_DECODE_HEADERS.index("CARRIER")] = "MAC"
    values[CARRIER_DECODE_HEADERS.index("CARRIER_NAME")] = "Mackey International"
    for field_name, value in overrides.items():
        values[CARRIER_DECODE_HEADERS.index(field_name)] = value
    return values


def _airport_row(**overrides):
    values = [""] * len(MASTER_COORDINATE_HEADERS)
    values[MASTER_COORDINATE_HEADERS.index("AIRPORT_SEQ_ID")] = "01000101"
    values[MASTER_COORDINATE_HEADERS.index("AIRPORT_ID")] = "0010001"
    values[MASTER_COORDINATE_HEADERS.index("AIRPORT")] = "01A"
    for field_name, value in overrides.items():
        values[MASTER_COORDINATE_HEADERS.index(field_name)] = value
    return values


def _valid_carrier_zip(path, rows):
    return _write_zip(
        path,
        [
            (
                EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET],
                _csv_bytes(CARRIER_DECODE_HEADERS, rows),
            )
        ],
    )


def test_zip_checksum_mismatch_fails_preflight(tmp_path):
    path = _valid_carrier_zip(tmp_path / "carrier.zip", [_carrier_row()])
    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.checksum_matches is False
    assert report.zip_integrity is True
    assert report.dry_run_ready is False
    assert report.errors


@pytest.mark.parametrize("members", [[], [("unexpected.csv", b"a,b\n1,2\n")]])
def test_missing_expected_csv_member_fails_preflight(tmp_path, monkeypatch, members):
    path = _write_zip(tmp_path / "missing.csv.zip", members)
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)
    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.checksum_matches is True
    assert report.csv_member is None
    assert report.dry_run_ready is False


def test_multiple_csv_members_are_rejected_as_ambiguous(tmp_path, monkeypatch):
    path = _valid_carrier_zip(tmp_path / "ambiguous.zip", [_carrier_row()])
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extra.csv", b"also,not,expected\n")
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.csv_members == ("T_CARRIER_DECODE.csv", "extra.csv")
    assert report.csv_member is None
    assert report.dry_run_ready is False


def test_duplicate_expected_csv_member_names_are_rejected(tmp_path, monkeypatch):
    expected_member = EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET]
    row_data = _csv_bytes(CARRIER_DECODE_HEADERS, [_carrier_row()])
    path = tmp_path / "duplicate-name.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_zip(path, [(expected_member, row_data), (expected_member, row_data)])
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.csv_members == (expected_member, expected_member)
    assert report.csv_member is None
    assert report.dry_run_ready is False


def test_zip_crc_failure_is_rejected(tmp_path, monkeypatch):
    path = _valid_carrier_zip(tmp_path / "crc.zip", [_carrier_row()])
    with zipfile.ZipFile(path, "r") as archive:
        info = archive.getinfo(EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET])
    payload = bytearray(path.read_bytes())
    filename_length, extra_length = struct.unpack_from("<HH", payload, info.header_offset + 26)
    data_offset = info.header_offset + 30 + filename_length + extra_length
    payload[data_offset] ^= 0x01
    path.write_bytes(payload)
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.checksum_matches is True
    assert report.zip_integrity is False
    assert report.dry_run_ready is False


def test_header_mismatch_fails_preflight(tmp_path, monkeypatch):
    wrong_headers = list(CARRIER_DECODE_HEADERS)
    wrong_headers[-1] = "UNEXPECTED_DATE_COLUMN"
    path = _write_zip(
        tmp_path / "header.zip",
        [
            (
                EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET],
                _csv_bytes(wrong_headers, [_carrier_row()]),
            )
        ],
    )
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.headers_match is False
    assert report.dry_run_ready is False


def test_malformed_csv_row_is_counted_and_fails_preflight(tmp_path, monkeypatch):
    content = _csv_bytes(CARRIER_DECODE_HEADERS, []) + b"too,few,fields\n"
    path = _write_zip(
        tmp_path / "malformed.zip",
        [(EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET], content)],
    )
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.headers_match is True
    assert report.malformed_rows == 1
    assert report.rejected_rows == 1
    assert report.dry_run_ready is False


def test_late_malformed_row_keeps_partial_counts_failed(tmp_path, monkeypatch):
    first = _carrier_row()
    second = _carrier_row(CARRIER_NAME="Another version")
    content = _csv_bytes(CARRIER_DECODE_HEADERS, [first, second, first])
    content += b"too,few,fields\n"
    path = _write_zip(
        tmp_path / "late-malformed.zip",
        [(EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET], content)],
    )
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.parsed_rows == 3
    assert report.unique_fingerprints == 2
    assert report.duplicate_occurrences == 1
    assert report.malformed_rows == 1
    assert report.rejected_rows == 1
    assert report.parse_complete is False
    assert report.reconciliation_matches is False
    assert report.dry_run_ready is False


def test_reconciliation_failure_blocks_dry_run_readiness():
    """An inconsistent complete-scan summary cannot be marked ready."""
    expected_member = EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET]
    report = BTSReferencePreflightReport(
        dataset_identifier=CARRIER_DECODE_DATASET,
        source_path="synthetic-inconsistent-report",
        expected_zip_sha256="0" * 64,
        checksum_matches=True,
        zip_integrity=True,
        csv_member=expected_member,
        headers_match=True,
        parse_complete=True,
        parsed_rows=4,
        unique_fingerprints=3,
        duplicate_occurrences=0,
        fingerprints_reproducible=True,
        model_schema_compatible=True,
    )

    assert _reconcile_report_counts(report) is False
    _finalize_dry_run_readiness(report, expected_member)

    assert report.reconciliation_matches is False
    assert report.dry_run_ready is False
    assert report.errors


def test_duplicate_fingerprints_reconcile_without_rejecting_rows(
    tmp_path, monkeypatch
):
    first = _carrier_row()
    second = _carrier_row(CARRIER_NAME="Distinct carrier row")
    path = _valid_carrier_zip(tmp_path / "duplicates.zip", [first, first, second])
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.parsed_rows == 3
    assert report.unique_fingerprints == 2
    assert report.duplicate_occurrences == 1
    assert report.reconciliation_matches is True
    assert report.fingerprints_reproducible is True
    assert report.rejected_rows == 0


def test_conflicting_identity_candidates_are_reported_not_deduplicated(
    tmp_path, monkeypatch
):
    first = _carrier_row(CARRIER_NAME="Carrier version A")
    second = _carrier_row(CARRIER_NAME="Carrier version B")
    path = _valid_carrier_zip(tmp_path / "conflicts.zip", [first, second])
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert report.parsed_rows == 2
    assert report.unique_fingerprints == 2
    assert report.duplicate_occurrences == 0
    assert report.conflict_groups["AIRLINE_ID"] == 1
    assert report.conflict_examples["AIRLINE_ID"] == (("00019031", 2),)
    assert report.dry_run_ready is True


def test_airport_conflicts_report_dot_id_and_sequence_candidates(
    tmp_path, monkeypatch
):
    first = _airport_row(DISPLAY_AIRPORT_NAME="Version A")
    second = _airport_row(DISPLAY_AIRPORT_NAME="Version B")
    content = _csv_bytes(MASTER_COORDINATE_HEADERS, [first, second])
    path = _write_zip(
        tmp_path / "airport-conflicts.zip",
        [(EXPECTED_CSV_MEMBER[MASTER_COORDINATE_DATASET], content)],
    )
    _set_expected_checksum(monkeypatch, MASTER_COORDINATE_DATASET, path)

    report = preflight_reference_zip(path, MASTER_COORDINATE_DATASET)

    assert report.parsed_rows == 2
    assert report.unique_fingerprints == 2
    assert report.conflict_groups["AIRPORT_ID"] == 1
    assert report.conflict_groups["AIRPORT_SEQ_ID"] == 1
    assert report.conflict_examples["AIRPORT_ID"] == (("0010001", 2),)
    assert report.conflict_examples["AIRPORT_SEQ_ID"] == (("01000101", 2),)
    assert report.dry_run_ready is True


@pytest.mark.parametrize(
    "missing_field",
    ["AIRPORT_ID", "AIRPORT_SEQ_ID"],
)
def test_blank_required_airport_identifier_blocks_readiness(
    tmp_path, monkeypatch, missing_field
):
    row = _airport_row(**{missing_field: ""})
    content = _csv_bytes(MASTER_COORDINATE_HEADERS, [row])
    path = _write_zip(
        tmp_path / f"missing-{missing_field.lower()}.zip",
        [(EXPECTED_CSV_MEMBER[MASTER_COORDINATE_DATASET], content)],
    )
    _set_expected_checksum(monkeypatch, MASTER_COORDINATE_DATASET, path)

    report = preflight_reference_zip(path, MASTER_COORDINATE_DATASET)

    assert report.parse_complete is True
    assert report.missing_required_identity_rows == 1
    assert report.dry_run_ready is False


def test_dataset_readiness_reports_are_independent(tmp_path, monkeypatch):
    carrier_path = _valid_carrier_zip(
        tmp_path / "carrier-missing-id.zip", [_carrier_row(AIRLINE_ID="")]
    )
    airport_path = _write_zip(
        tmp_path / "valid-airport.zip",
        [
            (
                EXPECTED_CSV_MEMBER[MASTER_COORDINATE_DATASET],
                _csv_bytes(MASTER_COORDINATE_HEADERS, [_airport_row()]),
            )
        ],
    )
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, carrier_path)
    _set_expected_checksum(monkeypatch, MASTER_COORDINATE_DATASET, airport_path)

    carrier_report = preflight_reference_zip(carrier_path, CARRIER_DECODE_DATASET)
    airport_report = preflight_reference_zip(airport_path, MASTER_COORDINATE_DATASET)

    assert carrier_report.dry_run_ready is False
    assert airport_report.dry_run_ready is True


@pytest.mark.parametrize("malformed", [False, True], ids=["success", "failed-scan"])
def test_temporary_files_are_cleaned_and_source_zip_is_unchanged(
    tmp_path, monkeypatch, malformed
):
    row = _carrier_row()
    content = _csv_bytes(CARRIER_DECODE_HEADERS, [row])
    if malformed:
        content += b"too,few,fields\n"
    path = _write_zip(
        tmp_path / "source.zip",
        [(EXPECTED_CSV_MEMBER[CARRIER_DECODE_DATASET], content)],
    )
    _set_expected_checksum(monkeypatch, CARRIER_DECODE_DATASET, path)
    original_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    real_temporary_directory = preflight_module.tempfile.TemporaryDirectory
    temp_paths: list[Path] = []

    def tracking_temporary_directory(*args, **kwargs):
        temporary_directory = real_temporary_directory(*args, **kwargs)
        temp_paths.append(Path(temporary_directory.name))
        return temporary_directory

    monkeypatch.setattr(
        preflight_module.tempfile,
        "TemporaryDirectory",
        tracking_temporary_directory,
    )

    report = preflight_reference_zip(path, CARRIER_DECODE_DATASET)

    assert len(temp_paths) == 1
    assert all(not temporary_path.exists() for temporary_path in temp_paths)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_sha256
    assert report.dry_run_ready is (not malformed)


