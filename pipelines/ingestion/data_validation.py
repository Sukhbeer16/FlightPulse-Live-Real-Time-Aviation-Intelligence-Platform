"""Chunked validation and quality metrics for BTS On-Time CSV data."""

from __future__ import annotations

import calendar
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from pipelines.ingestion.data_cleaning import (
    BOOLEAN_COLUMNS,
    NUMERIC_COLUMNS,
    NUMERIC_RANGES,
    REQUIRED_COLUMNS,
    TIME_COLUMNS,
)

RANGE_LIMITS = NUMERIC_RANGES
DELAY_COLUMNS = {
    "DepDelay",
    "ArrDelay",
    "DepDelayMinutes",
    "ArrDelayMinutes",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
}


class ExactDuplicateTracker:
    """Track complete duplicate rows on disk to bound memory use."""

    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.execute(
            "CREATE TABLE seen_rows (row_hash TEXT PRIMARY KEY) WITHOUT ROWID"
        )

    def mark_unique(self, frame: pd.DataFrame) -> pd.Series:
        """Return a mask selecting the first occurrence of each full row."""
        hashes = pd.util.hash_pandas_object(frame, index=False).astype("uint64")
        unique_flags: list[bool] = []
        cursor = self._connection.cursor()
        for value in hashes:
            row_hash = f"{int(value):016x}"
            cursor.execute(
                "INSERT OR IGNORE INTO seen_rows (row_hash) VALUES (?)", (row_hash,)
            )
            unique_flags.append(cursor.rowcount == 1)
        self._connection.commit()
        return pd.Series(unique_flags, index=frame.index, dtype=bool)

    def close(self) -> None:
        """Close the on-disk duplicate index."""
        self._connection.close()


