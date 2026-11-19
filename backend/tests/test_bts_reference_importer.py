"""Focused transactional BTS reference-import tests without a database."""

import csv
import hashlib
import io
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
import zipfile

import pytest

import backend.app.data_ingestion.bts_reference_preflight as preflight_module
from backend.app.data_ingestion.bts_reference_csv import (
    CARRIER_DECODE_DATASET,
    CARRIER_DECODE_HEADERS,
    MASTER_COORDINATE_DATASET,
    MASTER_COORDINATE_HEADERS,
)
from backend.app.data_ingestion.bts_reference_importer import (
    _import_with_store,
)
from backend.app.database.models.bts_reference import (
    BTSCarrierReference,
)


def _csv_bytes(headers, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _write_zip(path, member_name, content):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, checksum


def _carrier_row(**overrides):
    values = [""] * len(CARRIER_DECODE_HEADERS)
    defaults = {
        "AIRLINE_ID": "00019031",
        "CARRIER": "MAC",
        "CARRIER_ENTITY": "030550",
        "CARRIER_NAME": "Mackey International Inc.",
        "UNIQUE_CARRIER": "MAC",
        "UNIQUE_CARRIER_ENTITY": "030550",
        "UNIQUE_CARRIER_NAME": "Mackey International Inc.",
        "REGION": "Domestic",
        "START_DATE_SOURCE": "1/1/1960 12:00:00 AM",
        "THRU_DATE_SOURCE": "",
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        values[CARRIER_DECODE_HEADERS.index(name)] = value
    return values


def _airport_row(**overrides):
    values = [""] * len(MASTER_COORDINATE_HEADERS)
    defaults = {
        "AIRPORT_SEQ_ID": "01000101",
        "AIRPORT_ID": "0010001",
        "AIRPORT": "01A",
        "DISPLAY_AIRPORT_NAME": "Afognak Lake Airport",
        "AIRPORT_START_DATE": "7/1/2007 12:00:00 AM",
        "AIRPORT_THRU_DATE": "",
        "AIRPORT_IS_CLOSED": "0",
        "AIRPORT_IS_LATEST": "1",
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        values[MASTER_COORDINATE_HEADERS.index(name)] = value
    return values


class _MemoryStore:
    """Transaction-aware store fake exercising the importer orchestration."""

    def __init__(self, *, fail_on_batch_call=None):
        self.releases = {}
        self.rows = {}
        self.fail_on_batch_call = fail_on_batch_call
        self.batch_calls = 0
        self.initial_statuses = []

    @contextmanager
    def transaction(self):
        original_releases = dict(self.releases)
        release_attributes = {
            id(release): (
                release,
                release.status,
                release.completed_at,
                release.fingerprint_schema_version,
            )
            for release in self.releases.values()
        }
        original_rows = {key: dict(value) for key, value in self.rows.items()}
        try:
            yield
        except Exception:
            self.releases = original_releases
            self.rows = original_rows
            for release, status, completed_at, version in release_attributes.values():
                release.status = status
                release.completed_at = completed_at
                release.fingerprint_schema_version = version
            raise

    def find_release(self, source_agency, dataset_name, checksum):
        return self.releases.get((source_agency, dataset_name, checksum))

    def add_release(self, release):
        if release.id is None:
            release.id = uuid4()
        key = (
            release.source_agency,
            release.dataset_name,
            release.source_artifact_sha256,
        )
        self.releases[key] = release
        self.initial_statuses.append(release.status)

    def insert_batch(self, model, rows):
        self.batch_calls += 1
        if self.batch_calls == self.fail_on_batch_call:
            raise RuntimeError("simulated batch insertion failure")
        table_name = model.__tablename__
        inserted = set()
        for row in rows:
            key = (table_name, row["release_id"], row["row_fingerprint"])
            if key not in self.rows:
                self.rows[key] = dict(row)
                inserted.add(row["row_fingerprint"])
        stored = {
            fingerprint: self.rows[(table_name, rows[0]["release_id"], fingerprint)][
                "source_values"
            ]
            for fingerprint in (row["row_fingerprint"] for row in rows)
            if (table_name, rows[0]["release_id"], fingerprint) in self.rows
        }
        return inserted, stored

    def get_rows(self, model, release_id, fingerprints):
        table_name = model.__tablename__
        return {
            fingerprint: self.rows[(table_name, release_id, fingerprint)][
                "source_values"
            ]
            for fingerprint in fingerprints
            if (table_name, release_id, fingerprint) in self.rows
        }

    def count_rows(self, model, release_id):
        return sum(
            1
            for table_name, row_release_id, _ in self.rows
            if table_name == model.__tablename__ and row_release_id == release_id
        )

    def flush(self):
        pass


def _prepare_carrier_zip(tmp_path, monkeypatch, rows, name="carrier.zip"):
    path, checksum = _write_zip(
        tmp_path / name,
        "T_CARRIER_DECODE.csv",
        _csv_bytes(CARRIER_DECODE_HEADERS, rows),
    )
    monkeypatch.setitem(
        preflight_module.EXPECTED_ZIP_SHA256, CARRIER_DECODE_DATASET, checksum
    )
    return path, checksum


def _prepare_airport_zip(tmp_path, monkeypatch, rows, name="airport.zip"):
    path, checksum = _write_zip(
        tmp_path / name,
        "T_MASTER_CORD.csv",
        _csv_bytes(MASTER_COORDINATE_HEADERS, rows),
    )
    monkeypatch.setitem(
        preflight_module.EXPECTED_ZIP_SHA256, MASTER_COORDINATE_DATASET, checksum
    )
    return path, checksum


def test_successful_import_preserves_raw_values_and_release_lifecycle(
    tmp_path, monkeypatch
):
    path, _ = _prepare_carrier_zip(tmp_path, monkeypatch, [_carrier_row()])
    store = _MemoryStore()

    report = _import_with_store(store, path, CARRIER_DECODE_DATASET, batch_size=1)

    release = next(iter(store.releases.values()))
    stored = next(iter(store.rows.values()))
    assert store.initial_statuses == ["pending"]
    assert report.status == release.status == "complete"
    assert isinstance(release.completed_at, datetime)
    assert report.inserted_rows == 1
    assert report.existing_rows == 0
    assert stored["dot_carrier_id"] == "00019031"
    assert stored["carrier_code"] == "MAC"
    assert stored["unique_carrier_code"] == "MAC"
    assert stored["valid_from"] is None
    assert stored["valid_to"] is None
    assert [pair[0] for pair in stored["source_values"]] == list(
        CARRIER_DECODE_HEADERS
    )
    assert stored["source_values"][-1] == ["THRU_DATE_SOURCE", ""]


def test_completed_release_retry_is_idempotent(tmp_path, monkeypatch):
    path, _ = _prepare_carrier_zip(tmp_path, monkeypatch, [_carrier_row()])
    store = _MemoryStore()

    first = _import_with_store(store, path, CARRIER_DECODE_DATASET)
    second = _import_with_store(store, path, CARRIER_DECODE_DATASET)

    assert first.inserted_rows == 1
    assert second.already_complete is True
    assert second.inserted_rows == 0
    assert second.existing_rows == 1
    assert len(store.rows) == 1
    assert len(store.releases) == 1


def test_exact_duplicate_source_rows_are_protected_by_fingerprint(
    tmp_path, monkeypatch
):
    row = _carrier_row()
    path, _ = _prepare_carrier_zip(tmp_path, monkeypatch, [row, row])
    store = _MemoryStore()

    report = _import_with_store(store, path, CARRIER_DECODE_DATASET)

    assert report.parsed_rows == 2
    assert report.unique_fingerprints == 1
    assert report.duplicate_occurrences == 1
    assert report.inserted_rows == 1
    assert len(store.rows) == 1


def test_batch_failure_rolls_back_rows_and_records_failed_release(
    tmp_path, monkeypatch
):
    rows = [
        _carrier_row(CARRIER_ENTITY="030550"),
        _carrier_row(CARRIER_ENTITY="030551", REGION="International"),
    ]
    path, _ = _prepare_carrier_zip(tmp_path, monkeypatch, rows)
    store = _MemoryStore(fail_on_batch_call=2)

    with pytest.raises(RuntimeError, match="simulated batch insertion failure"):
        _import_with_store(store, path, CARRIER_DECODE_DATASET, batch_size=1)

    release = next(iter(store.releases.values()))
    assert release.status == "failed"
    assert release.completed_at is None
    assert store.count_rows(BTSCarrierReference, release.id) == 0


def test_failed_release_can_be_retried_to_completion(tmp_path, monkeypatch):
    rows = [
        _carrier_row(CARRIER_ENTITY="030550"),
        _carrier_row(CARRIER_ENTITY="030551", REGION="International"),
    ]
    path, _ = _prepare_carrier_zip(tmp_path, monkeypatch, rows)
    store = _MemoryStore(fail_on_batch_call=2)

    with pytest.raises(RuntimeError, match="simulated batch insertion failure"):
        _import_with_store(store, path, CARRIER_DECODE_DATASET, batch_size=1)
    store.fail_on_batch_call = None

    report = _import_with_store(
        store, path, CARRIER_DECODE_DATASET, batch_size=1
    )

    release = next(iter(store.releases.values()))
    assert release.status == report.status == "complete"
    assert release.completed_at is not None
    assert report.inserted_rows == 2
    assert store.count_rows(BTSCarrierReference, release.id) == 2


def test_historical_carrier_entities_and_airport_versions_are_not_collapsed(
    tmp_path, monkeypatch
):
    carrier_rows = [
        _carrier_row(CARRIER_ENTITY="030550", REGION="Domestic"),
        _carrier_row(CARRIER_ENTITY="130550", REGION="International"),
    ]
    carrier_path, _ = _prepare_carrier_zip(
        tmp_path, monkeypatch, carrier_rows, "carrier-versions.zip"
    )
    carrier_store = _MemoryStore()

    carrier_report = _import_with_store(
        carrier_store, carrier_path, CARRIER_DECODE_DATASET
    )

    assert carrier_report.unique_fingerprints == 2
    assert carrier_report.inserted_rows == 2
    assert carrier_store.count_rows(
        BTSCarrierReference, carrier_report.release_id
    ) == 2

    airport_rows = [
        _airport_row(AIRPORT_SEQ_ID="01000101", AIRPORT_START_DATE="1/1/2000"),
        _airport_row(
            AIRPORT_SEQ_ID="01000102",
            AIRPORT_START_DATE="1/1/2010",
            AIRPORT_THRU_DATE="",
            AIRPORT_IS_LATEST="1",
        ),
    ]
    airport_path, _ = _prepare_airport_zip(
        tmp_path, monkeypatch, airport_rows, "airport-versions.zip"
    )
    airport_store = _MemoryStore()

    airport_report = _import_with_store(
        airport_store, airport_path, MASTER_COORDINATE_DATASET
    )

    airport_records = list(airport_store.rows.values())
    assert airport_report.unique_fingerprints == 2
    assert airport_report.inserted_rows == 2
    assert {record["dot_airport_id"] for record in airport_records} == {"0010001"}
    assert {record["dot_airport_seq_id"] for record in airport_records} == {
        "01000101",
        "01000102",
    }
    assert all(record["valid_from"] is None for record in airport_records)
    assert all(record["valid_to"] is None for record in airport_records)
    assert all(record["airport_name"] is None for record in airport_records)
