"""Reproducible BTS January 2024 download, validation, and processing CLI."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.config.settings import get_settings
from pipelines.ingestion.data_cleaning import clean_dataframe, read_csv_chunks
from pipelines.ingestion.data_validation import (
    ExactDuplicateTracker,
    sha256_file,
    validate_csv,
    write_provenance,
    write_quality_report,
)
from pipelines.ingestion.exploratory_analysis import EDAAccumulator


DATASET_NAME = "BTS On-Time Reporting Carrier On-Time Performance"
ARCHIVE_NAME = (
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_1.zip"
)
CSV_NAME = ARCHIVE_NAME.removesuffix(".zip") + ".csv"
SOURCE_URL = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_1.zip"
)
MANUAL_SOURCE_URL = "https://www.transtats.bts.gov/"
CHUNK_SIZE_BYTES = 1024 * 1024
DOWNLOAD_MAX_ATTEMPTS = 5
DOWNLOAD_RETRY_BACKOFF_SECONDS = 1
EXPECTED_ARCHIVE_CSV = (
    "On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2024_1.csv"
)
DEFAULT_CHUNK_ROWS = 50_000
REPORT_PATH = Path("docs/data_quality_report.md")
PROCESSED_NAME = "bts_ontime_2024_01.parquet"
EDA_RELATIVE_PATH = Path("reports/eda/2024-01")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_bts_archive(
    archive_path: Path,
    expected_csv: str = EXPECTED_ARCHIVE_CSV,
) -> None:
    """Verify ZIP CRCs and the unique expected BTS CSV member."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member:
                raise ValueError(f"ZIP member failed its CRC check: {corrupt_member}")
            csv_members = [
                member.filename
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".csv")
            ]
            if csv_members != [expected_csv]:
                raise ValueError(
                    f"Expected exactly the BTS CSV member {expected_csv!r}; "
                    f"found {csv_members!r}."
                )
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid or incomplete ZIP archive: {exc}") from exc


def _download_metadata_path(partial: Path) -> Path:
    return partial.with_name(partial.name + ".json")


def _read_download_metadata(
    partial: Path,
) -> tuple[str | None, str | None, int | None]:
    """Read validators and total size saved for a partial download."""
    metadata_path = _download_metadata_path(partial)
    if not metadata_path.exists():
        return None, None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        etag = metadata.get("etag")
        last_modified = metadata.get("last_modified")
        total_size = metadata.get("total_size")
        if etag is not None and not isinstance(etag, str):
            raise ValueError("ETag must be a string or null.")
        if last_modified is not None and not isinstance(last_modified, str):
            raise ValueError("last_modified must be a string or null.")
        if total_size is not None and (
            not isinstance(total_size, int)
            or isinstance(total_size, bool)
            or total_size < 0
        ):
            raise ValueError("total_size must be a non-negative integer or null.")
        return etag, last_modified, total_size
    except (OSError, json.JSONDecodeError, AttributeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid resume metadata at {metadata_path}; refusing to resume: {exc}"
        ) from exc


