"""Tests for annual feature splitting, training-only imputation, and leakage."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipelines.ml.annual_feature_dataset import (
    _collect_training_values,
    _make_feature_table,
    _month_split,
)
from pipelines.ml.feature_dataset import (
    CATEGORICAL_FEATURES,
    FEATURE_ALLOWLIST,
    LEAKAGE_DENYLIST,
    NUMERIC_FEATURES,
    SOURCE_COLUMNS,
    TARGET_COLUMN,
)


def _source_table() -> pa.Table:
    return pa.table(
        {
            "FlightDate": pa.array(
                [
                    datetime(2024, 1, 5),
                    datetime(2024, 2, 5),
                    datetime(2024, 3, 5),
                    datetime(2024, 4, 5),
                ],
                type=pa.timestamp("ns"),
            ),
            "Reporting_Airline": ["AA", "DL", "UA", None],
            "Origin": ["JFK", "ATL", "ORD", "LAX"],
            "Dest": ["LAX", "ORD", "DEN", "SEA"],
            "CRSDepTime": [5, 30, 745, 2359],
            "CRSArrTime": [30, 745, 2359, None],
            "CRSElapsedTime": [100, 120, 140, 160],
            "Distance": [10.0, 20.0, 1_000.0, 2_000.0],
            "ArrDelay": [0.0, 16.0, 30.0, 45.0],
            "Cancelled": [0, 0, 0, 0],
            "Diverted": [0, 0, 0, 0],
        }
    ).select(SOURCE_COLUMNS)


def test_month_split_is_deterministic_and_keeps_months_together() -> None:
    months = list(range(1, 13))

    split = _month_split(months)

    assert split == _month_split(months)
    assert [month for month, name in split.items() if name == "train"] == list(
        range(1, 9)
    )
    assert [month for month, name in split.items() if name == "validation"] == [9, 10]
    assert [month for month, name in split.items() if name == "test"] == [11, 12]


def test_month_split_requires_three_chronological_partitions() -> None:
    with pytest.raises(ValueError, match="At least three validated months"):
        _month_split([1, 2])


def test_feature_matrix_uses_allowlist_and_neutral_missing_categories() -> None:
    source = _source_table()
    split_by_month = {1: "train", 2: "train", 3: "validation", 4: "test"}
    medians = {name: 100.0 for name in NUMERIC_FEATURES}

    result = _make_feature_table(source, split_by_month, medians)

    assert result.column_names[3:] == list(FEATURE_ALLOWLIST)
    assert len(FEATURE_ALLOWLIST) == 21
    assert not (set(result.column_names) & (LEAKAGE_DENYLIST - {TARGET_COLUMN}))
    assert result["Reporting_Airline"][3].as_py() == "__MISSING__"
    assert result["target_arr_delay_gt_15"].to_pylist() == [0, 1, 1, 1]
    assert all(result.column(name).null_count == 0 for name in FEATURE_ALLOWLIST)
    assert set(CATEGORICAL_FEATURES).issubset(FEATURE_ALLOWLIST)


def test_annual_numeric_imputation_uses_training_months_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.parquet"
    pq.write_table(_source_table(), path)
    input_file = pq.ParquetFile(path)
    split_by_month = {1: "train", 2: "train", 3: "validation", 4: "test"}

    values, month_counts, source_totals = _collect_training_values(
        input_file, split_by_month
    )

    distance_median = float(
        np.median(np.concatenate(values["distance_miles"]))
    )
    assert distance_median == 15.0
    assert month_counts["2024-01"]["rows"] == 1
    assert month_counts["2024-02"]["delayed"] == 1
    assert source_totals["eligible_delay_records"] == 4
    assert len(SOURCE_COLUMNS) == 11
