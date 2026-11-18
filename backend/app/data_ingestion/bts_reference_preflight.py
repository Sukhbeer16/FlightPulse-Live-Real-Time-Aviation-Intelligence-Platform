"""Read-only ZIP and CSV preflight for local BTS reference releases."""

from __future__ import annotations

import csv
import hashlib
import heapq
import shutil
import tempfile
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import CheckConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.data_ingestion.bts_reference_csv import (
    CARRIER_DECODE_DATASET,
    FINGERPRINT_SCHEMA_VERSION,
    MASTER_COORDINATE_DATASET,
    HeaderValidationError,
    MalformedCSVRowError,
    iter_reference_csv,
)
from backend.app.database.models.bts_reference import (
    BTSAirportReference,
    BTSCarrierReference,
    BTSReferenceRelease,
)


EXPECTED_ZIP_SHA256 = {
    CARRIER_DECODE_DATASET: (
        "1912da934d5dbfe2dfb92ce1a633c1a98ddc819e2f7f104cd14b708065d6ec81"
    ),
    MASTER_COORDINATE_DATASET: (
        "683659c7e701e9c8105a31f725833a01c246de9bef9895f83bec76f8c2943695"
    ),
}

EXPECTED_CSV_MEMBER = {
    CARRIER_DECODE_DATASET: "T_CARRIER_DECODE.csv",
    MASTER_COORDINATE_DATASET: "T_MASTER_CORD.csv",
}
CONFLICT_EXAMPLE_LIMIT = 20


@dataclass
class BTSReferencePreflightReport:
    dataset_identifier: str
    source_path: str
    expected_zip_sha256: str
    fingerprint_schema_version: str = FINGERPRINT_SCHEMA_VERSION
    zip_sha256: str | None = None
    checksum_matches: bool | None = None
    zip_integrity: bool | None = None
    csv_member: str | None = None
    csv_members: tuple[str, ...] = ()
    headers_match: bool | None = None
    parse_complete: bool | None = None
    parsed_rows: int = 0
    unique_fingerprints: int = 0
    duplicate_occurrences: int = 0
    malformed_rows: int = 0
    rejected_rows: int = 0
    missing_required_identity_rows: int = 0
    conflict_groups: dict[str, int] = field(default_factory=dict)
    conflict_examples: dict[str, tuple[tuple[str, int], ...]] = field(
        default_factory=dict
    )
    reconciliation_matches: bool | None = None
    fingerprints_reproducible: bool | None = None
    model_schema_compatible: bool = False
    database_schema_verified: bool = False
    dry_run_ready: bool = False
    matching_release_status: str = "not checked: database access is not used"
    errors: list[str] = field(default_factory=list)
    _fingerprint_stream_digest: bytes | None = field(default=None, repr=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_release_row_fingerprint_constraint(model: type) -> bool:
    return any(
        isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("release_id", "row_fingerprint")
        for constraint in model.__table__.constraints
    )


def _has_unique_column_set(model: type, columns: tuple[str, ...]) -> bool:
    return any(
        isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns) == columns
        for constraint in model.__table__.constraints
    )


