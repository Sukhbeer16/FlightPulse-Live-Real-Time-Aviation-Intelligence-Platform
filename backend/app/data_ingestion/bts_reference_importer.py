"""Transactional imports for the official BTS reference CSV releases."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from backend.app.data_ingestion.bts_reference_csv import (
    CARRIER_DECODE_DATASET,
    FINGERPRINT_SCHEMA_VERSION,
    MASTER_COORDINATE_DATASET,
    BTSReferenceCSVRow,
    iter_reference_csv,
)
from backend.app.data_ingestion.bts_reference_preflight import (
    BTSReferencePreflightReport,
    EXPECTED_CSV_MEMBER,
    preflight_reference_zip,
)
from backend.app.database.models.bts_reference import (
    BTSAirportReference,
    BTSCarrierReference,
    BTSReferenceRelease,
)


SOURCE_AGENCY = "BTS"
DEFAULT_BATCH_SIZE = 500
_ROW_UNIQUE_CONSTRAINTS = {
    CARRIER_DECODE_DATASET: "uq_bts_carrier_references_release_row_fingerprint",
    MASTER_COORDINATE_DATASET: "uq_bts_airport_references_release_row_fingerprint",
}


class BTSReferenceImportError(RuntimeError):
    """Raised when a source release cannot be safely imported."""


class BTSReferencePreflightRejected(BTSReferenceImportError):
    """Raised before database work when the source ZIP fails preflight."""

    def __init__(self, report: BTSReferencePreflightReport) -> None:
        self.report = report
        super().__init__(
            "BTS reference preflight failed: " + "; ".join(report.errors)
        )


class BTSLegacyReleaseNeedsReview(BTSReferenceImportError):
    """An old or unversioned release must not be silently reclassified."""


class BTSCompletedReleaseMismatch(BTSReferenceImportError):
    """A completed immutable release does not match the verified source."""


@dataclass(frozen=True)
class BTSReferenceImportReport:
    dataset_identifier: str
    release_id: UUID
    source_artifact_sha256: str
    status: str
    parsed_rows: int
    unique_fingerprints: int
    duplicate_occurrences: int
    inserted_rows: int
    existing_rows: int
    already_complete: bool = False


class _ImportStore(Protocol):
    """Small persistence boundary so the import flow can be tested without DB."""

    def transaction(self): ...

    def find_release(
        self, source_agency: str, dataset_name: str, checksum: str
    ) -> BTSReferenceRelease | None: ...

    def add_release(self, release: BTSReferenceRelease) -> None: ...

    def get_rows(
        self,
        model: type[BTSAirportReference] | type[BTSCarrierReference],
        release_id: UUID,
        fingerprints: Sequence[str],
    ) -> dict[str, list[list[str | None]] | None]: ...

    def insert_batch(
        self,
        model: type[BTSAirportReference] | type[BTSCarrierReference],
        rows: Sequence[dict[str, object]],
    ) -> tuple[set[str], dict[str, list[list[str | None]] | None]]: ...

    def count_rows(
        self,
        model: type[BTSAirportReference] | type[BTSCarrierReference],
        release_id: UUID,
    ) -> int: ...

    def flush(self) -> None: ...


class _SQLAlchemyImportStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def transaction(self):
        return self.session.begin()

    def find_release(
        self, source_agency: str, dataset_name: str, checksum: str
    ) -> BTSReferenceRelease | None:
        return self.session.execute(
            select(BTSReferenceRelease).where(
                BTSReferenceRelease.source_agency == source_agency,
                BTSReferenceRelease.dataset_name == dataset_name,
                BTSReferenceRelease.source_artifact_sha256 == checksum,
            )
        ).scalar_one_or_none()

    def add_release(self, release: BTSReferenceRelease) -> None:
        self.session.add(release)
        self.session.flush()

    def insert_batch(
        self,
        model: type[BTSAirportReference] | type[BTSCarrierReference],
        rows: Sequence[dict[str, object]],
    ) -> tuple[set[str], dict[str, list[list[str | None]] | None]]:
        if not rows:
            return set(), {}

        fingerprints = [str(row["row_fingerprint"]) for row in rows]
        statement = (
            postgresql_insert(model)
            .values(list(rows))
            .on_conflict_do_nothing(
                constraint=_ROW_UNIQUE_CONSTRAINTS[
                    CARRIER_DECODE_DATASET
                    if model is BTSCarrierReference
                    else MASTER_COORDINATE_DATASET
                ]
            )
            .returning(model.row_fingerprint)
        )
        inserted = set(self.session.scalars(statement).all())
        stored = self.get_rows(model, rows[0]["release_id"], fingerprints)
        return inserted, stored

    def get_rows(
        self,
        model: type[BTSAirportReference] | type[BTSCarrierReference],
        release_id: UUID,
        fingerprints: Sequence[str],
    ) -> dict[str, list[list[str | None]] | None]:
        if not fingerprints:
            return {}
        stored = self.session.execute(
            select(model.row_fingerprint, model.source_values).where(
                model.release_id == release_id,
                model.row_fingerprint.in_(fingerprints),
            )
        ).all()
        return {fingerprint: source_values for fingerprint, source_values in stored}

    def count_rows(
        self,
        model: type[BTSAirportReference] | type[BTSCarrierReference],
        release_id: UUID,
    ) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.release_id == release_id)
            )
            or 0
        )

    def flush(self) -> None:
        self.session.flush()


def _model_for_dataset(
    dataset_identifier: str,
) -> type[BTSCarrierReference] | type[BTSAirportReference]:
    if dataset_identifier == CARRIER_DECODE_DATASET:
        return BTSCarrierReference
    if dataset_identifier == MASTER_COORDINATE_DATASET:
        return BTSAirportReference
    raise ValueError(f"Unsupported BTS reference dataset: {dataset_identifier}")


def _nullable_source_text(value: str) -> str | None:
    """Map blank optional values to SQL NULL while preserving raw JSON values."""
    return value if value != "" else None


def _map_source_row(
    row: BTSReferenceCSVRow, release_id: UUID
) -> dict[str, object]:
    source = dict(row.source_values)
    common: dict[str, object] = {
        "release_id": release_id,
        "row_fingerprint": row.fingerprint,
        "source_values": row.source_values,
    }

    if row.dataset_identifier == CARRIER_DECODE_DATASET:
        dot_carrier_id = source["AIRLINE_ID"]
        if not dot_carrier_id:
            raise BTSReferenceImportError("AIRLINE_ID is required but blank.")
        return {
            **common,
            "dot_carrier_id": dot_carrier_id,
            "carrier_code": _nullable_source_text(source["CARRIER"]),
            "carrier_code_namespace": "IATA_CARRIER_CODE",
            "unique_carrier_code": _nullable_source_text(
                source["UNIQUE_CARRIER"]
            ),
            "carrier_name": _nullable_source_text(source["CARRIER_NAME"]),
            # START_DATE_SOURCE / THRU_DATE_SOURCE remain raw-only until their
            # export aliases are authoritatively mapped.
            "valid_from": None,
            "valid_to": None,
            "airline_code": None,
        }

    if row.dataset_identifier == MASTER_COORDINATE_DATASET:
        dot_airport_id = source["AIRPORT_ID"]
        dot_airport_seq_id = source["AIRPORT_SEQ_ID"]
        if not dot_airport_id or not dot_airport_seq_id:
            raise BTSReferenceImportError(
                "AIRPORT_ID and AIRPORT_SEQ_ID are required but one is blank."
            )
        return {
            **common,
            "dot_airport_id": dot_airport_id,
            "dot_airport_seq_id": dot_airport_seq_id,
            "bts_airport_code": _nullable_source_text(source["AIRPORT"]),
            "airport_code_namespace": "BTS_DOT_AIRPORT_CODE",
            # Display-name and validity aliases remain raw-only.
            "airport_name": None,
            "valid_from": None,
            "valid_to": None,
            "airport_id": None,
        }

    raise ValueError(f"Unsupported BTS reference dataset: {row.dataset_identifier}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified_member(
    source_zip: Path, dataset_identifier: str, expected_sha256: str, target: Path
) -> None:
    if _sha256_file(source_zip) != expected_sha256:
        raise BTSReferenceImportError("Source ZIP changed after successful preflight.")

    expected_member = EXPECTED_CSV_MEMBER[dataset_identifier]
    try:
        with zipfile.ZipFile(source_zip, "r") as archive:
            csv_members = [
                entry
                for entry in archive.infolist()
                if entry.filename.lower().endswith(".csv")
            ]
            if len(csv_members) != 1 or csv_members[0].filename != expected_member:
                raise BTSReferenceImportError(
                    f"Expected only CSV member {expected_member}; found "
                    f"{tuple(entry.filename for entry in csv_members)!r}."
                )
            bad_member = archive.testzip()
            if bad_member is not None:
                raise BTSReferenceImportError(f"ZIP CRC check failed for {bad_member}.")
            with archive.open(csv_members[0], "r") as member_stream:
                with target.open("wb") as output:
                    shutil.copyfileobj(member_stream, output, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error) as error:
        raise BTSReferenceImportError(f"Unable to read verified ZIP member: {error}") from error


def _verify_archive_unchanged(
    source_zip: Path, dataset_identifier: str, expected_sha256: str
) -> None:
    if _sha256_file(source_zip) != expected_sha256:
        raise BTSReferenceImportError("Source ZIP changed during import.")
    expected_member = EXPECTED_CSV_MEMBER[dataset_identifier]
    try:
        with zipfile.ZipFile(source_zip, "r") as archive:
            csv_members = [
                entry
                for entry in archive.infolist()
                if entry.filename.lower().endswith(".csv")
            ]
            if len(csv_members) != 1 or csv_members[0].filename != expected_member:
                raise BTSReferenceImportError("Source ZIP member list changed during import.")
            bad_member = archive.testzip()
            if bad_member is not None:
                raise BTSReferenceImportError(f"ZIP CRC check failed for {bad_member}.")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error) as error:
        raise BTSReferenceImportError(f"ZIP revalidation failed: {error}") from error


def _record_failed_release(
    store: _ImportStore,
    dataset_identifier: str,
    checksum: str,
) -> None:
    with store.transaction():
        release = store.find_release(
            SOURCE_AGENCY, dataset_identifier, checksum
        )
        if release is None:
            release = BTSReferenceRelease(
                source_agency=SOURCE_AGENCY,
                dataset_name=dataset_identifier,
                source_artifact_sha256=checksum,
                fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
                status="failed",
                completed_at=None,
            )
            store.add_release(release)
        elif release.status is None or release.status == "complete":
            # Preserve legacy unknown releases and never downgrade completion.
            return
        else:
            release.status = "failed"
            release.completed_at = None
            store.flush()


def _import_with_store(
    store: _ImportStore,
    source_zip: str | Path,
    dataset_identifier: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> BTSReferenceImportReport:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    model = _model_for_dataset(dataset_identifier)
    zip_path = Path(source_zip)
    preflight = preflight_reference_zip(zip_path, dataset_identifier)
    if not preflight.dry_run_ready or preflight.zip_sha256 is None:
        raise BTSReferencePreflightRejected(preflight)

    try:
        with tempfile.TemporaryDirectory(prefix="flightpulse-bts-import-") as temp_dir:
            csv_path = Path(temp_dir) / "source.csv"
            _copy_verified_member(
                zip_path,
                dataset_identifier,
                preflight.zip_sha256,
                csv_path,
            )

            with store.transaction():
                release = store.find_release(
                    SOURCE_AGENCY,
                    dataset_identifier,
                    preflight.zip_sha256,
                )
                if release is not None and release.status == "complete":
                    row_count = store.count_rows(model, release.id)
                    if (
                        release.fingerprint_schema_version
                        != FINGERPRINT_SCHEMA_VERSION
                        or row_count != preflight.unique_fingerprints
                    ):
                        raise BTSCompletedReleaseMismatch(
                            "Completed release version or row count does not match "
                            "the verified source; it was left unchanged."
                        )
                    seen: set[str] = set()
                    parsed_rows = 0
                    duplicate_occurrences = 0
                    pending: list[dict[str, object]] = []

                    def verify_complete_batch() -> None:
                        if not pending:
                            return
                        stored = store.get_rows(
                            model,
                            release.id,
                            [str(row["row_fingerprint"]) for row in pending],
                        )
                        for source_row in pending:
                            fingerprint = str(source_row["row_fingerprint"])
                            if (
                                fingerprint not in stored
                                or stored[fingerprint] != source_row["source_values"]
                            ):
                                raise BTSCompletedReleaseMismatch(
                                    "Completed release rows do not match the source; "
                                    "the release was left unchanged."
                                )
                        pending.clear()

                    for row in iter_reference_csv(csv_path, dataset_identifier):
                        parsed_rows += 1
                        if row.fingerprint in seen:
                            duplicate_occurrences += 1
                            continue
                        seen.add(row.fingerprint)
                        pending.append(_map_source_row(row, release.id))
                        if len(pending) >= batch_size:
                            verify_complete_batch()
                    verify_complete_batch()
                    if (
                        parsed_rows != preflight.parsed_rows
                        or len(seen) != preflight.unique_fingerprints
                        or duplicate_occurrences != preflight.duplicate_occurrences
                    ):
                        raise BTSCompletedReleaseMismatch(
                            "Completed release row counts differ from preflight; "
                            "the release was left unchanged."
                        )
                    _verify_archive_unchanged(
                        zip_path, dataset_identifier, preflight.zip_sha256
                    )
                    return BTSReferenceImportReport(
                        dataset_identifier=dataset_identifier,
                        release_id=release.id,
                        source_artifact_sha256=preflight.zip_sha256,
                        status="complete",
                        parsed_rows=preflight.parsed_rows,
                        unique_fingerprints=preflight.unique_fingerprints,
                        duplicate_occurrences=preflight.duplicate_occurrences,
                        inserted_rows=0,
                        existing_rows=row_count,
                        already_complete=True,
                    )

                if release is None:
                    release = BTSReferenceRelease(
                        source_agency=SOURCE_AGENCY,
                        dataset_name=dataset_identifier,
                        source_artifact_sha256=preflight.zip_sha256,
                        fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
                        status="pending",
                        completed_at=None,
                    )
                    store.add_release(release)
                elif release.status is None or not release.fingerprint_schema_version:
                    raise BTSLegacyReleaseNeedsReview(
                        "Existing legacy release lacks explicit lifecycle or "
                        "fingerprint-version metadata; manual review is required."
                    )
                elif release.fingerprint_schema_version != FINGERPRINT_SCHEMA_VERSION:
                    raise BTSLegacyReleaseNeedsReview(
                        "Existing release uses a different fingerprint schema version."
                    )
                elif release.status not in {"pending", "failed"}:
                    raise BTSLegacyReleaseNeedsReview(
                        f"Unsupported existing release state: {release.status!r}."
                    )
                else:
                    release.status = "pending"
                    release.completed_at = None
                    store.flush()

                if release.id is None:
                    raise BTSReferenceImportError("Release primary key was not assigned.")

                seen_fingerprints: set[str] = set()
                pending_rows: list[dict[str, object]] = []
                parsed_rows = 0
                duplicate_occurrences = 0
                inserted_rows = 0
                existing_rows = 0

                def flush_batch() -> None:
                    nonlocal inserted_rows, existing_rows
                    if not pending_rows:
                        return
                    inserted, stored_values = store.insert_batch(model, pending_rows)
                    for values in pending_rows:
                        fingerprint = str(values["row_fingerprint"])
                        if fingerprint not in stored_values:
                            raise BTSReferenceImportError(
                                f"Fingerprint {fingerprint} was not persisted."
                            )
                        if stored_values[fingerprint] != values["source_values"]:
                            raise BTSReferenceImportError(
                                "Existing fingerprint has different raw source values."
                            )
                        if fingerprint in inserted:
                            inserted_rows += 1
                        else:
                            existing_rows += 1
                    pending_rows.clear()

                for row in iter_reference_csv(csv_path, dataset_identifier):
                    parsed_rows += 1
                    if row.fingerprint in seen_fingerprints:
                        duplicate_occurrences += 1
                        continue
                    seen_fingerprints.add(row.fingerprint)
                    pending_rows.append(_map_source_row(row, release.id))
                    if len(pending_rows) >= batch_size:
                        flush_batch()
                flush_batch()

                unique_fingerprints = len(seen_fingerprints)
                if (
                    parsed_rows != preflight.parsed_rows
                    or unique_fingerprints != preflight.unique_fingerprints
                    or duplicate_occurrences != preflight.duplicate_occurrences
                    or parsed_rows != unique_fingerprints + duplicate_occurrences
                ):
                    raise BTSReferenceImportError(
                        "Import row counts do not reconcile with the successful "
                        "preflight report."
                    )

                _verify_archive_unchanged(
                    zip_path, dataset_identifier, preflight.zip_sha256
                )
                row_count = store.count_rows(model, release.id)
                if row_count != unique_fingerprints:
                    raise BTSReferenceImportError(
                        f"Release has {row_count} stored rows; expected "
                        f"{unique_fingerprints}."
                    )

                release.status = "complete"
                release.completed_at = datetime.now(UTC)
                store.flush()

            return BTSReferenceImportReport(
                dataset_identifier=dataset_identifier,
                release_id=release.id,
                source_artifact_sha256=preflight.zip_sha256,
                status="complete",
                parsed_rows=parsed_rows,
                unique_fingerprints=unique_fingerprints,
                duplicate_occurrences=duplicate_occurrences,
                inserted_rows=inserted_rows,
                existing_rows=existing_rows,
            )
    except (BTSLegacyReleaseNeedsReview, BTSCompletedReleaseMismatch):
        raise
    except Exception as error:
        try:
            _record_failed_release(
                store, dataset_identifier, preflight.zip_sha256
            )
        except Exception as lifecycle_error:
            raise BTSReferenceImportError(
                "Import transaction rolled back, but failed status could not be "
                f"recorded: {lifecycle_error}"
            ) from error
        raise


def import_reference_zip(
    session: Session,
    source_zip: str | Path,
    dataset_identifier: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> BTSReferenceImportReport:
    """Import exactly one verified BTS dataset in a release-scoped transaction.

    Use a fresh session with no active transaction. Run once per dataset; each
    release commits or rolls back independently. No canonical airport/airline
    link or unresolved validity alias is inferred.
    """
    if session.in_transaction():
        raise BTSReferenceImportError(
            "Use a fresh SQLAlchemy session with no active transaction."
        )
    return _import_with_store(
        _SQLAlchemyImportStore(session),
        source_zip,
        dataset_identifier,
        batch_size=batch_size,
    )