def _read_header(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError(f"Expected a CSV input file, got: {path.name}")
    try:
        return list(pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ValueError(f"Unable to read CSV header from {path}: {exc}") from exc


def validate_csv(
    path: Path,
    chunksize: int = 50_000,
    year: int = 2024,
    month: int = 1,
) -> dict[str, Any]:
    """Inspect schema, nulls, duplicates, types, dates, and numeric ranges.

    The scanner holds at most one pandas chunk plus a disk-backed set of row
    hashes in memory. An invalid required schema is rejected immediately.
    """
    if chunksize < 1:
        raise ValueError("chunksize must be a positive integer.")
    if year < 1987 or not 1 <= month <= 12:
        raise ValueError("Expected a valid BTS reporting year and month.")
    period_start = pd.Timestamp(year=year, month=month, day=1)
    last_day = calendar.monthrange(year, month)[1]
    period_end = pd.Timestamp(year=year, month=month, day=last_day) + pd.Timedelta(
        days=1, microseconds=-1
    )
    columns = _read_header(path)
    missing_required = sorted(REQUIRED_COLUMNS.difference(columns))
    if missing_required:
        raise ValueError(f"Input is missing required BTS columns: {missing_required}")

    missing_values: Counter[str] = Counter()
    invalid_values: Counter[str] = Counter()
    observed_types: dict[str, set[str]] = {column: set() for column in columns}
    total_rows = 0
    invalid_date_rows = 0
    out_of_scope_rows = 0
    unique_count = 0

    with tempfile.TemporaryDirectory(prefix="flightpulse-duplicates-") as temp_dir:
        tracker = ExactDuplicateTracker(Path(temp_dir) / "rows.sqlite")
        try:
            try:
                chunks = pd.read_csv(
                    path,
                    chunksize=chunksize,
                    encoding="utf-8-sig",
                    low_memory=False,
                    dtype="string",
                )
                for chunk in chunks:
                    total_rows += len(chunk)
                    for column in columns:
                        missing_values[column] += int(
                            chunk[column].isna().sum()
                            + chunk[column]
                            .astype("string")
                            .str.strip()
                            .eq("")
                            .fillna(False)
                            .sum()
                        )
                        if column == "FlightDate":
                            observed_types[column].add("date")
                        elif column in (
                            NUMERIC_COLUMNS
                            | TIME_COLUMNS
                            | DELAY_COLUMNS
                            | BOOLEAN_COLUMNS
                            | set(RANGE_LIMITS)
                        ):
                            observed_types[column].add("numeric")
                        else:
                            observed_types[column].add("string/category")

                    dates = pd.to_datetime(chunk["FlightDate"], errors="coerce")
                    nonempty_dates = chunk["FlightDate"].notna() & chunk[
                        "FlightDate"
                    ].astype("string").str.strip().ne("")
                    invalid_date_rows += int((nonempty_dates & dates.isna()).sum())
                    out_of_scope_rows += int(
                        (
                            dates.notna()
                            & ~dates.between(
                                period_start,
                                period_end,
                            )
                        ).sum()
                    )

                    numeric_columns = (
                        NUMERIC_COLUMNS
                        | TIME_COLUMNS
                        | DELAY_COLUMNS
                        | BOOLEAN_COLUMNS
                        | set(RANGE_LIMITS)
                    ).intersection(columns)
                    for column in numeric_columns:
                        original = chunk[column]
                        parsed = pd.to_numeric(original, errors="coerce")
                        nonempty = original.notna() & original.astype("string").str.strip().ne("")
                        invalid_values[column] += int((nonempty & parsed.isna()).sum())

                        if column in RANGE_LIMITS:
                            lower, upper = RANGE_LIMITS[column]
                            invalid_values[column] += int(
                                (parsed.notna() & ~parsed.between(lower, upper)).sum()
                            )
                        if column in TIME_COLUMNS:
                            hour = parsed // 100
                            minute = parsed % 100
                            valid_clock_time = (
                                parsed.between(0, 2400)
                                & (minute < 60)
                                & minute.mod(1).eq(0)
                                & ((hour < 24) | parsed.eq(2400))
                            )
                            invalid_values[column] += int(
                                (parsed.notna() & ~valid_clock_time).sum()
                            )
                        if column in BOOLEAN_COLUMNS:
                            invalid_values[column] += int(
                                (parsed.notna() & ~parsed.isin([0, 1])).sum()
                            )

                    unique_count += int(tracker.mark_unique(chunk).sum())
            except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
                raise ValueError(f"Unable to read valid BTS CSV input {path}: {exc}") from exc
        finally:
            tracker.close()

    if total_rows == 0:
        raise ValueError(f"CSV contains a header but no data rows: {path}")

    return {
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "column_count": len(columns),
        "named_column_count": len(
            [column for column in columns if not column.startswith("Unnamed: ")]
        ),
        "blank_header_columns": [
            column for column in columns if column.startswith("Unnamed: ")
        ],
        "columns": columns,
        "missing_required_columns": missing_required,
        "missing_relevant_columns": sorted(
            {
                "FlightDate",
                "Reporting_Airline",
                "Origin",
                "Dest",
                "CRSDepTime",
                "DepTime",
                "DepDelay",
                "CRSArrTime",
                "ArrTime",
                "ArrDelay",
                "Cancelled",
                "Diverted",
                "Distance",
            }.difference(columns)
        ),
        "total_rows": total_rows,
        "unique_rows": unique_count,
        "duplicate_rows": total_rows - unique_count,
        "invalid_date_rows": invalid_date_rows,
        "out_of_scope_date_rows": out_of_scope_rows,
        "reporting_year": year,
        "reporting_month": month,
        "missing_values": dict(sorted(missing_values.items())),
        "invalid_values": dict(sorted(invalid_values.items())),
        "column_types": {
            column: sorted(types) for column, types in sorted(observed_types.items())
        },
        "validated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }


def write_quality_report(report: dict[str, Any], output_path: Path) -> None:
    """Write a reproducible Markdown summary based only on measured input."""
    missing = report["missing_values"]
    invalid = report["invalid_values"]
    period = (
        f"{report.get('reporting_year', 2024):04d}-"
        f"{report.get('reporting_month', 1):02d}"
    )
    lines = [
        f"# BTS {period} data quality report",
        "",
        f"- **Input file:** `{report['file_name']}`",
        f"- **Validated (UTC):** {report['validated_at_utc']}",
        f"- **File size:** {report['file_size_bytes']:,} bytes",
        f"- **Columns:** {report['column_count']}",
        f"- **Named columns:** {report['named_column_count']}",
        f"- **Blank-header columns:** "
        f"{', '.join(report['blank_header_columns']) or 'None'}",
        f"- **Missing optional relevant columns:** "
        f"{', '.join(report['missing_relevant_columns']) or 'None'}",
        f"- **Rows scanned:** {report['total_rows']:,}",
        f"- **Unique rows:** {report['unique_rows']:,}",
        f"- **Duplicate rows after first occurrence:** {report['duplicate_rows']:,}",
        f"- **Unparseable non-empty dates:** {report['invalid_date_rows']:,}",
        f"- **Rows outside {period}:** {report['out_of_scope_date_rows']:,}",
        "",
        "## Missing values",
        "",
        "| Column | Missing/blank rows |",
        "|---|---:|",
    ]
    lines.extend(
        f"| `{column}` | {count:,} |"
        for column, count in missing.items()
        if count
    )
    if not any(missing.values()):
        lines.append("| None | 0 |")
    lines.extend(
        [
            "",
            "## Invalid values",
            "",
            "Counts include non-numeric values in numeric fields and values outside",
            "the documented sanity ranges. Counts are per field; one row may be",
            "invalid in more than one field.",
            "",
            "| Column | Invalid values |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| `{column}` | {count:,} |" for column, count in invalid.items() if count
    )
    if not any(invalid.values()):
        lines.append("| None | 0 |")
    lines.extend(
        [
            "",
            "## Schema and type observations",
            "",
            "| Column | Validated semantic type(s) |",
            "|---|---|",
        ]
    )
    lines.extend(
        f"| `{column}` | {', '.join(types)} |"
        for column, types in report["column_types"].items()
    )
    lines.extend(
        [
            "",
            "Missing-column notices for non-required BTS fields are informational.",
            "Core columns required for date-, route-, and label-based processing are",
            "validated before cleaning. Invalid dates, out-of-scope dates, incomplete",
            "flight identity fields, and exact duplicate records are excluded from the",
            "processed output; missing measurements are not imputed.",
            "",
        ]
    )
    if "processed_rows" in report:
        lines.extend(
            [
                "## Processing result",
                "",
                f"- **Processed rows:** {report['processed_rows']:,}",
                f"- **Excluded rows:** {report['excluded_rows']:,}",
                "- **Entirely empty unnamed columns omitted from Parquet:** "
                f"{', '.join(report['processed_columns_dropped']) or 'None'}",
                f"- **Raw CSV SHA-256:** `{report['raw_csv_sha256']}`",
                f"- **Source:** {report['source']['source']}",
                f"- **Source URL:** {report['source']['source_url']}",
                f"- **Acquisition method:** {report['source']['acquisition_method']}",
                "- **Download date (UTC):** "
                f"{report['source'].get('download_date_utc') or 'Not available for manual import'}",
                f"- **Imported date (UTC):** "
                f"{report['source'].get('imported_at_utc') or 'Not applicable'}",
                "",
                "EDA CSV tables and PNG charts were written under "
                "`reports/eda/2024-01/`.",
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_provenance(provenance: dict[str, Any], output_path: Path) -> None:
    """Persist source and acquisition metadata next to the immutable raw file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a file checksum without loading the entire dataset into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()
