"""Tests for leakage-safe BTS model-dataset preparation."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pipelines.ml.feature_dataset import (
    CATEGORICAL_FEATURES,
    FEATURE_ALLOWLIST,
    LEAKAGE_DENYLIST,
    MISSING_CATEGORY,
    MISSING_INDICATOR_FEATURES,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    _atomic_write_parquet,
    build_feature_table,
    parse_scheduled_hhmm,
)


def _synthetic_source() -> pa.Table:
    dates = [date(2024, 1, day) for day in range(1, 32)]
    dates.extend([date(2024, 1, 31)] * 3)
    count = len(dates)
    cancelled = [0.0] * count
    diverted = [0.0] * count
    delays: list[float | None] = [15.0] * count
    cancelled[-3] = 1.0
    diverted[-2] = 1.0
    delays[-3] = None
    delays[-1] = None
    delays[0] = 16.0
    departure_times: list[float | None] = [5.0] * count
    departure_times[0] = None
    departure_times[1] = 30.0
    departure_times[21] = 2_359.0
    departure_times[26] = 2_400.0
    arrival_times: list[float | None] = [745.0] * count
    arrival_times[0] = 2_359.0
    elapsed: list[float | None] = [100.0] * count
    elapsed[0] = None
    elapsed[21] = 1_900.0
    distance: list[float | None] = [100.0] * count
    distance[0] = None
    distance[2] = 200.0
    distance[21] = 19_999.0
    airlines: list[str | None] = ["AA"] * count
    airlines[1] = None
    origins = ["AAA"] * count
    origins[2] = "   "
    destinations = ["BBB"] * count

    return pa.table(
        {
            "FlightDate": pa.array(
                [datetime.combine(value, datetime.min.time()) for value in dates],
                type=pa.timestamp("ns"),
            ),
            "Reporting_Airline": pa.array(airlines, type=pa.string()),
            "Origin": pa.array(origins, type=pa.string()),
            "Dest": pa.array(destinations, type=pa.string()),
            "CRSDepTime": pa.array(departure_times, type=pa.float64()),
            "CRSArrTime": pa.array(arrival_times, type=pa.float64()),
            "CRSElapsedTime": pa.array(elapsed, type=pa.float64()),
            "Distance": pa.array(distance, type=pa.float64()),
            "ArrDelay": pa.array(delays, type=pa.float64()),
            "Cancelled": pa.array(cancelled, type=pa.float64()),
            "Diverted": pa.array(diverted, type=pa.float64()),
        }
    )


def test_scheduled_hhmm_parsing_handles_edges_and_invalid_values() -> None:
    values = parse_scheduled_hhmm(
        [5, 30, 745, 2359, 2400, 1260, 2401, -1, 7.5, None, float("nan")]
    )

    assert values.to_pylist() == [
        5,
        30,
        465,
        1_439,
        0,
        None,
        None,
        None,
        None,
        None,
        None,
    ]


def test_feature_table_reconciles_eligibility_and_target_counts() -> None:
    table, summary = build_feature_table(_synthetic_source())

    assert summary["source_metrics"]["total_flights"] == 34
    assert summary["source_metrics"]["cancelled_flights"] == 1
    assert summary["source_metrics"]["diverted_flights"] == 1
    assert summary["eligible_rows"] == 31
    assert summary["delayed_rows"] == 1
    assert summary["non_delayed_rows"] == 30
    assert table.num_rows == 31
    assert table[TARGET_COLUMN].null_count == 0
    assert set(table[TARGET_COLUMN].to_pylist()) == {0, 1}


def test_feature_matrix_is_allowlisted_and_has_no_leakage_fields() -> None:
    table, _ = build_feature_table(_synthetic_source())
    feature_columns = table.column_names[3:]

    assert feature_columns == list(FEATURE_ALLOWLIST)
    assert not set(feature_columns) & LEAKAGE_DENYLIST
    assert TARGET_COLUMN not in FEATURE_ALLOWLIST
    assert not {
        "ArrDelay",
        "DepDelay",
        "DepTime",
        "ArrTime",
        "Cancelled",
        "Diverted",
        "FlightDate",
    } & set(feature_columns)


def test_missing_features_are_handled_with_train_only_medians() -> None:
    table, summary = build_feature_table(_synthetic_source())
    medians = summary["imputation_medians_fit_on_train_only"]

    assert medians["distance_miles"] == 100.0
    assert medians["scheduled_elapsed_time_minutes"] == 100.0
    assert table["distance_miles"][0].as_py() == 100.0
    assert table["scheduled_elapsed_time_minutes"][0].as_py() == 100.0
    assert table["is_missing_distance_miles"][0].as_py() == 1
    assert table["is_missing_scheduled_elapsed_time_minutes"][0].as_py() == 1
    assert table["Reporting_Airline"][1].as_py() == MISSING_CATEGORY
    assert table["Origin"][2].as_py() == MISSING_CATEGORY
    assert all(table[name].null_count == 0 for name in NUMERIC_FEATURES)
    assert all(table[name].null_count == 0 for name in CATEGORICAL_FEATURES)


def test_chronological_partitions_and_deterministic_feature_values() -> None:
    first, first_summary = build_feature_table(_synthetic_source())
    second, second_summary = build_feature_table(_synthetic_source())

    assert first.equals(second)
    assert first_summary == second_summary
    assert first_summary["split_counts"] == {
        "train": {
            "rows": 21,
            "delayed": 1,
            "non_delayed": 20,
            "start_date": "2024-01-01",
            "end_date": "2024-01-21",
        },
        "validation": {
            "rows": 5,
            "delayed": 0,
            "non_delayed": 5,
            "start_date": "2024-01-22",
            "end_date": "2024-01-26",
        },
        "test": {
            "rows": 5,
            "delayed": 0,
            "non_delayed": 5,
            "start_date": "2024-01-27",
            "end_date": "2024-01-31",
        },
    }


def test_prepared_parquet_is_readable_without_target_as_a_feature(
    tmp_path: Path,
) -> None:
    features, _ = build_feature_table(_synthetic_source())
    path = tmp_path / "features.parquet"

    _atomic_write_parquet(features, path)
    reopened = pq.read_table(path)

    assert reopened.equals(features)
    assert reopened.num_rows == 31
    assert reopened.column_names[3:] == list(FEATURE_ALLOWLIST)
    assert "Cancelled" not in reopened.column_names
    assert "Diverted" not in reopened.column_names
    assert len(MISSING_INDICATOR_FEATURES) == len(NUMERIC_FEATURES)
