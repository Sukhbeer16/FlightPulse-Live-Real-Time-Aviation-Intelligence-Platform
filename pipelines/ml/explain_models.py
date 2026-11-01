"""Explain saved Phase 4.2 models using validation data only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    fbeta_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression

from pipelines.ml.combined_feature_dataset import (
    OUTPUT_MANIFEST as DATASET_MANIFEST,
    OUTPUT_PATH as DATASET_PATH,
)
from pipelines.ml.feature_dataset import (
    CATEGORICAL_FEATURES,
    FEATURE_ALLOWLIST,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)
from pipelines.ml.train_models import (
    CLASSIFICATION_THRESHOLD,
    EXPECTED_PARTITIONS,
    OUTPUT_DIRECTORY as PHASE42_DIRECTORY,
    _load_partition,
    validate_feature_names,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = ROOT / "data" / "processed" / "ml" / "phase4_3"
PHASE42_FILES = (
    "decision_tree.joblib",
    "experiment_manifest.json",
    "feature_importance.csv",
    "final_test_metrics.json",
    "logistic_regression.joblib",
    "preprocessor.joblib",
    "random_forest.joblib",
    "selected_test_confusion_matrix.png",
    "selected_test_roc_pr.png",
    "selected_validation_confusion_matrix.png",
    "validation_metrics.json",
    "validation_roc_pr.png",
    "xgboost.joblib",
)
MINIMUM_GROUP_SIZE = 500
PERMUTATION_REPEATS = 3
PERMUTATION_SEED = 42
THRESHOLDS = (0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _phase42_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in PHASE42_FILES:
        path = PHASE42_DIRECTORY / name
        if not path.is_file():
            raise FileNotFoundError(f"Expected Phase 4.2 artifact missing: {path}")
        hashes[name] = _sha256_file(path)
    return hashes


def _assert_hashes_unchanged(
    before: Mapping[str, str], after: Mapping[str, str]
) -> None:
    if dict(before) != dict(after):
        raise ValueError("An existing Phase 4.2 artifact changed during analysis.")


def _validate_existing_output(directory: Path) -> None:
    """Only reuse outputs whose manifest proves they are Phase 4.3 artifacts."""
    manifest_path = directory / "analysis_manifest.json"
    if not manifest_path.is_file():
        raise FileExistsError(
            f"Refusing to overwrite an unrecognized Phase 4.3 output directory: {directory}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("output_artifacts")
    if (
        manifest.get("validation_only") is not True
        or manifest.get("test_partition_loaded_or_evaluated") is not False
        or not isinstance(artifacts, dict)
    ):
        raise ValueError("Existing Phase 4.3 manifest does not prove output provenance.")
    existing_names = {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != manifest_path.name
    }
    if existing_names != set(artifacts):
        raise ValueError("Existing Phase 4.3 output files differ from their manifest.")
    for name, metadata in artifacts.items():
        path = directory / name
        if (
            not isinstance(metadata, dict)
            or metadata.get("sha256") != _sha256_file(path)
            or metadata.get("size_bytes") != path.stat().st_size
        ):
            raise ValueError(f"Existing Phase 4.3 output failed integrity check: {name}")


def _load_validation_frame() -> tuple[pd.DataFrame, np.ndarray]:
    """Load only the validation partition and its allowlisted features."""
    manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("validation_status") != "passed":
        raise ValueError("Combined feature dataset manifest is not validated.")
    if manifest.get("numeric_imputation", {}).get("fit_partition") != "train":
        raise ValueError("Combined feature manifest does not prove train-only imputation.")
    if manifest["numeric_imputation"].get("fit_rows") != EXPECTED_PARTITIONS["train"]["rows"]:
        raise ValueError("Combined feature manifest has an unexpected imputation row count.")
    if manifest.get("target", {}).get("column") != TARGET_COLUMN or (
        manifest.get("target", {}).get("definition")
        != "1 when ArrDelay > 15 minutes; otherwise 0."
    ):
        raise ValueError("Combined feature manifest has an unexpected target definition.")
    if manifest.get("split_strategy", {}).get(
        "same_calendar_date_stays_in_one_partition"
    ) is not True:
        raise ValueError("Combined feature manifest does not guarantee date-grouped splits.")
    expected_boundaries = {
        "train": {"start": "2024-01-01", "end": "2024-02-11"},
        "validation": {"start": "2024-02-12", "end": "2024-02-20"},
        "test": {"start": "2024-02-21", "end": "2024-02-29"},
    }
    if manifest.get("split_strategy", {}).get("boundaries_inclusive") != expected_boundaries:
        raise ValueError("Combined feature manifest has unexpected date split boundaries.")
    if manifest.get("output_sha256") != _sha256_file(DATASET_PATH):
        raise ValueError("Combined feature dataset checksum does not match manifest.")
    if manifest.get("features", {}).get("allowlist") != list(FEATURE_ALLOWLIST):
        raise ValueError("Combined feature allowlist differs from the approved list.")
    expected_names = [
        "flight_date",
        "split",
        TARGET_COLUMN,
        *FEATURE_ALLOWLIST,
    ]
    parquet = pq.ParquetFile(DATASET_PATH)
    if parquet.schema_arrow.names != expected_names:
        raise ValueError("Combined feature Parquet schema has unexpected columns.")
    table = pq.read_table(
        DATASET_PATH,
        columns=expected_names,
        filters=[("split", "=", "validation")],
    )
    expected = EXPECTED_PARTITIONS["validation"]
    if table.num_rows != expected["rows"]:
        raise ValueError(
            f"Validation row count mismatch: {table.num_rows} != {expected['rows']}."
        )
    if table[TARGET_COLUMN].null_count or table["flight_date"].null_count:
        raise ValueError("Validation target or date contains null values.")
    dates = table["flight_date"].to_pylist()
    splits = table["split"].to_pylist()
    if any(split != "validation" for split in splits):
        raise ValueError("A non-validation row entered the analysis.")
    if any(not (datetime(2024, 2, 12).date() <= day <= datetime(2024, 2, 20).date()) for day in dates):
        raise ValueError("A validation date lies outside the approved date boundary.")
    labels = np.asarray(
        table[TARGET_COLUMN].to_numpy(zero_copy_only=False), dtype=np.int8
    )
    if (
        np.count_nonzero(labels == 1) != expected["delayed"]
        or np.count_nonzero(labels == 0) != expected["non_delayed"]
    ):
        raise ValueError("Validation target counts do not match the manifest.")
    feature_table = table.select(FEATURE_ALLOWLIST)
    validate_feature_names(feature_table.column_names)
    frame = feature_table.to_pandas(strings_to_categorical=True)
    for name in CATEGORICAL_FEATURES:
        frame[name] = frame[name].astype("category")
    for name in NUMERIC_FEATURES:
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(np.float32)
    if frame.isna().any().any():
        raise ValueError("Validation feature matrix contains nulls.")
    return frame, labels


def _validate_model_pipelines(
    models: Mapping[str, Pipeline],
) -> list[str]:
    names: list[str] | None = None
    for model_name, pipeline in models.items():
        if not isinstance(pipeline, Pipeline):
            raise TypeError(f"Saved {model_name} artifact is not a sklearn Pipeline.")
        fitted_preprocessor = pipeline.named_steps.get("preprocessor")
        input_names = list(getattr(fitted_preprocessor, "feature_names_in_", []))
        validate_feature_names(input_names)
        if names is None:
            names = input_names
        elif input_names != names:
            raise ValueError("Saved model pipelines use inconsistent input columns.")
        classifier = pipeline.named_steps.get("classifier")
        if classifier is None:
            raise ValueError(f"Saved {model_name} pipeline lacks a classifier.")
    return names or []


def _original_feature(transformed_name: str) -> str:
    for categorical in CATEGORICAL_FEATURES:
        prefix = f"{categorical}_"
        if transformed_name.startswith(prefix):
            return categorical
    return transformed_name


def _aggregate_feature_values(
    transformed_names: Sequence[str],
    values: Sequence[float],
    *,
    absolute: bool,
) -> dict[str, float]:
    if len(transformed_names) != len(values):
        raise ValueError("Transformed feature importance lengths do not match.")
    result: dict[str, float] = {}
    for name, value in zip(transformed_names, values):
        original = _original_feature(str(name))
        selected = abs(float(value)) if absolute else float(value)
        result[original] = result.get(original, 0.0) + selected
    return result


def extract_global_importances(
    models: Mapping[str, Pipeline],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract coefficients and tree importances, aggregating one-hot columns."""
    rows: list[dict[str, Any]] = []
    model_details: list[dict[str, Any]] = []
    for family, pipeline in models.items():
        estimator = pipeline.named_steps["classifier"]
        names = [str(name) for name in pipeline.named_steps["preprocessor"].get_feature_names_out()]
        if family == "xgboost":
            booster = estimator.get_booster()[: int(estimator.best_iteration) + 1]
            score_maps = {
                kind: booster.get_score(importance_type=kind)
                for kind in ("gain", "weight", "cover")
            }
            gain = np.zeros(len(names), dtype=np.float64)
            for kind, scores in score_maps.items():
                for key, value in scores.items():
                    if key.startswith("f"):
                        index = int(key[1:])
                    elif key in names:
                        index = names.index(key)
                    else:
                        raise ValueError(f"XGBoost returned unexpected feature key {key}.")
                    if not 0 <= index < len(names):
                        raise ValueError(f"XGBoost returned unexpected feature key {key}.")
                    model_details.append(
                        {
                            "model": family,
                            "transformed_feature": names[index],
                            "source_feature": _original_feature(names[index]),
                            "method": f"xgboost_{kind}",
                            "value": float(value),
                        }
                    )
                    if kind == "gain":
                        gain[index] = float(value)
            aggregate = _aggregate_feature_values(names, gain, absolute=False)
            method = "summed_xgboost_gain"
        elif hasattr(estimator, "coef_"):
            coefficients = np.asarray(estimator.coef_).reshape(-1)
            if len(coefficients) != len(names):
                raise ValueError(f"{family} coefficient count does not match transformed features.")
            for name, coefficient in zip(names, coefficients):
                model_details.append(
                    {
                        "model": family,
                        "transformed_feature": name,
                        "source_feature": _original_feature(name),
                        "method": "signed_logistic_coefficient",
                        "value": float(coefficient),
                    }
                )
            aggregate = _aggregate_feature_values(names, coefficients, absolute=True)
            method = "sum_absolute_logistic_coefficients"
        elif hasattr(estimator, "feature_importances_"):
            importances = np.asarray(estimator.feature_importances_).reshape(-1)
            if len(importances) != len(names):
                raise ValueError(f"{family} importance count does not match transformed features.")
            for name, value in zip(names, importances):
                model_details.append(
                    {
                        "model": family,
                        "transformed_feature": name,
                        "source_feature": _original_feature(name),
                        "method": "impurity_importance",
                        "value": float(value),
                    }
                )
            aggregate = _aggregate_feature_values(names, importances, absolute=False)
            method = "summed_impurity_importance"
        else:
            continue

        total = sum(aggregate.values())
        for feature, raw_value in aggregate.items():
            rows.append(
                {
                    "model": family,
                    "source_feature": feature,
                    "method": method,
                    "raw_importance": raw_value,
                    "normalized_importance": (
                        raw_value / total if total else 0.0
                    ),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(model_details)


def _unweighted_logistic_importances() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reuse the Phase 4.2 saved coefficient table for the unsaved candidate."""
    path = PHASE42_DIRECTORY / "feature_importance.csv"
    saved = pd.read_csv(path)
    candidate = saved[saved["model_candidate"] == "logistic_regression_unweighted"]
    if candidate.empty or set(candidate["method"]) != {"logistic_regression_coefficient"}:
        raise ValueError("Saved unweighted Logistic Regression coefficients are unavailable.")
    names = candidate["feature"].astype(str).tolist()
    values = candidate["value"].to_numpy(dtype=np.float64)
    if len(names) != len(set(names)) or not set(
        _original_feature(name) for name in names
    ).issubset(FEATURE_ALLOWLIST):
        raise ValueError("Saved unweighted Logistic Regression features are unexpected.")
    aggregate = _aggregate_feature_values(names, values, absolute=True)
    total = sum(aggregate.values())
    summary = pd.DataFrame(
        [
            {
                "model": "logistic_regression_unweighted",
                "source_feature": feature,
                "method": "sum_absolute_logistic_coefficients",
                "raw_importance": value,
                "normalized_importance": value / total if total else 0.0,
            }
            for feature, value in aggregate.items()
        ]
    )
    details = pd.DataFrame(
        [
            {
                "model": "logistic_regression_unweighted",
                "transformed_feature": name,
                "source_feature": _original_feature(name),
                "method": "signed_logistic_coefficient",
                "value": float(value),
            }
            for name, value in zip(names, values)
        ]
    )
    coefficients = pd.DataFrame(
        {
            "transformed_feature": names,
            "source_feature": [_original_feature(name) for name in names],
            "coefficient": values,
        }
    )
    coefficients = pd.concat(
        [
            coefficients.nlargest(20, "coefficient").assign(direction="positive"),
            coefficients.nsmallest(20, "coefficient").assign(direction="negative"),
        ],
        ignore_index=True,
    )
    return summary, details, coefficients


def calculate_threshold_metrics(
    labels: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    thresholds: Sequence[float] = THRESHOLDS,
    baseline_threshold: float = CLASSIFICATION_THRESHOLD,
) -> pd.DataFrame:
    """Compare threshold trade-offs and incremental TP/FP versus 0.5."""
    y = np.asarray(labels, dtype=np.int8)
    p = np.asarray(probabilities, dtype=np.float64)
    if y.ndim != 1 or p.ndim != 1 or len(y) != len(p) or not len(y):
        raise ValueError("Labels and probabilities must be non-empty matching arrays.")
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Predicted probabilities must be finite values in [0, 1].")
    baseline_pred = p >= baseline_threshold
    baseline_tp = int(np.count_nonzero((y == 1) & baseline_pred))
    baseline_fp = int(np.count_nonzero((y == 0) & baseline_pred))
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        predicted = p >= threshold
        tp = int(np.count_nonzero((y == 1) & predicted))
        fp = int(np.count_nonzero((y == 0) & predicted))
        fn = int(np.count_nonzero((y == 1) & ~predicted))
        tn = int(np.count_nonzero((y == 0) & ~predicted))
        rows.append(
            {
                "threshold": float(threshold),
                "flights_flagged": tp + fp,
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "true_negative": tn,
                "precision": float(precision_score(y, predicted, zero_division=0)),
                "recall": float(recall_score(y, predicted, zero_division=0)),
                "f1": float(f1_score(y, predicted, zero_division=0)),
                "f2": float(fbeta_score(y, predicted, beta=2, zero_division=0)),
                "additional_delayed_detected_vs_0_5": tp - baseline_tp,
                "additional_false_positives_vs_0_5": fp - baseline_fp,
            }
        )
    return pd.DataFrame(rows)


def calculate_probability_calibration(
    labels: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    *,
    bin_count: int = 10,
) -> tuple[dict[str, float], pd.DataFrame]:
    """Return Brier/log-loss/ECE and equal-frequency reliability bins."""
    y = np.asarray(labels, dtype=np.int8)
    p = np.asarray(probabilities, dtype=np.float64)
    if y.ndim != 1 or p.ndim != 1 or len(y) != len(p) or not len(y):
        raise ValueError("Calibration arrays must be non-empty and have equal length.")
    if bin_count < 1:
        raise ValueError("Calibration bin count must be positive.")
    if not set(np.unique(y)).issubset({0, 1}):
        raise ValueError("Calibration labels must be binary 0/1.")
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Calibration probabilities must be finite values in [0, 1].")
    quantiles = np.quantile(p, np.linspace(0, 1, bin_count + 1))
    edges = np.unique(quantiles)
    if len(edges) < 2:
        bin_ids = np.zeros(len(p), dtype=np.int8)
    else:
        bin_ids = np.clip(np.digitize(p, edges[1:-1], right=True), 0, len(edges) - 2)
    rows = []
    ece = 0.0
    for index in np.unique(bin_ids):
        mask = bin_ids == index
        count = int(mask.sum())
        mean_probability = float(p[mask].mean())
        observed_rate = float(y[mask].mean())
        ece += count / len(y) * abs(mean_probability - observed_rate)
        rows.append(
            {
                "bin": int(index + 1),
                "count": count,
                "minimum_probability": float(p[mask].min()),
                "maximum_probability": float(p[mask].max()),
                "mean_predicted_probability": mean_probability,
                "observed_delayed_rate": observed_rate,
            }
        )
    metrics = {
        "rows": int(len(y)),
        "positive_prevalence": float(y.mean()),
        "brier_score": float(brier_score_loss(y, p)),
        "expected_calibration_error_equal_frequency": float(ece),
        "bin_count": int(len(rows)),
    }
    return metrics, pd.DataFrame(rows)


def group_performance_table(
    labels: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    groups: Sequence[Any],
    *,
    dimension: str,
    minimum_group_size: int = MINIMUM_GROUP_SIZE,
    threshold: float = CLASSIFICATION_THRESHOLD,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Calculate unweighted retrospective metrics, excluding undersized groups."""
    y = np.asarray(labels, dtype=np.int8)
    p = np.asarray(probabilities, dtype=np.float64)
    group_values = np.asarray(groups, dtype=object)
    if not (len(y) == len(p) == len(group_values)):
        raise ValueError("Labels, probabilities, and groups must have matching lengths.")
    predicted = (p >= threshold).astype(np.int8)
    frame = pd.DataFrame(
        {
            "group": pd.Series(group_values, dtype="object").fillna("__MISSING__"),
            "actual": y,
            "predicted": predicted,
        }
    )
    rows: list[dict[str, Any]] = []
    omitted_groups = 0
    omitted_flights = 0
    for value, subset in frame.groupby("group", sort=True, observed=True):
        count = len(subset)
        if count < minimum_group_size:
            omitted_groups += 1
            omitted_flights += count
            continue
        actual = subset["actual"].to_numpy()
        prediction = subset["predicted"].to_numpy()
        tp = int(np.count_nonzero((actual == 1) & (prediction == 1)))
        fp = int(np.count_nonzero((actual == 0) & (prediction == 1)))
        fn = int(np.count_nonzero((actual == 1) & (prediction == 0)))
        rows.append(
            {
                "dimension": dimension,
                "group": str(value),
                "flights": count,
                "actual_delayed": int(actual.sum()),
                "predicted_delayed": int(prediction.sum()),
                "actual_delayed_rate": float(actual.mean()),
                "predicted_delayed_rate": float(prediction.mean()),
                "precision": float(precision_score(actual, prediction, zero_division=0)),
                "recall": float(recall_score(actual, prediction, zero_division=0)),
                "f1": float(f1_score(actual, prediction, zero_division=0)),
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
            }
        )
    return pd.DataFrame(rows), {
        "minimum_group_size": minimum_group_size,
        "groups_reported": len(rows),
        "groups_omitted_below_minimum": omitted_groups,
        "flights_in_omitted_groups": omitted_flights,
    }


def _scheduled_departure_bands(frame: pd.DataFrame) -> np.ndarray:
    sine = frame["scheduled_departure_sin"].to_numpy(dtype=np.float64)
    cosine = frame["scheduled_departure_cos"].to_numpy(dtype=np.float64)
    angle = np.mod(np.arctan2(sine, cosine), 2 * np.pi)
    minutes = angle * (1_440 / (2 * np.pi))
    hours = np.floor(minutes / 60).astype(np.int16)
    bands = np.select(
        [hours < 6, hours < 12, hours < 18],
        ["00-05", "06-11", "12-17"],
        default="18-23",
    ).astype(object)
    missing = frame["is_missing_scheduled_departure_sin"].to_numpy() > 0
    bands[missing] = "__MISSING__"
    return bands


def _distance_bands(frame: pd.DataFrame) -> np.ndarray:
    distance = frame["distance_miles"].to_numpy(dtype=np.float64)
    bands = np.select(
        [distance <= 250, distance <= 750],
        ["0-250", "251-750"],
        default="751+",
    ).astype(object)
    missing = frame["is_missing_distance_miles"].to_numpy() > 0
    bands[missing] = "__MISSING__"
    return bands


def _top_coefficients(pipeline: Pipeline, top_count: int = 20) -> pd.DataFrame:
    estimator = pipeline.named_steps["classifier"]
    names = [str(value) for value in pipeline.named_steps["preprocessor"].get_feature_names_out()]
    coefficients = np.asarray(estimator.coef_).reshape(-1)
    result = pd.DataFrame(
        {
            "transformed_feature": names,
            "source_feature": [_original_feature(name) for name in names],
            "coefficient": coefficients,
        }
    )
    positive = result.nlargest(top_count, "coefficient").assign(direction="positive")
    negative = result.nsmallest(top_count, "coefficient").assign(direction="negative")
    return pd.concat([positive, negative], ignore_index=True)


def _tree_report(pipeline: Pipeline) -> tuple[dict[str, Any], str]:
    estimator = pipeline.named_steps["classifier"]
    tree = estimator.tree_
    feature_names = [
        str(value)
        for value in pipeline.named_steps["preprocessor"].get_feature_names_out()
    ]
    paths = export_text(
        estimator,
        feature_names=feature_names,
        max_depth=4,
        decimals=3,
    )
    return (
        {
            "node_count": int(tree.node_count),
            "leaf_count": int(np.count_nonzero(tree.children_left == -1)),
            "depth": int(estimator.get_depth()),
            "configured_max_depth": estimator.get_params()["max_depth"],
            "configured_min_samples_leaf": estimator.get_params()["min_samples_leaf"],
            "path_export_max_depth": 4,
        },
        paths,
    )


def export_text(
    estimator: Any,
    *,
    feature_names: Sequence[str],
    max_depth: int,
    decimals: int,
) -> str:
    """Export a compact tree path report using sklearn's actual fitted tree."""
    from sklearn.tree import export_text as sklearn_export_text

    return sklearn_export_text(
        estimator,
        feature_names=list(feature_names),
        max_depth=max_depth,
        decimals=decimals,
    )


def _xgboost_report(pipeline: Pipeline) -> tuple[dict[str, Any], pd.DataFrame]:
    estimator = pipeline.named_steps["classifier"]
    result = estimator.evals_result()
    metric_map = result.get("validation_0", {})
    if set(metric_map) != {"aucpr"}:
        raise ValueError(f"Unexpected saved XGBoost validation metrics: {list(metric_map)}")
    values = np.asarray(metric_map["aucpr"], dtype=np.float64)
    if not len(values):
        raise ValueError("Saved XGBoost artifact has no validation history.")
    best_index = int(np.argmax(values))
    best_iteration = int(estimator.best_iteration)
    if best_index != best_iteration or not np.isclose(
        values[best_index], float(estimator.best_score)
    ):
        raise ValueError("XGBoost best-iteration metadata disagrees with saved history.")
    rounds_without_improvement = len(values) - 1 - best_index
    configured_patience = int(estimator.get_params()["early_stopping_rounds"])
    report = {
        "metric": "XGBoost eval_metric=aucpr (not identical implementation to sklearn average precision)",
        "best_iteration_zero_based": best_iteration,
        "best_iteration_one_based": best_iteration + 1,
        "observed_validation_aucpr_at_best": float(values[best_index]),
        "best_score_attribute": float(estimator.best_score),
        "evaluation_rounds_recorded": int(len(values)),
        "validation_aucpr_first_round": float(values[0]),
        "validation_aucpr_last_round": float(values[-1]),
        "rounds_after_best_without_improvement": int(rounds_without_improvement),
        "configured_early_stopping_patience": configured_patience,
        "patience_exhausted": rounds_without_improvement >= configured_patience,
        "boosted_rounds_stored": int(estimator.get_booster().num_boosted_rounds()),
        "effective_best_trees": best_iteration + 1,
    }
    history = pd.DataFrame(
        {
            "iteration_zero_based": np.arange(len(values)),
            "iteration_one_based": np.arange(1, len(values) + 1),
            "validation_aucpr": values,
            "is_best_iteration": np.arange(len(values)) == best_index,
        }
    )
    return report, history


def _write_plots(
    output: Path,
    importance: pd.DataFrame,
    coefficients: pd.DataFrame,
    unweighted_coefficients: pd.DataFrame,
    permutation_importance_table: pd.DataFrame,
    labels: np.ndarray,
    probabilities: np.ndarray,
    calibration_bins: pd.DataFrame,
) -> None:
    model_order = [
        value
        for value in (
            "logistic_regression_unweighted",
            "logistic_regression",
            "decision_tree",
            "random_forest",
            "xgboost",
        )
        if value in set(importance["model"])
    ]
    fig, axes = plt.subplots(
        1, len(model_order), figsize=(5 * len(model_order), 7), squeeze=False
    )
    for axis, model in zip(axes[0], model_order):
        subset = importance[importance["model"] == model]
        top = subset.nlargest(12, "normalized_importance").sort_values(
            "normalized_importance"
        )
        axis.barh(top["source_feature"], top["normalized_importance"])
        axis.set(title=model.replace("_", " "), xlabel="Within-model normalized importance")
        axis.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output / "global_feature_importance.png", dpi=150)
    plt.close(fig)

    permutation_top = permutation_importance_table.nlargest(
        15, "mean_average_precision_drop"
    ).sort_values("mean_average_precision_drop")
    fig, axis = plt.subplots(figsize=(9, 7))
    axis.barh(
        permutation_top["source_feature"],
        permutation_top["mean_average_precision_drop"],
        xerr=permutation_top["std_average_precision_drop"],
    )
    axis.axvline(0, color="black", linewidth=0.8)
    axis.set(
        title="Random Forest validation permutation importance",
        xlabel="Mean average-precision decrease when permuted",
    )
    fig.tight_layout()
    fig.savefig(output / "random_forest_validation_permutation_importance.png", dpi=150)
    plt.close(fig)

    signed = coefficients.sort_values("coefficient")
    fig, axis = plt.subplots(figsize=(9, 8))
    axis.barh(signed["transformed_feature"], signed["coefficient"], color=np.where(signed["coefficient"] >= 0, "#c44e52", "#4c72b0"))
    axis.axvline(0, color="black", linewidth=0.8)
    axis.set(title="Balanced Logistic Regression: strongest signed coefficients", xlabel="Coefficient (scaled numeric / one-hot encoded)")
    fig.tight_layout()
    fig.savefig(output / "logistic_regression_coefficients.png", dpi=150)
    plt.close(fig)

    signed = unweighted_coefficients.sort_values("coefficient")
    fig, axis = plt.subplots(figsize=(9, 8))
    axis.barh(
        signed["transformed_feature"],
        signed["coefficient"],
        color=np.where(
            signed["coefficient"] >= 0, "#c44e52", "#4c72b0"
        ),
    )
    axis.axvline(0, color="black", linewidth=0.8)
    axis.set(
        title="Unweighted Logistic Regression: strongest signed coefficients",
        xlabel="Coefficient (scaled numeric / one-hot encoded)",
    )
    fig.tight_layout()
    fig.savefig(output / "logistic_regression_unweighted_coefficients.png", dpi=150)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(8, 5))
    axis.hist(probabilities[labels == 0], bins=40, alpha=0.65, density=True, label="Non-delayed")
    axis.hist(probabilities[labels == 1], bins=40, alpha=0.65, density=True, label="Delayed")
    axis.axvline(CLASSIFICATION_THRESHOLD, color="black", linestyle="--", label="0.50 threshold")
    axis.set(title="Selected model validation probability distributions", xlabel="Predicted probability", ylabel="Density")
    axis.legend()
    fig.tight_layout()
    fig.savefig(output / "validation_probability_distributions.png", dpi=150)
    plt.close(fig)

    precision, recall, _ = precision_recall_curve(labels, probabilities)
    fig, axis = plt.subplots(figsize=(7, 5))
    axis.plot(recall, precision, label="Balanced Logistic Regression")
    axis.axhline(labels.mean(), linestyle="--", color="gray", label="Positive prevalence")
    axis.set(title="Validation precision-recall curve", xlabel="Recall", ylabel="Precision")
    axis.legend()
    axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output / "validation_precision_recall.png", dpi=150)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(7, 5))
    for model, subset in calibration_bins.groupby("model", sort=False):
        axis.plot(
            subset["mean_predicted_probability"],
            subset["observed_delayed_rate"],
            marker="o",
            label=model.replace("_", " "),
        )
    axis.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect calibration")
    axis.set(title="Validation reliability diagram", xlabel="Mean predicted probability", ylabel="Observed delayed rate")
    axis.legend()
    axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output / "validation_calibration.png", dpi=150)
    plt.close(fig)