def _write_download_metadata(
    partial: Path,
    etag: str | None,
    total_size: int | None,
    last_modified: str | None = None,
) -> None:
    """Atomically persist download validators next to the partial archive."""
    metadata_path = _download_metadata_path(partial)
    temporary_path = metadata_path.with_name(metadata_path.name + ".tmp")
    temporary_path.write_text(
        json.dumps(
            {
                "etag": etag,
                "last_modified": last_modified,
                "total_size": total_size,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(metadata_path)


def _backup_unverified_partial(partial: Path) -> Path:
    """Move a partial without reliable validators aside without overwriting it."""
    backup = partial.with_name(partial.name + ".unverified")
    suffix = 1
    while backup.exists():
        backup = partial.with_name(f"{partial.name}.unverified.{suffix}")
        suffix += 1
    partial.replace(backup)
    return backup


def _replace_partial_from_staged(
    partial: Path, staged: Path, append_offset: int | None
) -> None:
    """Atomically add a validated response, preserving the previous partial."""
    assembled = partial.with_name(partial.name + ".assembled")
    try:
        with assembled.open("wb") as output:
            if append_offset is not None:
                with partial.open("rb") as source:
                    shutil.copyfileobj(source, output, length=CHUNK_SIZE_BYTES)
            with staged.open("rb") as source:
                shutil.copyfileobj(source, output, length=CHUNK_SIZE_BYTES)
            output.flush()
            os.fsync(output.fileno())
        assembled.replace(partial)
    except OSError:
        assembled.unlink(missing_ok=True)
        raise


def download_archive(
    destination: Path,
    timeout: int = 60,
    source_url: str = SOURCE_URL,
    expected_csv: str = EXPECTED_ARCHIVE_CSV,
) -> Path:
    """Download BTS data with validated, ETag-protected resumable requests."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            _validate_bts_archive(destination, expected_csv)
        except ValueError as exc:
            raise RuntimeError(
                f"Refusing to overwrite existing invalid archive {destination}: {exc}"
            ) from exc
        return destination

    partial = destination.with_name(destination.name + ".part")
    staged = partial.with_name(partial.name + ".response")
    force_full = False
    restarts = 0
    attempts = 0

    if partial.exists():
        metadata_path = _download_metadata_path(partial)
        if not metadata_path.exists():
            backup = _backup_unverified_partial(partial)
            print(
                f"Preserved partial without download metadata at {backup}; "
                "starting a fresh download."
            )
        else:
            etag, last_modified, _ = _read_download_metadata(partial)
            if not (etag or last_modified):
                backup = _backup_unverified_partial(partial)
                metadata_path.unlink(missing_ok=True)
                print(
                    f"Preserved partial without a reliable validator at {backup}; "
                    "starting a fresh download."
                )

    while attempts < DOWNLOAD_MAX_ATTEMPTS:
        attempts += 1
        stored_etag, stored_last_modified, stored_total = (
            _read_download_metadata(partial)
            if partial.exists()
            else (None, None, None)
        )
        if (
            partial.exists()
            and partial.stat().st_size
            and not force_full
            and not (stored_etag or stored_last_modified)
        ):
            backup = _backup_unverified_partial(partial)
            _download_metadata_path(partial).unlink(missing_ok=True)
            print(
                f"Preserved partial without a reliable validator at {backup}; "
                "restarting safely."
            )
            stored_total = None
        offset = partial.stat().st_size if partial.exists() and not force_full else 0
        resulting_total: int | None = None
        headers = {
            "User-Agent": "FlightPulse-Live/0.1 (BTS historical data ingestion)",
            "Accept-Encoding": "identity",
        }
        if offset:
            headers["Range"] = f"bytes={offset}-"
            if stored_etag:
                headers["If-Range"] = stored_etag
            elif stored_last_modified:
                headers["If-Range"] = stored_last_modified
        request = urllib.request.Request(source_url, headers=headers)
        restart = False
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", response.getcode())
                response_etag = response.headers.get("ETag")
                response_last_modified = response.headers.get("Last-Modified")
                content_encoding = response.headers.get("Content-Encoding", "identity")
                if content_encoding.strip().lower() not in ("", "identity"):
                    raise RuntimeError(
                        "BTS returned encoded content despite Accept-Encoding: identity "
                        f"({content_encoding!r}); existing partial retained."
                    )
                append_offset: int | None
                expected_length: int | None

                if status == 206:
                    if not offset:
                        raise RuntimeError(
                            "BTS returned partial content without a requested range."
                        )
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)",
                        response.headers.get("Content-Range", "").strip(),
                    )
                    if not match:
                        raise RuntimeError(
                            "Malformed BTS Content-Range; existing partial retained."
                        )
                    start, end, total = map(int, match.groups())
                    if start != offset or end < start or end >= total:
                        raise RuntimeError(
                            "Inconsistent BTS Content-Range "
                            f"(expected start {offset}, got {start}-{end}/{total}); "
                            "existing partial retained."
                        )
                    if stored_total is not None and stored_total != total:
                        restart = True
                    if stored_etag is not None and stored_etag != response_etag:
                        restart = True
                    if (
                        stored_etag is None
                        and stored_last_modified is not None
                        and stored_last_modified != response_last_modified
                    ):
                        restart = True
                    if restart:
                        if restarts:
                            raise RuntimeError(
                                "BTS archive validators changed repeatedly; "
                                "existing partial retained."
                            )
                        restarts += 1
                        force_full = True
                        continue
                    expected_length = end - start + 1
                    append_offset = offset
                    content_length = response.headers.get("Content-Length")
                    if content_length is not None:
                        try:
                            if int(content_length) != expected_length:
                                raise RuntimeError(
                                    "BTS Content-Length does not match Content-Range; "
                                    "existing partial retained."
                                )
                        except ValueError as exc:
                            raise RuntimeError("Invalid BTS Content-Length.") from exc
                    resulting_total = total
                    persisted_etag = response_etag or stored_etag
                    persisted_last_modified = (
                        response_last_modified or stored_last_modified
                    )
                elif status == 200:
                    append_offset = None
                    content_length = response.headers.get("Content-Length")
                    try:
                        expected_length = (
                            int(content_length) if content_length is not None else None
                        )
                    except ValueError as exc:
                        raise RuntimeError("Invalid BTS Content-Length.") from exc
                    resulting_total = expected_length
                    persisted_etag = response_etag
                    persisted_last_modified = response_last_modified
                    force_full = False
                else:
                    raise RuntimeError(
                        f"Unexpected BTS download response HTTP {status}; "
                        "existing partial retained."
                    )

                received = 0
                try:
                    with staged.open("wb") as output:
                        while True:
                            block = response.read(CHUNK_SIZE_BYTES)
                            if not block:
                                break
                            received += len(block)
                            if expected_length is not None and received > expected_length:
                                raise RuntimeError(
                                    "BTS response body exceeded its declared range; "
                                    "existing partial retained."
                                )
                            output.write(block)
                        output.flush()
                        os.fsync(output.fileno())
                except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                    if received:
                        _replace_partial_from_staged(partial, staged, append_offset)
                        _write_download_metadata(
                            partial,
                            persisted_etag,
                            resulting_total,
                            persisted_last_modified,
                        )
                    raise exc

                if expected_length is not None and received != expected_length:
                    if received:
                        _replace_partial_from_staged(partial, staged, append_offset)
                        _write_download_metadata(
                            partial,
                            persisted_etag,
                            resulting_total,
                            persisted_last_modified,
                        )
                    raise RuntimeError(
                        f"BTS body length mismatch ({received} of {expected_length}); "
                        "verified contiguous bytes retained for retry."
                    )
                _replace_partial_from_staged(partial, staged, append_offset)
                _write_download_metadata(
                    partial,
                    persisted_etag,
                    resulting_total,
                    persisted_last_modified,
                )
        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600:
                if attempts >= DOWNLOAD_MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"BTS server returned HTTP {exc.code} after "
                        f"{attempts} attempts; partial retained at {partial}."
                    ) from exc
                time.sleep(
                    DOWNLOAD_RETRY_BACKOFF_SECONDS * (2 ** (attempts - 1))
                )
                continue
            if exc.code != 416 or not partial.exists():
                raise RuntimeError(
                    f"Unable to download BTS archive: HTTP {exc.code}; "
                    "existing partial retained."
                ) from exc
            range_header = (
                exc.headers.get("Content-Range", "") if exc.headers else ""
            ).strip()
            match = re.fullmatch(r"bytes \*/(\d+)", range_header)
            reported_total = int(match.group(1)) if match else None
            if (
                reported_total is not None
                and partial.stat().st_size == reported_total
                and (stored_total is None or stored_total == reported_total)
            ):
                try:
                    _validate_bts_archive(partial, expected_csv)
                except ValueError:
                    pass
                else:
                    partial.replace(destination)
                    _download_metadata_path(partial).unlink(missing_ok=True)
                    return destination
            if restarts:
                raise RuntimeError(
                    "BTS returned 416 and the partial failed total-size or archive "
                    f"integrity checks; partial retained at {partial}."
                ) from exc
            restarts += 1
            force_full = True
            attempts -= 1
            continue
        except (
            urllib.error.URLError,
            OSError,
            http.client.HTTPException,
            RuntimeError,
        ) as exc:
            if attempts >= DOWNLOAD_MAX_ATTEMPTS:
                raise RuntimeError(
                    f"BTS download failed after {attempts} attempts: {exc}. "
                    f"Verified bytes, if any, remain resumable at {partial}."
                ) from exc
            if isinstance(exc, RuntimeError) and (
                "Content-Range" in str(exc)
                or "validator" in str(exc)
                or "encoded content" in str(exc)
                or "Content-Length" in str(exc)
            ):
                raise
            delay = DOWNLOAD_RETRY_BACKOFF_SECONDS * (2 ** (attempts - 1))
            time.sleep(delay)
            continue
        finally:
            staged.unlink(missing_ok=True)

        if restart:
            continue
        if resulting_total is not None and partial.stat().st_size > resulting_total:
            raise RuntimeError(
                f"Partial file exceeds BTS archive size; retained at {partial}."
            )
        if resulting_total is not None and partial.stat().st_size < resulting_total:
            if attempts < DOWNLOAD_MAX_ATTEMPTS:
                time.sleep(DOWNLOAD_RETRY_BACKOFF_SECONDS * (2 ** (attempts - 1)))
                force_full = False
                continue
            raise RuntimeError(
                f"BTS response ended before the complete archive size "
                f"({partial.stat().st_size} of {resulting_total or 'unknown'} bytes); "
                f"verified partial retained at {partial}."
            )
        try:
            _validate_bts_archive(partial, expected_csv)
        except ValueError as exc:
            if restarts:
                raise RuntimeError(
                    f"Downloaded BTS archive failed validation; partial retained "
                    f"at {partial}: {exc}"
                ) from exc
            restarts += 1
            force_full = True
            attempts -= 1
            continue
        partial.replace(destination)
        _download_metadata_path(partial).unlink(missing_ok=True)
        return destination

    raise RuntimeError(
        f"BTS download did not complete after {DOWNLOAD_MAX_ATTEMPTS} attempts; "
        f"verified partial retained at {partial}."
    )


def extract_bts_csv(
    archive_path: Path,
    raw_directory: Path,
    expected_csv: str = EXPECTED_ARCHIVE_CSV,
    target_path: Path | None = None,
) -> Path:
    """Extract only the archive's CSV member without modifying its ZIP source."""
    try:
        _validate_bts_archive(archive_path, expected_csv)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to extract invalid BTS archive: {exc}") from exc

    target = target_path or raw_directory / CSV_NAME
    if target.exists():
        provenance_path = target.with_name(target.name + ".provenance.json")
        if provenance_path.exists():
            try:
                existing_provenance = json.loads(
                    provenance_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                existing_provenance = {}
            if (
                existing_provenance.get("acquisition_method")
                == "official BTS PREZIP archive download"
                and existing_provenance.get("raw_csv_sha256") == sha256_file(target)
            ):
                return target
        raise FileExistsError(
            f"Refusing to replace existing raw CSV without verified BTS provenance: "
            f"{target}"
        )

    raw_directory.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".csv")
            ]
            member_names = [member.filename for member in members]
            if member_names != [expected_csv]:
                raise ValueError(
                    f"Expected exactly the BTS CSV member {expected_csv!r}; "
                    f"found {member_names!r}."
                )
            selected = expected_csv
            partial = target.with_name(target.name + ".part")
            with archive.open(selected) as source, partial.open("wb") as output:
                shutil.copyfileobj(source, output, length=CHUNK_SIZE_BYTES)
                output.flush()
                os.fsync(output.fileno())
            partial.replace(target)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise RuntimeError(f"Unable to extract BTS CSV from {archive_path}: {exc}") from exc
    return target


def _save_download_provenance(csv_path: Path, archive_path: Path) -> Path:
    """Record official source, acquisition time, and content hashes."""
    provenance_path = csv_path.with_name(csv_path.name + ".provenance.json")
    if provenance_path.exists():
        return provenance_path
    archive_hash = sha256_file(archive_path)
    provenance = {
        "dataset": DATASET_NAME,
        "period": "2024-01",
        "source": "U.S. Department of Transportation, Bureau of Transportation Statistics",
        "source_url": SOURCE_URL,
        "acquisition_method": "official BTS PREZIP archive download",
        "download_date_utc": _utc_now(),
        "archive_file": archive_path.name,
        "archive_sha256": archive_hash,
        "raw_csv_file": csv_path.name,
        "raw_csv_sha256": sha256_file(csv_path),
    }
    write_provenance(provenance, provenance_path)
    return provenance_path


def download_bts_data(data_directory: Path) -> Path:
    """Download the official January 2024 BTS archive and preserve its CSV."""
    raw_directory = data_directory / "raw"
    archive_path = raw_directory / ARCHIVE_NAME
    downloaded_archive = download_archive(archive_path)
    csv_path = extract_bts_csv(downloaded_archive, raw_directory)
    provenance_path = _save_download_provenance(csv_path, downloaded_archive)
    print(f"Raw BTS CSV: {csv_path}")
    print(f"Provenance: {provenance_path}")
    return csv_path


def import_raw_csv(input_path: Path, data_directory: Path) -> Path:
    """Copy a user-supplied BTS CSV into raw storage without replacing files."""
    source = input_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input CSV does not exist: {source}")
    if source.suffix.lower() != ".csv":
        raise ValueError(f"Expected a .csv input file, got {source.name}")

    raw_directory = data_directory / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    target = raw_directory / source.name
    if source != target.resolve():
        if target.exists():
            if sha256_file(target) != sha256_file(source):
                raise FileExistsError(
                    f"Refusing to replace different raw input file: {target}"
                )
        else:
            shutil.copy2(source, target)

    provenance_path = target.with_name(target.name + ".provenance.json")
    if not provenance_path.exists():
        write_provenance(
            {
                "dataset": DATASET_NAME,
                "period": "2024-01",
                "source": "BTS TranStats (operator-supplied CSV; source not independently verified)",
                "source_url": MANUAL_SOURCE_URL,
                "acquisition_method": "manual CSV import",
                "download_date_utc": None,
                "imported_at_utc": _utc_now(),
                "raw_csv_file": target.name,
                "raw_csv_sha256": sha256_file(target),
            },
            provenance_path,
        )
    return target


def _expected_eda_files(directory: Path) -> set[Path]:
    return {
        directory / "overview.csv",
        directory / "airline_delays.csv",
        directory / "airport_delays.csv",
        directory / "route_delays.csv",
        directory / "hour_delays.csv",
        directory / "arrival_delay_distribution.csv",
        directory / "airline_delay_rates.png",
        directory / "airport_delay_rates.png",
        directory / "route_delay_rates.png",
        directory / "hourly_delay_rates.png",
        directory / "arrival_delay_distribution.png",
    }


def process_bts_csv(
    csv_path: Path,
    data_directory: Path,
    repository_root: Path,
    chunksize: int = DEFAULT_CHUNK_ROWS,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Validate, clean, write Parquet, and generate EDA from the raw CSV."""
    if chunksize < 1:
        raise ValueError("chunksize must be a positive integer.")
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if csv_path.suffix.lower() != ".csv":
        raise ValueError(f"Expected a .csv input file, got: {csv_path.name}")

    raw_path = import_raw_csv(csv_path, data_directory)
    provenance_path = raw_path.with_name(raw_path.name + ".provenance.json")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Unable to read valid raw-data provenance at {provenance_path}: {exc}"
        ) from exc
    if not isinstance(provenance, dict):
        raise ValueError(f"Raw-data provenance must be a JSON object: {provenance_path}")
    processed_path = data_directory / "processed" / PROCESSED_NAME
    quality_report_path = repository_root / REPORT_PATH
    eda_directory = repository_root / EDA_RELATIVE_PATH

    expected_outputs = {processed_path, quality_report_path} | _expected_eda_files(
        eda_directory
    )
    existing = sorted(path for path in expected_outputs if path.exists())
    if existing and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite existing generated output(s): "
            + ", ".join(str(path) for path in existing)
            + ". Rerun with --overwrite to replace these pipeline outputs."
        )

    quality = validate_csv(raw_path, chunksize=chunksize)
    quality["source"] = provenance
    quality["raw_csv_sha256"] = sha256_file(raw_path)
    quality["dataset_period"] = "2024-01"
    quality["processing_chunk_rows"] = chunksize
    empty_header_columns = {
        column
        for column in quality["blank_header_columns"]
        if quality["missing_values"].get(column) == quality["total_rows"]
    }
    quality["processed_columns_dropped"] = sorted(empty_header_columns)

    processed_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = processed_path.with_name(processed_path.stem + ".tmp.parquet")
    if temporary_output.exists():
        temporary_output.unlink()

    import pyarrow as pa
    import pyarrow.parquet as pq

    writer: pq.ParquetWriter | None = None
    processed_rows = 0
    eda = EDAAccumulator()
    with tempfile.TemporaryDirectory(prefix="flightpulse-process-") as temp_dir:
        tracker = ExactDuplicateTracker(Path(temp_dir) / "rows.sqlite")
        try:
            for source_chunk in read_csv_chunks(
                raw_path,
                chunksize=chunksize,
                drop_columns=empty_header_columns,
            ):
                unique_chunk = source_chunk.loc[
                    tracker.mark_unique(source_chunk)
                ]
                cleaned = clean_dataframe(unique_chunk)
                if cleaned.empty:
                    continue
                eda.add(cleaned)
                table = pa.Table.from_pandas(cleaned, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(
                        temporary_output,
                        table.schema,
                        compression="zstd",
                    )
                else:
                    table = table.cast(writer.schema, safe=False)
                writer.write_table(table, row_group_size=chunksize)
                processed_rows += len(cleaned)
        except Exception:
            if writer is not None:
                writer.close()
            if temporary_output.exists():
                temporary_output.unlink()
            raise
        finally:
            tracker.close()

    if writer is not None:
        writer.close()
    if processed_rows == 0:
        if temporary_output.exists():
            temporary_output.unlink()
        raise ValueError(
            "No valid January 2024 flight rows remain after cleaning; "
            "no processed dataset or EDA report was generated."
        )

    temporary_output.replace(processed_path)
    eda_summary = eda.save(eda_directory)
    quality["processed_rows"] = processed_rows
    quality["excluded_rows"] = quality["total_rows"] - processed_rows
    quality["eda_summary"] = eda_summary
    write_quality_report(quality, quality_report_path)

    print(f"Raw source (unchanged): {raw_path}")
    print(f"Processed Parquet: {processed_path}")
    print(f"Quality report: {quality_report_path}")
    print(f"EDA outputs: {eda_directory}")
    print(
        f"Rows: {quality['total_rows']:,} scanned, "
        f"{processed_rows:,} processed, "
        f"{quality['duplicate_rows']:,} exact duplicates"
    )
    return quality


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire and process the official BTS January 2024 On-Time dataset."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Data root (defaults to DATA_DIRECTORY from .env or ./data).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("download", help="Download and preserve the official BTS ZIP/CSV.")

    process_parser = subparsers.add_parser(
        "process", help="Validate and process a CSV; use --input for manual imports."
    )
    process_parser.add_argument("--input", type=Path, default=None)
    process_parser.add_argument(
        "--chunksize", type=int, default=DEFAULT_CHUNK_ROWS
    )
    process_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace prior generated outputs (never replaces the raw source).",
    )

    all_parser = subparsers.add_parser(
        "all", help="Download BTS data and process it in one command."
    )
    all_parser.add_argument("--chunksize", type=int, default=DEFAULT_CHUNK_ROWS)
    all_parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the standalone ingestion command."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    data_directory = (args.data_dir or settings.data_directory).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[2]

    try:
        if args.command == "download":
            download_bts_data(data_directory)
        elif args.command == "process":
            input_path = args.input
            if input_path is None:
                input_path = data_directory / "raw" / CSV_NAME
            process_bts_csv(
                input_path.expanduser().resolve(),
                data_directory,
                repository_root,
                chunksize=args.chunksize,
                overwrite=args.overwrite,
            )
        elif args.command == "all":
            csv_path = download_bts_data(data_directory)
            process_bts_csv(
                csv_path,
                data_directory,
                repository_root,
                chunksize=args.chunksize,
                overwrite=args.overwrite,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