def _model_schema_compatibility(dataset_identifier: str) -> bool:
    release_table = BTSReferenceRelease.__table__
    required_release_columns = {
        "source_agency",
        "dataset_name",
        "source_artifact_sha256",
        "fingerprint_schema_version",
        "status",
        "completed_at",
    }
    if not required_release_columns.issubset(release_table.c.keys()):
        return False
    if not _has_unique_column_set(
        BTSReferenceRelease,
        ("source_agency", "dataset_name", "source_artifact_sha256"),
    ):
        return False
    release_checks = [
        " ".join(str(constraint.sqltext).split()).lower()
        for constraint in release_table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    if not any(
        "status is null or status in ('pending', 'failed', 'complete')" in check
        for check in release_checks
    ) or not any(
        "case when status is null then completed_at is null" in check
        and "when status = 'complete' then completed_at is not null" in check
        and "else completed_at is null" in check
        for check in release_checks
    ):
        return False

    if dataset_identifier == CARRIER_DECODE_DATASET:
        row_model = BTSCarrierReference
        required_id_columns = ("dot_carrier_id",)
    elif dataset_identifier == MASTER_COORDINATE_DATASET:
        row_model = BTSAirportReference
        required_id_columns = ("dot_airport_id", "dot_airport_seq_id")
    else:
        return False

    row_table = row_model.__table__
    return (
        all(isinstance(row_table.c[name].type, Text) for name in required_id_columns)
        and isinstance(row_table.c.source_values.type, JSONB)
        and "row_fingerprint" in row_table.c
        and _has_release_row_fingerprint_constraint(row_model)
    )


def _identity_fields(dataset_identifier: str) -> tuple[str, ...]:
    if dataset_identifier == CARRIER_DECODE_DATASET:
        return ("AIRLINE_ID",)
    return ("AIRPORT_ID", "AIRPORT_SEQ_ID")


def _summarize_conflicts(
    identity_counts: dict[str, Counter[str]],
) -> tuple[dict[str, int], dict[str, tuple[tuple[str, int], ...]]]:
    groups: dict[str, int] = {}
    examples: dict[str, tuple[tuple[str, int], ...]] = {}
    for field_name, counts in identity_counts.items():
        groups[field_name] = sum(1 for count in counts.values() if count > 1)
        examples[field_name] = tuple(
            heapq.nsmallest(
                CONFLICT_EXAMPLE_LIMIT,
                (
                    (identity, count)
                    for identity, count in counts.items()
                    if count > 1
                ),
            )
        )
    return groups, examples


def _reconcile_report_counts(report: BTSReferencePreflightReport) -> bool:
    """Reconcile complete-parser counts; incomplete scans always fail."""
    report.reconciliation_matches = (
        report.parse_complete is True
        and report.parsed_rows
        == report.unique_fingerprints + report.duplicate_occurrences
    )
    if not report.reconciliation_matches:
        report.errors.append("Parsed, unique, and duplicate counts do not reconcile.")
    return report.reconciliation_matches


def _finalize_dry_run_readiness(
    report: BTSReferencePreflightReport, expected_member: str
) -> None:
    report.dry_run_ready = all(
        (
            report.checksum_matches,
            report.zip_integrity,
            report.csv_member == expected_member,
            report.headers_match,
            report.parse_complete,
            report.reconciliation_matches,
            report.fingerprints_reproducible,
            report.model_schema_compatible,
            report.missing_required_identity_rows == 0,
            report.malformed_rows == 0,
            report.rejected_rows == 0,
        )
    )


def _scan_csv(
    csv_path: Path,
    dataset_identifier: str,
    report: BTSReferencePreflightReport,
) -> bool:
    seen_fingerprints: set[str] = set()
    identity_counts: dict[str, Counter[str]] = {
        field_name: Counter() for field_name in _identity_fields(dataset_identifier)
    }
    identity_indexes: dict[str, int] = {}
    digest = hashlib.sha256()

    try:
        rows = iter_reference_csv(csv_path, dataset_identifier)
        for row in rows:
            if report.headers_match is None:
                report.headers_match = True
                identity_indexes = {
                    name: row.headers.index(name)
                    for name in identity_counts
                }

            report.parsed_rows += 1
            digest.update(bytes.fromhex(row.fingerprint))

            missing_identity = False
            for name, index in identity_indexes.items():
                value = row.values[index]
                if value == "":
                    # Every field in _identity_fields is required by the
                    # corresponding normalized reference model.
                    missing_identity = True
                    continue

            if missing_identity:
                report.missing_required_identity_rows += 1

            if row.fingerprint in seen_fingerprints:
                report.duplicate_occurrences += 1
                continue

            seen_fingerprints.add(row.fingerprint)
            for name, index in identity_indexes.items():
                value = row.values[index]
                if value != "":
                    identity_counts[name][value] += 1

    except HeaderValidationError as error:
        report.headers_match = False
        report.parse_complete = False
        report.errors.append(str(error))
        return False
    except (MalformedCSVRowError, UnicodeDecodeError) as error:
        report.malformed_rows += 1
        report.rejected_rows += 1
        if isinstance(error, MalformedCSVRowError):
            report.headers_match = True
        elif report.headers_match is None and report.parsed_rows > 0:
            report.headers_match = True
        report.parse_complete = False
        report.unique_fingerprints = len(seen_fingerprints)
        report.reconciliation_matches = False
        report.conflict_groups, report.conflict_examples = _summarize_conflicts(
            identity_counts
        )
        report._fingerprint_stream_digest = digest.digest()
        report.errors.append(str(error))
        return False
    except csv.Error as error:
        report.headers_match = False
        report.parse_complete = False
        report.errors.append(f"Malformed CSV header or syntax: {error}")
        return False

    if report.headers_match is None:
        # A header-only file still passed the parser's exact header validation.
        report.headers_match = True
    report.parse_complete = True

    report.unique_fingerprints = len(seen_fingerprints)
    _reconcile_report_counts(report)

    report.conflict_groups, report.conflict_examples = _summarize_conflicts(
        identity_counts
    )
    report._fingerprint_stream_digest = digest.digest()
    return True


def _fingerprints_reproduce(
    csv_path: Path,
    dataset_identifier: str,
    first_digest: bytes,
    expected_rows: int,
) -> bool:
    digest = hashlib.sha256()
    rows_seen = 0
    for row in iter_reference_csv(csv_path, dataset_identifier):
        digest.update(bytes.fromhex(row.fingerprint))
        rows_seen += 1
    return rows_seen == expected_rows and digest.digest() == first_digest


def preflight_reference_zip(
    source_zip: str | Path, dataset_identifier: str
) -> BTSReferencePreflightReport:
    """Validate a local BTS reference ZIP without database access or writes.

    The selected CSV is copied in bounded chunks to a generated temporary file
    because the existing parser accepts filesystem paths. No source archive is
    extracted or modified.
    """
    if dataset_identifier not in EXPECTED_ZIP_SHA256:
        raise ValueError(f"Unsupported BTS reference dataset: {dataset_identifier}")

    path = Path(source_zip)
    expected_checksum = EXPECTED_ZIP_SHA256[dataset_identifier]
    report = BTSReferencePreflightReport(
        dataset_identifier=dataset_identifier,
        source_path=str(path),
        expected_zip_sha256=expected_checksum,
        model_schema_compatible=_model_schema_compatibility(dataset_identifier),
    )
    if not report.model_schema_compatible:
        report.errors.append("Current BTS reference models are not import-compatible.")

    try:
        report.zip_sha256 = _sha256_file(path)
    except OSError as error:
        report.errors.append(f"Cannot read source ZIP: {error}")
        return report
    report.checksum_matches = report.zip_sha256 == expected_checksum
    if not report.checksum_matches:
        report.errors.append(
            f"ZIP SHA-256 mismatch: expected {expected_checksum}, "
            f"received {report.zip_sha256}."
        )

    expected_member = EXPECTED_CSV_MEMBER[dataset_identifier]
    try:
        with zipfile.ZipFile(path, "r") as archive:
            csv_infos = [
                entry
                for entry in archive.infolist()
                if entry.filename.lower().endswith(".csv")
            ]
            report.csv_members = tuple(entry.filename for entry in csv_infos)
            expected_infos = [
                entry for entry in csv_infos if entry.filename == expected_member
            ]
            if len(csv_infos) == 1 and len(expected_infos) == 1:
                report.csv_member = expected_member
            else:
                report.errors.append(
                    f"Expected exactly one CSV member named {expected_member}; "
                    f"found {report.csv_members!r}."
                )

            bad_member = archive.testzip()
            report.zip_integrity = bad_member is None
            if bad_member is not None:
                report.errors.append(f"ZIP CRC check failed for {bad_member}.")

            if (
                not report.checksum_matches
                or not report.zip_integrity
                or report.csv_member is None
            ):
                return report

            with tempfile.TemporaryDirectory(prefix="flightpulse-bts-preflight-") as temp_dir:
                csv_path = Path(temp_dir) / "selected_source.csv"
                with archive.open(expected_infos[0], "r") as member_stream:
                    with csv_path.open("wb") as output:
                        shutil.copyfileobj(member_stream, output, length=1024 * 1024)

                parse_succeeded = _scan_csv(csv_path, dataset_identifier, report)
                if parse_succeeded:
                    first_digest = report._fingerprint_stream_digest
                    assert first_digest is not None
                    try:
                        report.fingerprints_reproducible = _fingerprints_reproduce(
                            csv_path,
                            dataset_identifier,
                            first_digest,
                            report.parsed_rows,
                        )
                    except (
                        HeaderValidationError,
                        MalformedCSVRowError,
                        UnicodeDecodeError,
                    ) as error:
                        report.fingerprints_reproducible = False
                        report.errors.append(
                            f"Fingerprint repeat pass failed: {error}"
                        )
                    if not report.fingerprints_reproducible:
                        report.errors.append(
                            "Fingerprints did not reproduce on a second streaming pass."
                        )

    except (
        OSError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as error:
        report.zip_integrity = False
        report.errors.append(f"ZIP verification or member read failed: {error}")
        return report

    if report.missing_required_identity_rows:
        report.errors.append(
            f"{report.missing_required_identity_rows} source rows lack a required "
            "DOT identity for the non-null normalized model field."
        )

    _finalize_dry_run_readiness(report, expected_member)
    return report