def _validation_errors(
    frame: pd.DataFrame,
    labels: np.ndarray,
    probabilities: np.ndarray,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    predicted = (probabilities >= CLASSIFICATION_THRESHOLD).astype(np.int8)
    error_type = np.select(
        [
            (labels == 1) & (predicted == 1),
            (labels == 0) & (predicted == 1),
            (labels == 1) & (predicted == 0),
        ],
        ["true_positive", "false_positive", "false_negative"],
        default="true_negative",
    )
    errors = frame.loc[:, FEATURE_ALLOWLIST].copy()
    errors.insert(0, "prediction_error", error_type)
    errors.insert(0, "predicted_delayed", predicted)
    errors.insert(0, "predicted_probability", probabilities)
    errors.insert(0, TARGET_COLUMN, labels)
    counts = dict(Counter(error_type))
    class_summaries: dict[str, Any] = {}
    for label, name in ((0, "non_delayed"), (1, "delayed")):
        values = probabilities[labels == label]
        class_summaries[name] = {
            "rows": int(len(values)),
            "minimum": float(values.min()),
            "q10": float(np.quantile(values, 0.10)),
            "median": float(np.median(values)),
            "q90": float(np.quantile(values, 0.90)),
            "maximum": float(values.max()),
        }
    return errors, {
        "confusion_counts": counts,
        "probability_by_actual_class": class_summaries,
    }


def _calibration_experiment(
    selected_pipeline: Pipeline,
    validation_frame: pd.DataFrame,
    validation_labels: np.ndarray,
    baseline_probabilities: np.ndarray,
) -> tuple[dict[str, Any], pd.DataFrame, np.ndarray]:
    """Fit a base model and sigmoid calibrator on disjoint training date windows."""
    columns = ["flight_date", "split", TARGET_COLUMN, *FEATURE_ALLOWLIST]
    calibration_cut = datetime(2024, 1, 21).date()
    early = pq.read_table(
        DATASET_PATH,
        columns=columns,
        filters=[
            ("split", "=", "train"),
            ("flight_date", "<=", calibration_cut),
        ],
    )
    later = pq.read_table(
        DATASET_PATH,
        columns=columns,
        filters=[
            ("split", "=", "train"),
            ("flight_date", ">", calibration_cut),
        ],
    )
    if early.num_rows == 0 or later.num_rows == 0:
        raise ValueError("Chronological training-only calibration split is empty.")
    if any(value != "train" for value in early["split"].unique().to_pylist()) or any(
        value != "train" for value in later["split"].unique().to_pylist()
    ):
        raise ValueError("Calibration experiment included a non-training row.")

    early_min = pc.min(early["flight_date"]).as_py()
    early_max = pc.max(early["flight_date"]).as_py()
    later_min = pc.min(later["flight_date"]).as_py()
    later_max = pc.max(later["flight_date"]).as_py()
    if early_max >= later_min:
        raise ValueError("Calibration fit/calibration windows are not chronological.")
    early_rows = int(early.num_rows)
    early_features = _frame_from_arrow(early.select(FEATURE_ALLOWLIST))
    early_y = np.asarray(early[TARGET_COLUMN].to_numpy(zero_copy_only=False), dtype=np.int8)
    del early
    calibration_imputation_medians = _fit_window_imputation_medians(early_features)
    _apply_window_imputation(early_features, calibration_imputation_medians)
    base_pipeline = clone_pipeline(selected_pipeline)
    base_pipeline.fit(early_features, early_y)
    del early_features, early_y

    later_features = _frame_from_arrow(later.select(FEATURE_ALLOWLIST))
    later_y = np.asarray(later[TARGET_COLUMN].to_numpy(zero_copy_only=False), dtype=np.int8)
    later_rows = len(later_y)
    del later
    _apply_window_imputation(later_features, calibration_imputation_medians)
    later_scores = base_pipeline.decision_function(later_features).reshape(-1, 1)
    del later_features
    sigmoid = LogisticRegression(
        C=1_000_000,
        solver="lbfgs",
        max_iter=1_000,
    )
    sigmoid.fit(later_scores, later_y)
    del later_scores, later_y
    calibration_validation_frame = validation_frame.copy()
    _apply_window_imputation(
        calibration_validation_frame, calibration_imputation_medians
    )
    validation_scores = base_pipeline.decision_function(
        calibration_validation_frame
    ).reshape(-1, 1)
    del calibration_validation_frame
    calibrated_probabilities = sigmoid.predict_proba(validation_scores)[:, 1]
    del validation_scores

    original_summary, original_bins = calculate_probability_calibration(
        validation_labels, baseline_probabilities
    )
    chronological_probabilities = base_pipeline.predict_proba(
        _validation_with_imputation(validation_frame, calibration_imputation_medians)
    )[:, 1]
    chronological_summary, chronological_bins = calculate_probability_calibration(
        validation_labels, chronological_probabilities
    )
    calibrated_summary, calibrated_bins = calculate_probability_calibration(
        validation_labels, calibrated_probabilities
    )
    original_summary["log_loss"] = float(
        log_loss(validation_labels, baseline_probabilities)
    )
    chronological_summary["log_loss"] = float(
        log_loss(validation_labels, chronological_probabilities)
    )
    calibrated_summary["log_loss"] = float(
        log_loss(validation_labels, calibrated_probabilities)
    )
    original_summary["average_precision"] = float(
        average_precision_score(validation_labels, baseline_probabilities)
    )
    original_summary["roc_auc"] = float(
        roc_auc_score(validation_labels, baseline_probabilities)
    )
    chronological_summary["average_precision"] = float(
        average_precision_score(validation_labels, chronological_probabilities)
    )
    chronological_summary["roc_auc"] = float(
        roc_auc_score(validation_labels, chronological_probabilities)
    )
    chronological_summary["threshold_0_5"] = _metrics_at_threshold(
        validation_labels,
        chronological_probabilities,
        CLASSIFICATION_THRESHOLD,
    )
    calibrated_summary["average_precision"] = float(
        average_precision_score(validation_labels, calibrated_probabilities)
    )
    calibrated_summary["roc_auc"] = float(
        roc_auc_score(validation_labels, calibrated_probabilities)
    )
    calibrated_summary["threshold_0_5"] = _metrics_at_threshold(
        validation_labels,
        calibrated_probabilities,
        CLASSIFICATION_THRESHOLD,
    )
    original_summary["fit_partition"] = "saved Phase 4.2 model; all training rows"
    chronological_summary["fit_partition"] = (
        "training only; Jan 1–21 base fit; no calibration"
    )
    calibrated_summary["fit_partition"] = "training only; Jan 1–21 fit, Jan 22–Feb 11 calibration"
    bins = pd.concat(
        [
            original_bins.assign(model="saved_phase42_balanced_logistic"),
            chronological_bins.assign(model="chronological_base_uncalibrated"),
            calibrated_bins.assign(model="training_only_sigmoid_calibration"),
        ],
        ignore_index=True,
    )
    return {
        "original_phase42_model": original_summary,
        "chronological_base_uncalibrated": chronological_summary,
        "training_only_sigmoid": calibrated_summary,
        "base_fit_rows": early_rows,
        "calibration_fit_rows": later_rows,
        "imputation_fit_partition": "base-fit dates only",
        "imputation_medians": calibration_imputation_medians,
        "base_fit_date_range": [early_min.isoformat(), early_max.isoformat()],
        "calibration_date_range": [later_min.isoformat(), later_max.isoformat()],
        "validation_only_assessment": True,
    }, bins, calibrated_probabilities


def _fit_window_imputation_medians(frame: pd.DataFrame) -> dict[str, float]:
    """Re-fit numeric medians from observed values in the early training window."""
    medians: dict[str, float] = {}
    for name in NUMERIC_FEATURES:
        observed = frame[f"is_missing_{name}"].to_numpy(dtype=np.int8) == 0
        values = frame[name].to_numpy(dtype=np.float64)
        finite_values = values[observed & np.isfinite(values)]
        if not len(finite_values):
            raise ValueError(f"No observed base-fit values are available for {name}.")
        medians[name] = float(np.median(finite_values))
    return medians


def _apply_window_imputation(
    frame: pd.DataFrame, medians: Mapping[str, float]
) -> None:
    """Apply medians only where the corresponding persisted missing flag is set."""
    for name in NUMERIC_FEATURES:
        missing = frame[f"is_missing_{name}"].to_numpy(dtype=np.int8) != 0
        frame.loc[missing, name] = medians[name]


def _validation_with_imputation(
    validation_frame: pd.DataFrame, medians: Mapping[str, float]
) -> pd.DataFrame:
    frame = validation_frame.copy()
    _apply_window_imputation(frame, medians)
    return frame


def _frame_from_arrow(table: pa.Table) -> pd.DataFrame:
    validate_feature_names(table.column_names)
    frame = table.to_pandas(strings_to_categorical=True)
    for name in CATEGORICAL_FEATURES:
        frame[name] = frame[name].astype("category")
    for name in NUMERIC_FEATURES:
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(np.float32)
    if frame.isna().any().any():
        raise ValueError("Training/calibration feature values contain nulls.")
    return frame


def clone_pipeline(pipeline: Pipeline) -> Pipeline:
    """Return an unfitted clone for training-only calibration experiments."""
    from sklearn.base import clone

    return clone(pipeline)


def log_loss(labels: np.ndarray, probabilities: np.ndarray) -> float:
    """Calculate log loss while clipping probabilities away from exact zero/one."""
    from sklearn.metrics import log_loss as sklearn_log_loss

    return float(sklearn_log_loss(labels, probabilities, labels=[0, 1]))


def _probability_quantiles(
    probabilities: np.ndarray,
) -> dict[str, float]:
    return {
        f"q{int(q * 100):02d}": float(np.quantile(probabilities, q))
        for q in (0.00, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99, 1.00)
    }


def run_analysis(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Create explainability and error-analysis artifacts from validation only."""
    if output_directory.exists() and any(output_directory.iterdir()):
        _validate_existing_output(output_directory)
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    source_hash = _sha256_file(DATASET_PATH)
    phase42_hashes_before = _phase42_hashes()
    output_directory.mkdir(parents=True, exist_ok=True)

    model_paths = {
        "logistic_regression": PHASE42_DIRECTORY / "logistic_regression.joblib",
        "decision_tree": PHASE42_DIRECTORY / "decision_tree.joblib",
        "random_forest": PHASE42_DIRECTORY / "random_forest.joblib",
        "xgboost": PHASE42_DIRECTORY / "xgboost.joblib",
    }
    models = {name: joblib.load(path) for name, path in model_paths.items()}
    validate_feature_names(_validate_model_pipelines(models))

    validation_frame, validation_labels = _load_validation_frame()
    stored_validation = json.loads(
        (PHASE42_DIRECTORY / "validation_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    if stored_validation.get("selected_candidate") != "logistic_regression_balanced":
        raise ValueError("Phase 4.2 selected model metadata is unexpected.")

    all_probabilities: dict[str, np.ndarray] = {}
    candidate_validation: dict[str, dict[str, Any]] = {}
    for name, pipeline in models.items():
        all_probabilities[name] = pipeline.predict_proba(validation_frame)[:, 1]
        candidate_validation[name] = _metrics_at_threshold(
            validation_labels, all_probabilities[name], CLASSIFICATION_THRESHOLD
        )
    selected_probabilities = all_probabilities["logistic_regression"]
    saved_selected = stored_validation["candidates"][
        "logistic_regression_balanced"
    ]
    selected_metrics = candidate_validation["logistic_regression"]
    stored_confusion = {
        key: saved_selected["confusion_matrix"][key]
        for key in ("true_negative", "false_positive", "false_negative", "true_positive")
    }
    if selected_metrics["confusion_matrix"] != stored_confusion:
        raise ValueError(
            "Saved selected model validation predictions do not match Phase 4.2 metrics."
        )

    importance, detailed_importance = extract_global_importances(models)
    unweighted_importance, unweighted_details, unweighted_coefficients = (
        _unweighted_logistic_importances()
    )
    importance = pd.concat([importance, unweighted_importance], ignore_index=True)
    detailed_importance = pd.concat(
        [detailed_importance, unweighted_details], ignore_index=True
    )
    importance.to_csv(output_directory / "global_feature_importance.csv", index=False)
    detailed_importance.to_csv(
        output_directory / "transformed_feature_importance.csv", index=False
    )
    rf_permutation = permutation_importance(
        models["random_forest"],
        validation_frame,
        validation_labels,
        scoring="average_precision",
        n_repeats=PERMUTATION_REPEATS,
        random_state=PERMUTATION_SEED,
        n_jobs=1,
    )
    permutation_table = pd.DataFrame(
        {
            "source_feature": list(FEATURE_ALLOWLIST),
            "mean_average_precision_drop": rf_permutation.importances_mean,
            "std_average_precision_drop": rf_permutation.importances_std,
            "repeats": PERMUTATION_REPEATS,
            "validation_rows": len(validation_labels),
        }
    ).sort_values("mean_average_precision_drop", ascending=False)
    permutation_table.to_csv(
        output_directory / "random_forest_validation_permutation_importance.csv",
        index=False,
    )

    coefficients = _top_coefficients(models["logistic_regression"])
    coefficients.to_csv(
        output_directory / "balanced_logistic_top_coefficients.csv", index=False
    )
    unweighted_coefficients.to_csv(
        output_directory / "unweighted_logistic_top_coefficients.csv", index=False
    )
    tree_complexity, tree_paths = _tree_report(models["decision_tree"])
    (output_directory / "decision_tree_paths.txt").write_text(
        tree_paths, encoding="utf-8"
    )
    xgb_report, xgb_history = _xgboost_report(models["xgboost"])
    xgb_history.to_csv(
        output_directory / "xgboost_validation_aucpr_history.csv", index=False
    )

    thresholds = calculate_threshold_metrics(
        validation_labels, selected_probabilities
    )
    thresholds.to_csv(
        output_directory / "selected_validation_thresholds.csv", index=False
    )
    calibration_metrics, calibration_bins = calculate_probability_calibration(
        validation_labels, selected_probabilities
    )
    calibration_metrics["log_loss"] = log_loss(
        validation_labels, selected_probabilities
    )
    calibration_metrics["average_precision"] = float(
        average_precision_score(validation_labels, selected_probabilities)
    )
    calibration_bins.to_csv(
        output_directory / "selected_validation_calibration_bins.csv", index=False
    )

    error_table, error_summary = _validation_errors(
        validation_frame, validation_labels, selected_probabilities
    )
    errors_path = output_directory / "selected_validation_errors.parquet"
    pq.write_table(
        pa.Table.from_pandas(error_table, preserve_index=False),
        errors_path,
        compression="zstd",
        row_group_size=50_000,
    )

    group_dimensions: dict[str, Sequence[Any]] = {
        "Reporting_Airline": validation_frame["Reporting_Airline"].astype("string").to_numpy(dtype=object),
        "Origin": validation_frame["Origin"].astype("string").to_numpy(dtype=object),
        "Dest": validation_frame["Dest"].astype("string").to_numpy(dtype=object),
        "scheduled_departure_band": _scheduled_departure_bands(validation_frame),
        "day_of_week": validation_frame["day_of_week"].map(
            {
                0: "Monday",
                1: "Tuesday",
                2: "Wednesday",
                3: "Thursday",
                4: "Friday",
                5: "Saturday",
                6: "Sunday",
            }
        ).to_numpy(),
        "flight_distance_band_miles": _distance_bands(validation_frame),
    }
    group_tables: list[pd.DataFrame] = []
    group_coverage: dict[str, Any] = {}
    for dimension, values in group_dimensions.items():
        table, coverage = group_performance_table(
            validation_labels,
            selected_probabilities,
            values,
            dimension=dimension,
        )
        group_tables.append(table)
        group_coverage[dimension] = coverage
    group_report = pd.concat(group_tables, ignore_index=True)
    group_report.to_csv(
        output_directory / "selected_validation_group_performance.csv",
        index=False,
    )

    calibrated_metrics, calibrated_bins, calibrated_probabilities = _calibration_experiment(
        models["logistic_regression"],
        validation_frame,
        validation_labels,
        selected_probabilities,
    )
    calibrated_bins.to_csv(
        output_directory / "calibration_experiment_bins.csv", index=False
    )
    _write_plots(
        output_directory,
        importance,
        coefficients,
        unweighted_coefficients,
        permutation_table,
        validation_labels,
        selected_probabilities,
        calibrated_bins,
    )

    threshold_rows = thresholds.set_index("threshold")
    probabilities_summary = {
        "validation_rows": int(len(validation_labels)),
        "delayed_prevalence": float(validation_labels.mean()),
        "threshold_0_5": selected_metrics["confusion_matrix"],
        "delayed_probability_quantiles": _probability_quantiles(
            selected_probabilities[validation_labels == 1]
        ),
        "non_delayed_probability_quantiles": _probability_quantiles(
            selected_probabilities[validation_labels == 0]
        ),
        "threshold_comparisons": thresholds.to_dict(orient="records"),
        "candidate_validation_metrics": candidate_validation,
        "calibration": calibrated_metrics,
        "threshold_0_10_summary": threshold_rows.loc[0.10].to_dict(),
    }
    (output_directory / "validation_probability_and_errors.json").write_text(
        json.dumps(probabilities_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    phase42_hashes_after = _phase42_hashes()
    _assert_hashes_unchanged(phase42_hashes_before, phase42_hashes_after)
    if _sha256_file(DATASET_PATH) != source_hash:
        raise ValueError("Combined feature dataset changed during Phase 4.3 analysis.")

    xgb_estimator = models["xgboost"].named_steps["classifier"]
    configured_params = xgb_estimator.get_params(deep=False)
    output_checksums = {
        path.name: {
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(output_directory.iterdir())
        if path.is_file() and path.name != "analysis_manifest.json"
    }
    analysis_summary = {
        "validation_only": True,
        "validation_rows": int(len(validation_labels)),
        "positive_prevalence": float(validation_labels.mean()),
        "target": {
            "column": TARGET_COLUMN,
            "definition": "ArrDelay > 15 minutes; positive class is delayed",
        },
        "feature_contract": {
            "count": len(FEATURE_ALLOWLIST),
            "allowlist": list(FEATURE_ALLOWLIST),
            "categorical": list(CATEGORICAL_FEATURES),
            "numeric": list(NUMERIC_FEATURES),
            "metadata_excluded_from_model": ["flight_date", "split"],
            "leakage_fields_excluded_by_exact_allowlist": True,
        },
        "date_partitions": {
            "train": ["2024-01-01", "2024-02-11"],
            "validation": ["2024-02-12", "2024-02-20"],
            "test": ["2024-02-21", "2024-02-29"],
        },
        "selected_model": "balanced Logistic Regression",
        "selected_validation_confusion": selected_metrics["confusion_matrix"],
        "candidate_validation_metrics": candidate_validation,
        "validation_error_summary": error_summary,
        "threshold_0_5_probability_calibration": calibration_metrics,
        "training_only_sigmoid_calibration_experiment": calibrated_metrics,
        "group_metrics_minimum_sample_size": MINIMUM_GROUP_SIZE,
        "group_coverage": group_coverage,
        "decision_tree_complexity": tree_complexity,
        "xgboost_early_stopping": xgb_report,
        "random_forest_permutation_importance": {
            "scoring": "average_precision",
            "validation_rows": len(validation_labels),
            "n_repeats": PERMUTATION_REPEATS,
            "random_state": PERMUTATION_SEED,
            "limitation": "Permutation importance is validation-set, model- and distribution-dependent; correlated inputs can share or mask importance.",
        },
        "model_artifact_files": {
            name: path.name for name, path in model_paths.items()
        },
        "unweighted_logistic_regression": {
            "pipeline_artifact_saved": False,
            "coefficients_reused_from": "phase4_2/feature_importance.csv",
        },
        "xgboost_configuration": configured_params,
        "dataset_sha256": source_hash,
        "dataset_path": str(DATASET_PATH.relative_to(ROOT)),
        "phase42_artifact_sha256_before": phase42_hashes_before,
        "phase42_artifact_sha256_after": phase42_hashes_after,
        "test_partition_loaded_or_evaluated": False,
        "test_metric_artifact_hashed_only": True,
        "output_artifacts": output_checksums,
        "created_at_utc": started_at,
        "runtime_seconds": time.perf_counter() - started,
    }
    manifest_path = output_directory / "analysis_manifest.json"
    manifest_path.write_text(
        json.dumps(_json_safe(analysis_summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output_directory": str(output_directory),
        "summary": analysis_summary,
        "thresholds": thresholds,
        "group_report": group_report,
        "importance": importance,
        "coefficients": coefficients,
        "permutation_importance": permutation_table,
        "calibration_bins": calibrated_bins,
    }


def _metrics_at_threshold(
    labels: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int8)
    p = np.asarray(probabilities, dtype=np.float64)
    prediction = p >= threshold
    tn = int(np.count_nonzero((y == 0) & ~prediction))
    fp = int(np.count_nonzero((y == 0) & prediction))
    fn = int(np.count_nonzero((y == 1) & ~prediction))
    tp = int(np.count_nonzero((y == 1) & prediction))
    return {
        "rows": int(len(y)),
        "threshold": float(threshold),
        "positive_prevalence": float(y.mean()),
        "accuracy": float(np.mean(y == prediction)),
        "precision": float(precision_score(y, prediction, zero_division=0)),
        "recall": float(recall_score(y, prediction, zero_division=0)),
        "f1": float(f1_score(y, prediction, zero_division=0)),
        "f2": float(fbeta_score(y, prediction, beta=2, zero_division=0)),
        "average_precision": float(average_precision_score(y, p)),
        "confusion_matrix": {
            "true_negative": tn,
            "false_positive": fp,
            "false_negative": fn,
            "true_positive": tp,
        },
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _atomic_json(payload: Mapping[str, Any], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(_json_safe(dict(payload)), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        result = run_analysis(args.output_dir.expanduser())
        summary = result["summary"]
        print(f"Phase 4.3 outputs: {result['output_directory']}")
        print(f"Runtime: {summary['runtime_seconds']:.1f} seconds")
        print("Validation confusion:", summary["selected_validation_confusion"])
        print("XGBoost early stopping:", summary["xgboost_early_stopping"])
        print("Thresholds:")
        print(result["thresholds"].to_string(index=False))
        print("Calibration:")
        print(json.dumps(summary["training_only_sigmoid_calibration_experiment"], indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, pa.ArrowException) as exc:
        print(f"Phase 4.3 analysis failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
