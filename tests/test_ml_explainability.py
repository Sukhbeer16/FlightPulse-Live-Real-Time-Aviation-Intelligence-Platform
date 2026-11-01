"""Tests for Phase 4.3 validation-only explainability helpers."""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from pipelines.ml.explain_models import (
    _aggregate_feature_values,
    _assert_hashes_unchanged,
    _calibration_experiment,
    _apply_window_imputation,
    _fit_window_imputation_medians,
    _sha256_file,
    _unweighted_logistic_importances,
    _validate_existing_output,
    calculate_probability_calibration,
    calculate_threshold_metrics,
    extract_global_importances,
    group_performance_table,
)
from pipelines.ml.feature_dataset import (
    FEATURE_ALLOWLIST,
    NUMERIC_FEATURES,
)
from pipelines.ml.train_models import make_preprocessor, validate_feature_names


def _features(rows: int = 40) -> pd.DataFrame:
    data: dict[str, object] = {
        "Reporting_Airline": pd.Series(
            ["AA", "DL"] * (rows // 2), dtype="category"
        ),
        "Origin": pd.Series(["JFK", "ATL"] * (rows // 2), dtype="category"),
        "Dest": pd.Series(["LAX", "ORD"] * (rows // 2), dtype="category"),
    }
    for index, name in enumerate(NUMERIC_FEATURES):
        data[name] = np.arange(rows, dtype=np.float32) + index
        data[f"is_missing_{name}"] = np.zeros(rows, dtype=np.int8)
    return pd.DataFrame(data).loc[:, FEATURE_ALLOWLIST]


def test_grouped_one_hot_importance_maps_to_original_feature() -> None:
    aggregate = _aggregate_feature_values(
        [
            "Reporting_Airline_AA",
            "Reporting_Airline_DL",
            "Origin_JFK",
            "distance_miles",
        ],
        [0.2, -0.3, 0.4, 0.1],
        absolute=True,
    )

    assert aggregate == {
        "Reporting_Airline": pytest.approx(0.5),
        "Origin": pytest.approx(0.4),
        "distance_miles": pytest.approx(0.1),
    }


def test_feature_importance_extracts_coefficients_with_source_names() -> None:
    frame = _features()
    labels = np.asarray([0, 1] * 20, dtype=np.int8)
    pipeline = Pipeline(
        [
            ("preprocessor", make_preprocessor()),
            ("classifier", LogisticRegression(random_state=7)),
        ]
    )
    pipeline.fit(frame, labels)

    summary, details = extract_global_importances(
        {"logistic_regression": pipeline}
    )

    assert set(summary["source_feature"]).issubset(FEATURE_ALLOWLIST)
    assert set(details["source_feature"]).issubset(FEATURE_ALLOWLIST)
    assert {"Reporting_Airline", "Origin", "Dest"}.issubset(
        set(summary["source_feature"])
    )
    assert set(summary["method"]) == {"sum_absolute_logistic_coefficients"}


def test_unweighted_coefficients_are_reused_and_mapped_to_source_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipelines.ml import explain_models

    saved = pd.DataFrame(
        {
            "model_candidate": ["logistic_regression_unweighted"] * 3,
            "feature": [
                "Reporting_Airline_AA",
                "Reporting_Airline_DL",
                "distance_miles",
            ],
            "method": ["logistic_regression_coefficient"] * 3,
            "value": [0.2, -0.3, 0.1],
            "absolute_value": [0.2, 0.3, 0.1],
        }
    )
    monkeypatch.setattr(explain_models.pd, "read_csv", lambda _path: saved)

    summary, details, coefficients = _unweighted_logistic_importances()

    assert set(summary["model"]) == {"logistic_regression_unweighted"}
    assert set(summary["source_feature"]) == {"Reporting_Airline", "distance_miles"}
    assert details["value"].tolist() == [0.2, -0.3, 0.1]
    assert set(coefficients["direction"]) == {"positive", "negative"}


def test_threshold_metrics_report_incremental_detections_and_false_alarms() -> None:
    result = calculate_threshold_metrics(
        [0, 0, 0, 1, 1, 1],
        [0.05, 0.12, 0.42, 0.18, 0.44, 0.80],
        thresholds=[0.10, 0.50],
    ).set_index("threshold")

    assert result.loc[0.50, "true_positive"] == 1
    assert result.loc[0.50, "false_positive"] == 0
    assert result.loc[0.10, "additional_delayed_detected_vs_0_5"] == 2
    assert result.loc[0.10, "additional_false_positives_vs_0_5"] == 2
    assert result.loc[0.10, "recall"] == pytest.approx(1.0)
    assert result.loc[0.10, "precision"] == pytest.approx(3 / 5)


def test_group_metrics_exclude_groups_below_minimum_size() -> None:
    labels = np.asarray([1, 0, 1, 0, 1, 0], dtype=np.int8)
    probabilities = np.asarray([0.8, 0.2, 0.6, 0.7, 0.1, 0.4])
    groups = ["large"] * 4 + ["small"] * 2

    table, coverage = group_performance_table(
        labels,
        probabilities,
        groups,
        dimension="airline",
        minimum_group_size=3,
    )

    assert table["group"].tolist() == ["large"]
    assert table.loc[0, "flights"] == 4
    assert table.loc[0, "actual_delayed_rate"] == pytest.approx(0.5)
    assert table.loc[0, "predicted_delayed_rate"] == pytest.approx(0.75)
    assert coverage == {
        "minimum_group_size": 3,
        "groups_reported": 1,
        "groups_omitted_below_minimum": 1,
        "flights_in_omitted_groups": 2,
    }


def test_window_imputation_uses_only_observed_base_fit_values() -> None:
    frame = _features(4)
    frame["distance_miles"] = [100.0, 900.0, 450.0, 450.0]
    frame["is_missing_distance_miles"] = [0, 0, 1, 1]

    medians = _fit_window_imputation_medians(frame)
    _apply_window_imputation(frame, medians)

    assert medians["distance_miles"] == 500.0
    assert frame["distance_miles"].tolist() == [100.0, 900.0, 500.0, 500.0]


def test_probability_calibration_reports_brier_and_expected_error() -> None:
    metrics, bins = calculate_probability_calibration(
        [0, 0, 1, 1],
        [0.1, 0.4, 0.6, 0.9],
        bin_count=2,
    )

    assert metrics["rows"] == 4
    assert metrics["positive_prevalence"] == 0.5
    assert metrics["brier_score"] == pytest.approx(0.085)
    assert metrics["expected_calibration_error_equal_frequency"] == pytest.approx(0.25)
    assert bins["count"].sum() == 4
    assert bins["observed_delayed_rate"].tolist() == [0.0, 1.0]


def test_sigmoid_calibration_uses_disjoint_training_date_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipelines.ml import explain_models

    frame = _features()
    labels = np.asarray([0, 1] * 20, dtype=np.int8)

    def make_partition(start: str) -> pa.Table:
        date_values = pd.date_range(start, periods=21, freq="D").date
        dates = np.resize(date_values, len(labels))
        partition = frame.copy()
        partition.insert(0, "flight_date", dates)
        partition.insert(1, "split", "train")
        partition.insert(2, "target_arr_delay_gt_15", labels)
        return pa.Table.from_pandas(partition, preserve_index=False)

    early = make_partition("2024-01-01")
    later = make_partition("2024-01-22")
    queried_filters: list[list[tuple[str, str, object]]] = []

    def read_table(_path: object, *, columns: list[str], filters: list[tuple[str, str, object]]) -> pa.Table:
        queried_filters.append(filters)
        selected = early if filters[-1][1] == "<=" else later
        return selected.select(columns)

    monkeypatch.setattr(explain_models.pq, "read_table", read_table)
    selected_pipeline = Pipeline(
        [
            ("preprocessor", make_preprocessor()),
            (
                "classifier",
                LogisticRegression(class_weight="balanced", random_state=7),
            ),
        ]
    )
    baseline = np.full(len(labels), 0.3)

    summary, bins, calibrated = _calibration_experiment(
        selected_pipeline,
        frame,
        labels,
        baseline,
    )

    assert queried_filters == [
        [("split", "=", "train"), ("flight_date", "<=", pd.Timestamp("2024-01-21").date())],
        [("split", "=", "train"), ("flight_date", ">", pd.Timestamp("2024-01-21").date())],
    ]
    assert summary["base_fit_rows"] == 40
    assert summary["calibration_fit_rows"] == 40
    assert summary["base_fit_date_range"] == ["2024-01-01", "2024-01-21"]
    assert summary["calibration_date_range"] == ["2024-01-22", "2024-02-11"]
    assert summary["validation_only_assessment"] is True
    assert set(bins["model"]) == {
        "saved_phase42_balanced_logistic",
        "chronological_base_uncalibrated",
        "training_only_sigmoid_calibration",
    }
    assert calibrated.shape == labels.shape
    assert np.isfinite(calibrated).all()


def test_leakage_contract_and_phase42_hash_guard() -> None:
    validate_feature_names(FEATURE_ALLOWLIST)
    with pytest.raises(ValueError, match="exactly match"):
        validate_feature_names([*FEATURE_ALLOWLIST, "flight_date"])
    with pytest.raises(ValueError, match="changed"):
        _assert_hashes_unchanged({"model.joblib": "before"}, {"model.joblib": "after"})
    _assert_hashes_unchanged({"model.joblib": "same"}, {"model.joblib": "same"})


def test_existing_phase43_outputs_require_valid_provenance(tmp_path) -> None:
    output = tmp_path / "phase4_3"
    output.mkdir()
    artifact = output / "result.csv"
    artifact.write_text("measured,result\n", encoding="utf-8")
    manifest = {
        "validation_only": True,
        "test_partition_loaded_or_evaluated": False,
        "output_artifacts": {
            artifact.name: {
                "sha256": _sha256_file(artifact),
                "size_bytes": artifact.stat().st_size,
            }
        },
    }
    (output / "analysis_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    _validate_existing_output(output)
    artifact.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity check"):
        _validate_existing_output(output)
