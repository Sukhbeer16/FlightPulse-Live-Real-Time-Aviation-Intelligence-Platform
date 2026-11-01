"""Tests for the combined January-February ML feature dataset."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pipelines.ml.combined_feature_dataset import (
    OUTPUT_MANIFEST,
    OUTPUT_PATH,
    _split_for_date,
    build_combined_feature_dataset,
)
from pipelines.ml.feature_dataset import (
    FEATURE_ALLOWLIST,
    LEAKAGE_DENYLIST,
    SOURCE_COLUMNS,
    TARGET_COLUMN,
)


def _source_table(month: int) -> pa.Table:
    if month == 1:
        dates = [datetime(2024, 1, 1)] * 3
        delays = [16.0, 15.0, 0.0]
        distances: list[float | None] = [100.0, None, 300.0]
    else:
        dates = [datetime(2024, 2, day) for day in range(1, 30)]
        delays = [0.0] * 29
        delays[11] = 16.0
        delays[19] = 16.0
        delays[28] = 20.0
        distances = [500.0] * 29
        distances[11:] = [10_000.0] * 18

    count = len(dates)
    return pa.table(
        {
            "FlightDate": pa.array(dates, type=pa.timestamp("ns")),
            "Reporting_Airline": ["AA"] * count,
            "Origin": ["AAA"] * count,
            "Dest": ["BBB"] * count,
            "CRSDepTime": [745.0] * count,
            "CRSArrTime": [900.0] * count,
            "CRSElapsedTime": [120.0] * count,
            "Distance": pa.array(distances, type=pa.float64()),
            "ArrDelay": pa.array(delays, type=pa.float64()),
            "Cancelled": [0.0] * count,
            "Diverted": [0.0] * count,
        }
    ).select(SOURCE_COLUMNS)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_split_boundaries_are_date_based_and_inclusive() -> None:
    assert _split_for_date(date(2024, 1, 1)) == "train"
    assert _split_for_date(date(2024, 2, 11)) == "train"
    assert _split_for_date(date(2024, 2, 12)) == "validation"
    assert _split_for_date(date(2024, 2, 20)) == "validation"
    assert _split_for_date(date(2024, 2, 21)) == "test"
    assert _split_for_date(date(2024, 2, 29)) == "test"


def test_combined_dataset_reconciles_features_splits_and_manifest(
    tmp_path: Path,
) -> None:
    january_path = tmp_path / "january.parquet"
    february_path = tmp_path / "february.parquet"
    pq.write_table(_source_table(1), january_path)
    pq.write_table(_source_table(2), february_path)
    january_hash = _sha256(january_path)
    february_hash = _sha256(february_path)
    output_path = tmp_path / "combined.parquet"
    manifest_path = tmp_path / "combined.json"

    result = build_combined_feature_dataset(
        inputs=((1, january_path), (2, february_path)),
        output_path=output_path,
        manifest_path=manifest_path,
        expected_dates={
            1: (date(2024, 1, 1), date(2024, 1, 1)),
            2: (date(2024, 2, 1), date(2024, 2, 29)),
        },
        expected_source_metrics={
            "total_flights": 32,
            "cancelled_flights": 0,
            "diverted_flights": 0,
            "eligible_delay_records": 32,
            "delayed_flights": 4,
            "non_delayed_eligible_flights": 28,
        },
        expected_partitions={
            "train": {"rows": 14, "delayed": 1, "non_delayed": 13},
            "validation": {"rows": 9, "delayed": 2, "non_delayed": 7},
            "test": {"rows": 9, "delayed": 1, "non_delayed": 8},
        },
    )

    table = pq.read_table(output_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert table.num_rows == result["rows_written"] == 32
    assert table.column_names == [
        "flight_date",
        "split",
        TARGET_COLUMN,
        *FEATURE_ALLOWLIST,
    ]
    assert len(FEATURE_ALLOWLIST) == 21
    assert not set(FEATURE_ALLOWLIST) & LEAKAGE_DENYLIST
    assert not set(table.column_names[3:]) & LEAKAGE_DENYLIST
    assert table[TARGET_COLUMN].to_pylist().count(1) == 4
    assert table[TARGET_COLUMN].to_pylist().count(0) == 28
    assert all(table[name].null_count == 0 for name in FEATURE_ALLOWLIST)

    rows_by_date: dict[date, set[str]] = {}
    for flight_date, split in zip(
        table["flight_date"].to_pylist(), table["split"].to_pylist()
    ):
        rows_by_date.setdefault(flight_date, set()).add(split)
    assert all(len(splits) == 1 for splits in rows_by_date.values())
    assert set(rows_by_date) == {
        date(2024, 1, 1),
        *(date(2024, 2, day) for day in range(1, 30)),
    }

    assert result["partitions"] == manifest["split_strategy"]["counts"]
    assert result["partitions"] == {
        "train": {
            "rows": 14,
            "delayed": 1,
            "non_delayed": 13,
            "start_date": "2024-01-01",
            "end_date": "2024-02-11",
        },
        "validation": {
            "rows": 9,
            "delayed": 2,
            "non_delayed": 7,
            "start_date": "2024-02-12",
            "end_date": "2024-02-20",
        },
        "test": {
            "rows": 9,
            "delayed": 1,
            "non_delayed": 8,
            "start_date": "2024-02-21",
            "end_date": "2024-02-29",
        },
    }
    assert manifest["target"]["definition"] == (
        "1 when ArrDelay > 15 minutes; otherwise 0."
    )
    assert manifest["features"]["count"] == len(FEATURE_ALLOWLIST) == 21
    assert manifest["features"]["allowlist"] == list(FEATURE_ALLOWLIST)
    assert manifest["numeric_imputation"]["fit_partition"] == "train"
    assert manifest["numeric_imputation"]["fit_rows"] == 14
    assert manifest["numeric_imputation"]["medians"]["distance_miles"] == 500.0
    assert manifest["source_datasets"]["2024-01"]["sha256"] == january_hash
    assert manifest["source_datasets"]["2024-02"]["sha256"] == february_hash
    assert manifest["output_sha256"] == _sha256(output_path)
    assert _sha256(january_path) == january_hash
    assert _sha256(february_path) == february_hash


def test_default_outputs_are_separate_from_january_artifacts() -> None:
    assert OUTPUT_PATH.name == "flight_delay_features_2024_01_02.parquet"
    assert OUTPUT_MANIFEST.name == "feature_manifest_2024_01_02.json"
    assert OUTPUT_PATH != OUTPUT_MANIFEST
