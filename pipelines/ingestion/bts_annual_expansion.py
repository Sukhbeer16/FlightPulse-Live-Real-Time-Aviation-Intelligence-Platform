"""Acquire and validate the official BTS 2024 monthly On-Time Performance data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from pipelines.ingestion.bts_ingestion import (
    _validate_bts_archive,
    download_archive,
    extract_bts_csv,
)
from pipelines.ingestion.data_cleaning import clean_dataframe
from pipelines.ingestion.data_validation import (
    ExactDuplicateTracker,
    _read_header,
    validate_csv,
)


YEAR = 2024
BASE_URL = "https://transtats.bts.gov/PREZIP"
DATASET_PREFIX = (
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present"
)
JANUARY_PARQUET = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "processed"
    / "bts_ontime_2024_01.parquet"
)
RAW_DIRECTORY = JANUARY_PARQUET.parents[1] / "raw"
MONTHLY_DIRECTORY = JANUARY_PARQUET.parent / "monthly"
ANNUAL_PARQUET = JANUARY_PARQUET.parent / "bts_ontime_2024.parquet"
ANNUAL_MANIFEST = JANUARY_PARQUET.parent / "bts_ontime_2024_manifest.json"
CHUNK_SIZE = 50_000
REQUIRED_FLIGHT_IDENTITY = (
    "FlightDate",
    "Reporting_Airline",
    "Flight_Number_Reporting_Airline",
    "Origin",
    "Dest",
)


def _month_paths(month: int) -> tuple[str, str, Path, Path, Path]:
    archive_name = f"{DATASET_PREFIX}_2024_{month}.zip"
    csv_name = (
        "On_Time_Reporting_Carrier_On_Time_Performance_"
        f"(1987_present)_2024_{month}.csv"
    )
    archive_path = RAW_DIRECTORY / archive_name
    csv_path = RAW_DIRECTORY / csv_name
    parquet_path = MONTHLY_DIRECTORY / f"bts_ontime_2024_{month:02d}.parquet"
    return archive_name, csv_name, archive_path, csv_path, parquet_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _month_url(month: int) -> str:
    archive_name, _, _, _, _ = _month_paths(month)
    return f"{BASE_URL}/{archive_name}"


def _download_month(month: int) -> tuple[Path, Path, str]:
    archive_name, csv_name, archive_path, csv_path, _ = _month_paths(month)
    url = _month_url(month)
    request = Request(url, method="HEAD")
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"BTS returned HTTP {response.status} for {url}."
                )
            advertised_size = int(response.headers.get("Content-Length", "0"))
    except HTTPError as exc:
        if exc.code in (404, 410):
            raise FileNotFoundError(
                f"Official BTS archive is unavailable for 2024-{month:02d}: {url}"
            ) from exc
        raise RuntimeError(f"BTS archive probe failed for {url}: {exc}") from exc
    except (OSError, URLError, ValueError) as exc:
        raise RuntimeError(f"BTS archive probe failed for {url}: {exc}") from exc
    if advertised_size <= 0:
        raise RuntimeError(f"BTS advertised an empty archive for {url}.")

    downloaded = download_archive(
        archive_path,
        source_url=url,
        expected_csv=csv_name,
    )
    if not downloaded.is_file() or downloaded.stat().st_size <= 0:
        raise RuntimeError(f"Downloaded BTS archive is empty: {downloaded}")
    if downloaded.stat().st_size != advertised_size:
        raise RuntimeError(
            f"Archive size mismatch for {downloaded.name}: "
            f"{downloaded.stat().st_size} != {advertised_size}."
        )
    _validate_bts_archive(downloaded, csv_name)
    if not csv_path.exists():
        extract_bts_csv(
            downloaded,
            RAW_DIRECTORY,
            expected_csv=csv_name,
            target_path=csv_path,
        )
        provenance = {
            "period": f"{YEAR}-{month:02d}",
            "source": "U.S. Department of Transportation, Bureau of Transportation Statistics",
            "source_url": url,
            "archive_file": archive_name,
            "archive_sha256": _sha256_file(downloaded),
            "raw_csv_file": csv_name,
            "raw_csv_sha256": _sha256_file(csv_path),
            "acquisition_method": "official BTS PREZIP archive download",
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        csv_path.with_name(csv_path.name + ".provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
    elif not csv_path.with_name(csv_path.name + ".provenance.json").is_file():
        raise FileExistsError(
            f"Refusing to trust an existing BTS CSV without provenance: {csv_path}"
        )
    if csv_path.stat().st_size <= 0:
        raise RuntimeError(f"Extracted BTS CSV is empty: {csv_path}")
    return downloaded, csv_path, url


def _source_exclusion_counts(
    frame: pd.DataFrame, year: int, month: int
) -> tuple[pd.DataFrame, Counter[str]]:
    exclusions: Counter[str] = Counter()
    raw_dates = frame["FlightDate"].astype("string")
    dates = pd.to_datetime(raw_dates, errors="coerce")
    missing_date = raw_dates.isna() | raw_dates.str.strip().eq("").fillna(False)
    invalid_date = ~missing_date & dates.isna()
    exclusions["missing_date"] = int(missing_date.sum())
    exclusions["invalid_date"] = int(invalid_date.sum())

    valid_date = dates.notna() & ~missing_date
    out_of_period = valid_date & (
        (dates.dt.year != year) | (dates.dt.month != month)
    )
    exclusions["out_of_reporting_period"] = int(out_of_period.sum())

    in_period = valid_date & ~out_of_period
    missing_identity = pd.Series(False, index=frame.index)
    for column in REQUIRED_FLIGHT_IDENTITY[1:]:
        values = frame[column].astype("string")
        missing_identity |= values.isna() | values.str.strip().eq("").fillna(False)
    missing_identity &= in_period
    exclusions["missing_flight_identity"] = int(missing_identity.sum())
    keep = in_period & ~missing_identity
    return frame.loc[keep].copy(), exclusions


def _validate_reconciliation(metrics: dict[str, int]) -> None:
    if metrics["cancelled_and_diverted_overlap"]:
        raise ValueError("Cancelled and diverted BTS records overlap.")
    if metrics["total_records"] != (
        metrics["cancelled"] + metrics["diverted"] + metrics["eligible_arrival"]
    ):
        raise ValueError(
            "Monthly flight-count reconciliation failed: "
            f"{metrics['total_records']} != {metrics['cancelled']} + "
            f"{metrics['diverted']} + {metrics['eligible_arrival']}."
        )
    if metrics["eligible_arrival"] != (
        metrics["delayed"] + metrics["non_delayed"]
    ):
        raise ValueError("Monthly eligible-arrival target counts do not reconcile.")


def _month_metrics(
    frame: pd.DataFrame, *, validate: bool = False
) -> dict[str, int]:
    cancelled = frame["Cancelled"].eq(1)
    diverted = frame["Diverted"].eq(1)
    if not frame["Cancelled"].isin([0, 1]).all() or not frame["Diverted"].isin(
        [0, 1]
    ).all():
        raise ValueError("Monthly data contains missing or invalid status flags.")
    eligible = ~cancelled & ~diverted & frame["ArrDelay"].notna()
    overlap = cancelled & diverted
    metrics = {
        "total_records": len(frame),
        "cancelled": int(cancelled.sum()),
        "diverted": int(diverted.sum()),
        "eligible_arrival": int(eligible.sum()),
        "delayed": int((eligible & frame["ArrDelay"].gt(15)).sum()),
        "non_delayed": int((eligible & frame["ArrDelay"].le(15)).sum()),
        "null_arrival_delay": int(frame["ArrDelay"].isna().sum()),
        "cancelled_and_diverted_overlap": int(overlap.sum()),
        "airlines": int(frame["Reporting_Airline"].nunique()),
        "airports": int(
            pd.concat([frame["Origin"], frame["Dest"]], ignore_index=True).nunique()
        ),
        "routes": int(
            frame[["Origin", "Dest"]].drop_duplicates().shape[0]
        ),
    }
    if validate:
        _validate_reconciliation(metrics)
    return metrics


def _process_month(
    month: int,
    csv_path: Path,
    source_url: str,
    archive_path: Path,
    expected_source_columns: list[str],
    expected_parquet_schema: pa.Schema,
) -> dict[str, Any]:
    quality = validate_csv(csv_path, chunksize=CHUNK_SIZE, year=YEAR, month=month)
    if quality["columns"] != expected_source_columns:
        raise ValueError(
            f"2024-{month:02d} source schema differs from January's BTS schema."
        )
    if quality["out_of_scope_date_rows"]:
        raise ValueError(
            f"2024-{month:02d} contains dates outside its reporting period."
        )
    empty_header_columns = {
        column
        for column in quality["blank_header_columns"]
        if quality["missing_values"].get(column) == quality["total_rows"]
    }

    MONTHLY_DIRECTORY.mkdir(parents=True, exist_ok=True)
    _, _, _, _, output_path = _month_paths(month)
    if output_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing monthly Parquet output: {output_path}"
        )
    temporary_path = output_path.with_name(output_path.name + ".part")
    if temporary_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an incomplete monthly output: {temporary_path}"
        )

    source_rows = 0
    retained_rows = 0
    excluded_rows: Counter[str] = Counter()
    metrics: Counter[str] = Counter()
    airlines: set[str] = set()
    airports: set[str] = set()
    routes: set[tuple[str, str]] = set()
    writer: pq.ParquetWriter | None = None
    try:
        with tempfile.TemporaryDirectory(prefix=f"flightpulse-2024-{month:02d}-") as temp:
            duplicate_tracker = ExactDuplicateTracker(Path(temp) / "source_rows.sqlite")
            try:
                for chunk in pd.read_csv(
                    csv_path,
                    chunksize=CHUNK_SIZE,
                    encoding="utf-8-sig",
                    low_memory=False,
                    dtype="string",
                ):
                    if empty_header_columns:
                        chunk = chunk.drop(columns=empty_header_columns)
                    for column, expected in (("Year", YEAR), ("Month", month)):
                        if column not in chunk:
                            raise ValueError(
                                f"2024-{month:02d} source is missing {column}."
                            )
                        observed = pd.to_numeric(chunk[column], errors="coerce")
                        if observed.isna().any() or not observed.eq(expected).all():
                            raise ValueError(
                                f"2024-{month:02d} source contains an incorrect "
                                f"{column} reporting value."
                            )
                    source_rows += len(chunk)
                    unique_mask = duplicate_tracker.mark_unique(chunk)
                    duplicate_count = int((~unique_mask).sum())
                    excluded_rows["exact_duplicates"] += duplicate_count
                    unique = chunk.loc[unique_mask]
                    candidates, chunk_excluded = _source_exclusion_counts(
                        unique, YEAR, month
                    )
                    excluded_rows.update(chunk_excluded)
                    cleaned = clean_dataframe(candidates, year=YEAR, month=month)
                    excluded_rows["normalized_duplicates"] += len(candidates) - len(
                        cleaned
                    )
                    if cleaned.empty:
                        continue
                    batch_metrics = _month_metrics(cleaned)
                    metrics.update(
                        {
                            name: count
                            for name, count in batch_metrics.items()
                            if name not in {"airlines", "airports", "routes"}
                        }
                    )
                    airlines.update(cleaned["Reporting_Airline"].dropna().unique())
                    airports.update(cleaned["Origin"].dropna().unique())
                    airports.update(cleaned["Dest"].dropna().unique())
                    routes.update(
                        zip(cleaned["Origin"].astype(str), cleaned["Dest"].astype(str))
                    )
                    retained_rows += len(cleaned)
                    table = pa.Table.from_pandas(cleaned, preserve_index=False)
                    try:
                        table = table.cast(expected_parquet_schema, safe=False)
                    except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
                        raise ValueError(
                            f"2024-{month:02d} output schema does not match January: {exc}"
                        ) from exc
                    if writer is None:
                        writer = pq.ParquetWriter(
                            temporary_path, expected_parquet_schema, compression="zstd"
                        )
                    writer.write_table(table, row_group_size=CHUNK_SIZE)
            finally:
                duplicate_tracker.close()
        if writer is None:
            raise ValueError(f"No valid rows retained for 2024-{month:02d}.")
        writer.close()
        writer = None
        if source_rows != quality["total_rows"]:
            raise ValueError(
                f"CSV row count changed between scans: {source_rows} != "
                f"{quality['total_rows']}."
            )
        if sum(excluded_rows.values()) + retained_rows != source_rows:
            raise ValueError(
                f"Monthly row exclusions do not reconcile: "
                f"{sum(excluded_rows.values())} + {retained_rows} != {source_rows}."
            )
        file_metrics = _month_metrics(
            pq.read_table(
                temporary_path,
                columns=[
                    "Cancelled",
                    "Diverted",
                    "ArrDelay",
                    "Reporting_Airline",
                    "Origin",
                    "Dest",
                ],
            ).to_pandas(),
            validate=True,
        )
        metrics.update(
            {
                "airlines": len(airlines),
                "airports": len(airports),
                "routes": len(routes),
            }
        )
        if file_metrics["total_records"] != retained_rows:
            raise ValueError("Written monthly Parquet row count does not reconcile.")
        if dict(metrics) != file_metrics:
            raise ValueError(
                "Monthly streaming counts do not match the written Parquet metrics."
            )
        os.replace(temporary_path, output_path)
    except Exception:
        if writer is not None:
            writer.close()
        temporary_path.unlink(missing_ok=True)
        raise

    report = {
        "period": f"{YEAR}-{month:02d}",
        "source_url": source_url,
        "source_archive": archive_path.name,
        "source_archive_sha256": _sha256_file(archive_path),
        "source_csv": csv_path.name,
        "source_csv_sha256": _sha256_file(csv_path),
        "source_row_count": source_rows,
        "retained_row_count": retained_rows,
        "excluded_row_count": sum(excluded_rows.values()),
        "excluded_rows_by_reason": dict(sorted(excluded_rows.items())),
        "exact_duplicate_count": excluded_rows["exact_duplicates"],
        "validation_scan": quality,
        "flight_metrics": file_metrics,
        "output_path": str(output_path.relative_to(JANUARY_PARQUET.parents[2])),
        "output_schema": str(expected_parquet_schema),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_status": "passed",
    }
    report_path = output_path.with_suffix(".validation.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _copy_month_to_writer(
    input_path: Path,
    writer: pq.ParquetWriter,
    expected_schema: pa.Schema,
) -> int:
    schema = pq.read_schema(input_path)
    if not schema.equals(expected_schema, check_metadata=False):
        raise ValueError(f"Monthly Parquet schema mismatch: {input_path}")
    rows = 0
    parquet_file = pq.ParquetFile(input_path)
    for batch in parquet_file.iter_batches(batch_size=CHUNK_SIZE):
        table = pa.Table.from_batches([batch])
        if not table.schema.equals(expected_schema, check_metadata=False):
            table = table.cast(expected_schema, safe=False)
        writer.write_table(table, row_group_size=CHUNK_SIZE)
        rows += table.num_rows
    return rows


def _verify_annual_dataset(
    path: Path, included_months: list[int]
) -> tuple[dict[str, int], dict[str, str]]:
    from pipelines.ml.feature_dataset import _source_metrics

    metrics: Counter[str] = Counter()
    observed_months: set[int] = set()
    first_date = None
    last_date = None
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=CHUNK_SIZE,
        columns=["FlightDate", "Cancelled", "Diverted", "ArrDelay"],
    ):
        table = pa.Table.from_batches([batch])
        metrics.update(_source_metrics(table))
        dates = pc.cast(table["FlightDate"], pa.date32()).to_pylist()
        if any(value is None for value in dates):
            raise ValueError("Annual Parquet contains a null FlightDate.")
        if any(value.year != YEAR or value.month not in included_months for value in dates):
            raise ValueError("Annual Parquet contains an out-of-scope FlightDate.")
        observed_months.update(value.month for value in dates)
        batch_first, batch_last = min(dates), max(dates)
        first_date = min(first_date or batch_first, batch_first)
        last_date = max(last_date or batch_last, batch_last)
    if observed_months != set(included_months):
        raise ValueError(
            "Annual Parquet month coverage differs from its manifest: "
            f"{sorted(observed_months)} != {sorted(included_months)}."
        )
    result = dict(metrics)
    if result["total_flights"] != (
        result["cancelled_flights"]
        + result["diverted_flights"]
        + result["eligible_delay_records"]
    ):
        raise ValueError("Annual cancellation/diversion/eligibility counts do not reconcile.")
    if result["eligible_delay_records"] != (
        result["delayed_flights"] + result["non_delayed_eligible_flights"]
    ):
        raise ValueError("Annual delayed and non-delayed counts do not reconcile.")
    coverage = {
        "start_date": first_date.isoformat(),
        "end_date": last_date.isoformat(),
    }
    return result, coverage


def _build_annual_dataset(
    month_paths: list[Path], month_reports: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_schema = pq.read_schema(JANUARY_PARQUET)
    if ANNUAL_PARQUET.exists() or ANNUAL_MANIFEST.exists():
        if not (ANNUAL_PARQUET.is_file() and ANNUAL_MANIFEST.is_file()):
            raise FileExistsError(
                "Annual dataset and manifest must both exist to reuse prior outputs."
            )
        existing = json.loads(ANNUAL_MANIFEST.read_text(encoding="utf-8"))
        parquet = pq.ParquetFile(ANNUAL_PARQUET)
        if (
            existing.get("validation_status") != "passed"
            or existing.get("output_sha256") != _sha256_file(ANNUAL_PARQUET)
            or existing.get("total_rows") != parquet.metadata.num_rows
            or not parquet.schema_arrow.equals(expected_schema, check_metadata=False)
        ):
            raise ValueError("Existing annual dataset or manifest failed verification.")
        expected_periods = [
            "2024-01",
            *[report["period"] for report in month_reports],
        ]
        if [
            item["period"] for item in existing.get("monthly_sources", [])
        ] != expected_periods:
            raise ValueError("Existing annual dataset does not match validated months.")
        return existing
    temporary_path = ANNUAL_PARQUET.with_name(ANNUAL_PARQUET.name + ".part")
    if temporary_path.exists():
        raise FileExistsError(f"Refusing to overwrite incomplete output: {temporary_path}")

    writer: pq.ParquetWriter | None = None
    try:
        writer = pq.ParquetWriter(
            temporary_path, expected_schema, compression="zstd"
        )
        paths = [JANUARY_PARQUET, *month_paths]
        total_rows = sum(
            _copy_month_to_writer(path, writer, expected_schema) for path in paths
        )
        writer.close()
        writer = None
        os.replace(temporary_path, ANNUAL_PARQUET)
    except Exception:
        if writer is not None:
            writer.close()
        temporary_path.unlink(missing_ok=True)
        raise

    parquet = pq.ParquetFile(ANNUAL_PARQUET)
    actual_rows = parquet.metadata.num_rows
    if actual_rows != total_rows:
        raise ValueError(f"Annual row count mismatch: {actual_rows} != {total_rows}.")
    months = sorted(
        [{"month": 1, "path": str(JANUARY_PARQUET)}, *[
            {"month": int(report["period"][-2:]), "path": str(path)}
            for report, path in zip(month_reports, month_paths)
        ]],
        key=lambda item: item["month"],
    )
    included_months = [item["month"] for item in months]
    missing_months = sorted(set(range(1, 13)).difference(included_months))
    expected_rows = sum(
        pq.ParquetFile(path).metadata.num_rows for path in [JANUARY_PARQUET, *month_paths]
    )
    if expected_rows != actual_rows:
        raise ValueError("Annual Parquet rows do not reconcile to monthly inputs.")
    flight_metrics, date_coverage = _verify_annual_dataset(
        ANNUAL_PARQUET, included_months
    )
    manifest = {
        "year": YEAR,
        "included_months": included_months,
        "missing_months": missing_months,
        "monthly_sources": [
            {
                "period": "2024-01",
                "source_file": "existing processed BTS January dataset",
                "source_sha256": _sha256_file(JANUARY_PARQUET),
                "output_rows": pq.ParquetFile(JANUARY_PARQUET).metadata.num_rows,
            },
            *[
                {
                    "period": report["period"],
                    "source_file": report["source_csv"],
                    "source_archive": report["source_archive"],
                    "source_archive_sha256": report["source_archive_sha256"],
                    "source_csv_sha256": report["source_csv_sha256"],
                    "output_rows": report["retained_row_count"],
                }
                for report in month_reports
            ],
        ],
        "output_path": str(ANNUAL_PARQUET.relative_to(JANUARY_PARQUET.parents[2])),
        "total_rows": actual_rows,
        "output_sha256": _sha256_file(ANNUAL_PARQUET),
        "flight_metrics": flight_metrics,
        "date_coverage": date_coverage,
        "schema": str(parquet.schema_arrow),
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "validation_status": "passed",
        "month_validation_reports": [
            report["output_path"].replace(".parquet", ".validation.json")
            for report in month_reports
        ],
        "duplicate_records_across_months": 0,
        "duplicate_reconciliation_basis": (
            "Each monthly source is exact-deduplicated; validated FlightDate "
            "ranges are disjoint across calendar months."
        ),
    }
    ANNUAL_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def run_annual_expansion() -> dict[str, Any]:
    """Acquire missing months sequentially, validate them, then combine outputs."""
    if not JANUARY_PARQUET.is_file():
        raise FileNotFoundError(f"Existing January BTS Parquet is missing: {JANUARY_PARQUET}")
    january_csv = RAW_DIRECTORY / f"{DATASET_PREFIX}_2024_1.csv"
    expected_source_columns = _read_header(january_csv)
    expected_parquet_schema = pq.read_schema(JANUARY_PARQUET)

    reports: list[dict[str, Any]] = []
    month_paths: list[Path] = []
    unavailable: list[int] = []
    for month in range(2, 13):
        archive_name, csv_name, archive_path, csv_path, output_path = _month_paths(month)
        report_path = output_path.with_suffix(".validation.json")
        if output_path.exists() or report_path.exists():
            if not (output_path.is_file() and report_path.is_file()):
                raise FileExistsError(
                    f"Incomplete prior monthly output for 2024-{month:02d}; "
                    "refusing to overwrite."
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if (
                report.get("validation_status") != "passed"
                or report.get("source_csv_sha256") != _sha256_file(csv_path)
                or report.get("source_archive_sha256") != _sha256_file(archive_path)
            ):
                raise ValueError(
                    f"Existing monthly output is stale or invalid: {output_path}"
                )
            reports.append(report)
            month_paths.append(output_path)
            continue
        try:
            downloaded, csv_file, url = _download_month(month)
        except FileNotFoundError:
            unavailable.append(month)
            continue
        if archive_path.name != archive_name or csv_file.name != csv_name:
            raise RuntimeError("Downloaded BTS source path does not match its month.")
        if not csv_file.is_file() or csv_file.stat().st_size <= 0:
            raise RuntimeError(f"Expected nonempty BTS CSV not found: {csv_file}")
        report = _process_month(
            month,
            csv_file,
            url,
            downloaded,
            expected_source_columns,
            expected_parquet_schema,
        )
        reports.append(report)
        month_paths.append(output_path)

    manifest = _build_annual_dataset(month_paths, reports)
    manifest["unavailable_months"] = unavailable
    ANNUAL_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    from pipelines.ml.annual_feature_dataset import build_annual_feature_dataset

    feature_manifest = build_annual_feature_dataset()
    return {
        "manifest": manifest,
        "monthly_reports": reports,
        "unavailable_months": unavailable,
        "ml_feature_manifest": feature_manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        result = run_annual_expansion()
    except Exception as exc:
        raise SystemExit(f"BTS annual expansion failed: {exc}") from exc
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
