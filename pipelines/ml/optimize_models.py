"""Tune Phase 4.2 classifiers with bounded chronological randomized searches."""

from __future__ import annotations

import argparse
import gc
import importlib.metadata
import json
import sys
import time
import uuid
import warnings
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from scipy.stats import randint, loguniform, uniform
from scipy import sparse
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    precision_recall_curve,
    roc_curve,
)
from sklearn.model_selection import ParameterSampler
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier

from pipelines.ml.combined_feature_dataset import (
    OUTPUT_MANIFEST as DATASET_MANIFEST,
    OUTPUT_PATH as DATASET_PATH,
    _sha256_file,
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
    calculate_metrics,
    make_preprocessor,
    validate_feature_names,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = ROOT / "data" / "processed" / "ml" / "phase4_2_improvements"
RANDOM_SEED = 42
INNER_TRAIN_START = date(2024, 1, 1)
INNER_TRAIN_END = date(2024, 2, 1)
INNER_VALIDATION_START = date(2024, 2, 2)
INNER_VALIDATION_END = date(2024, 2, 11)
EXTERNAL_VALIDATION_START = date(2024, 2, 12)
EXTERNAL_VALIDATION_END = date(2024, 2, 20)
TRIAL_BUDGETS = {
    "logistic_regression": 20,
    "decision_tree": 20,
    "random_forest": 15,
    "xgboost": 20,
}
THRESHOLDS = (0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80)
PHASE42_PROTECTED_FILES = (
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

SEARCH_DISTRIBUTIONS: dict[str, dict[str, Any]] = {
    "logistic_regression": {
        "C": loguniform(0.001, 100),
        "solver_penalty": ["liblinear:l1", "liblinear:l2", "saga:l1", "saga:l2"],
        "class_weight": [None, "balanced"],
    },
    "decision_tree": {
        "max_depth": [None, *range(4, 31)],
        "min_samples_split": randint(2, 101),
        "min_samples_leaf": randint(50, 1_001),
        "criterion": ["gini", "entropy"],
        "class_weight": [None, "balanced"],
    },
    "random_forest": {
        "n_estimators": randint(100, 401),
        "max_depth": [None, *range(8, 31)],
        "min_samples_split": randint(2, 51),
        "min_samples_leaf": randint(20, 501),
        "max_features": ["sqrt", 0.3, 0.6, 0.9],
        "class_weight": [None, "balanced", "balanced_subsample"],
    },
    "xgboost": {
        "n_estimators": randint(100, 501),
        "learning_rate": loguniform(0.01, 0.2),
        "max_depth": randint(2, 9),
        "min_child_weight": randint(1, 21),
        "subsample": uniform(0.6, 0.4),
        "colsample_bytree": uniform(0.6, 0.4),
        "reg_alpha": uniform(0, 10),
        "reg_lambda": loguniform(0.1, 20),
        "scale_pos_weight_multiplier": [0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
    },
}


def _validate_dataset_manifest() -> dict[str, Any]:
    if not DATASET_PATH.is_file() or not DATASET_MANIFEST.is_file():
        raise FileNotFoundError("The verified January-February dataset is required.")
    manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("validation_status") != "passed":
        raise ValueError("Combined feature dataset manifest is not validated.")
    if manifest.get("output_sha256") != _sha256_file(DATASET_PATH):
        raise ValueError("Combined dataset checksum does not match its manifest.")
    if manifest.get("features", {}).get("allowlist") != list(FEATURE_ALLOWLIST):
        raise ValueError("Combined dataset feature allowlist is unexpected.")
    if manifest.get("features", {}).get("count") != len(FEATURE_ALLOWLIST):
        raise ValueError("Combined dataset feature count is unexpected.")
    if manifest.get("target", {}).get("column") != TARGET_COLUMN:
        raise ValueError("Combined dataset target definition is unexpected.")
    if manifest.get("numeric_imputation", {}).get("fit_partition") != "train":
        raise ValueError("Combined dataset imputation was not fitted on training.")
    if manifest.get("numeric_imputation", {}).get("fit_rows") != EXPECTED_PARTITIONS["train"]["rows"]:
        raise ValueError("Combined dataset imputation row count is unexpected.")
    return manifest


def _artifact_hashes(directory: Path, expected_files: Sequence[str] | None = None) -> dict[str, str]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Protected artifact directory not found: {directory}")
    paths = (
        [directory / name for name in expected_files]
        if expected_files is not None
        else sorted(path for path in directory.rglob("*") if path.is_file())
    )
    hashes: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Protected artifact missing: {path}")
        hashes[str(path.relative_to(directory))] = _sha256_file(path)
    if not hashes:
        raise ValueError(f"No protected artifacts found in {directory}.")
    return hashes


def _assert_hashes_unchanged(
    before: Mapping[str, str], after: Mapping[str, str], label: str
) -> None:
    if dict(before) != dict(after):
        raise ValueError(f"Protected {label} artifacts changed during optimization.")


def _window_filters(
    split: str, start: date, end: date
) -> list[tuple[str, str, Any]]:
    allowed = {
        "train": (INNER_TRAIN_START, date(2024, 2, 11)),
        "validation": (EXTERNAL_VALIDATION_START, EXTERNAL_VALIDATION_END),
    }
    if split not in allowed:
        raise ValueError("Optimization must never read the test partition.")
    allowed_start, allowed_end = allowed[split]
    if start < allowed_start or end > allowed_end or start > end:
        raise ValueError(f"Requested date window is outside the {split} partition.")
    return [
        ("split", "=", split),
        ("flight_date", ">=", start),
        ("flight_date", "<=", end),
    ]


def _load_date_window(
    split: str,
    start: date,
    end: date,
    *,
    expected_rows: int | None = None,
) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    columns = ["flight_date", "split", TARGET_COLUMN, *FEATURE_ALLOWLIST]
    parquet = pq.ParquetFile(DATASET_PATH)
    if parquet.schema_arrow.names != columns:
        raise ValueError("Combined feature schema differs from the Phase 4.1.6 contract.")
    table = pq.read_table(
        DATASET_PATH,
        columns=columns,
        filters=_window_filters(split, start, end),
    )
    if table.num_rows == 0:
        raise ValueError(f"No {split} rows in requested dates {start} through {end}.")
    if expected_rows is not None and table.num_rows != expected_rows:
        raise ValueError(
            f"{split} row count mismatch: expected {expected_rows:,}, "
            f"found {table.num_rows:,}."
        )
    if table["flight_date"].null_count or table[TARGET_COLUMN].null_count:
        raise ValueError(f"{split} data contains a missing date or target.")
    if set(table["split"].unique().to_pylist()) != {split}:
        raise ValueError(f"Unexpected split label in {split} date window.")

    date_values = pc.cast(table["flight_date"], pa.date32())
    minimum_date = pc.min(date_values).as_py()
    maximum_date = pc.max(date_values).as_py()
    if minimum_date < start or maximum_date > end:
        raise ValueError(f"{split} rows are outside the requested date boundaries.")
    dates = pc.cast(table["flight_date"], pa.date32()).to_pylist()

    target = np.asarray(
        table[TARGET_COLUMN].to_numpy(zero_copy_only=False), dtype=np.int8
    )
    if not set(np.unique(target)).issubset({0, 1}):
        raise ValueError(f"{split} target is not binary.")
    features = table.select(FEATURE_ALLOWLIST)
    validate_feature_names(features.column_names)
    frame = features.to_pandas(strings_to_categorical=True)
    for column in CATEGORICAL_FEATURES:
        frame[column] = frame[column].astype("category")
    for column in NUMERIC_FEATURES:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(np.float32)
    if frame.isna().any().any():
        raise ValueError(f"{split} feature matrix contains nulls.")
    counts = {
        "split": split,
        "start_date": minimum_date.isoformat(),
        "end_date": maximum_date.isoformat(),
        "rows": int(table.num_rows),
        "delayed": int(np.count_nonzero(target == 1)),
        "non_delayed": int(np.count_nonzero(target == 0)),
        "positive_prevalence": float(target.mean()),
        "unique_dates": int(len(set(dates))),
    }
    return frame, target, counts


def _category_distribution_shift(
    reference: pd.DataFrame, comparison: pd.DataFrame
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for column in CATEGORICAL_FEATURES:
        reference_values = reference[column].astype("string").fillna("__MISSING__")
        comparison_values = comparison[column].astype("string").fillna("__MISSING__")
        reference_counts = reference_values.value_counts(normalize=True)
        comparison_counts = comparison_values.value_counts(normalize=True)
        all_categories = reference_counts.index.union(comparison_counts.index)
        reference_share = reference_counts.reindex(all_categories, fill_value=0.0)
        comparison_share = comparison_counts.reindex(all_categories, fill_value=0.0)
        unseen = ~comparison_values.isin(reference_counts.index)
        results[column] = {
            "reference_unique_categories": int(reference_values.nunique()),
            "comparison_unique_categories": int(comparison_values.nunique()),
            "unseen_comparison_rows": int(unseen.sum()),
            "unseen_comparison_rate": float(unseen.mean()),
            "total_variation_distance": float(
                0.5 * (reference_share - comparison_share).abs().sum()
            ),
        }
    return results


def _fit_numeric_medians_on_training_window(
    frame: pd.DataFrame,
) -> dict[str, float]:
    """Recompute medians from observed values in this fit window only."""
    medians: dict[str, float] = {}
    for column in NUMERIC_FEATURES:
        observed = frame[f"is_missing_{column}"].to_numpy(dtype=np.int8) == 0
        values = frame[column].to_numpy(dtype=np.float64)
        values = values[observed & np.isfinite(values)]
        if not len(values):
            raise ValueError(f"No observed inner-training values for {column}.")
        medians[column] = float(np.median(values))
    return medians


def _apply_numeric_medians(
    frame: pd.DataFrame, medians: Mapping[str, float]
) -> None:
    """Apply fit-window medians only where persisted missing flags are set."""
    for column in NUMERIC_FEATURES:
        missing = frame[f"is_missing_{column}"].to_numpy(dtype=np.int8) != 0
        frame.loc[missing, column] = medians[column]


def _estimator_parameters(
    family: str,
    sampled: Mapping[str, Any],
    *,
    positive_negative_ratio: float,
    seed: int,
    n_jobs: int = 1,
) -> dict[str, Any]:
    parameters = dict(sampled)
    if family == "logistic_regression":
        solver, penalty = parameters.pop("solver_penalty").split(":")
        parameters.update(
            {
                "solver": solver,
                "penalty": penalty,
                "max_iter": 1_000,
                "tol": 1e-3,
                "random_state": seed,
            }
        )
    elif family == "decision_tree":
        parameters["random_state"] = seed
    elif family == "random_forest":
        parameters.update({"random_state": seed, "n_jobs": n_jobs})
    elif family == "xgboost":
        multiplier = float(parameters.pop("scale_pos_weight_multiplier"))
        parameters.update(
            {
                "scale_pos_weight": float(positive_negative_ratio * multiplier),
                "objective": "binary:logistic",
                "eval_metric": "aucpr",
                "tree_method": "hist",
                "max_bin": 128,
                "n_jobs": n_jobs,
                "random_state": seed,
            }
        )
    else:
        raise ValueError(f"Unknown estimator family: {family}")
    return parameters


def _make_estimator(family: str, parameters: Mapping[str, Any]) -> Any:
    if family == "logistic_regression":
        return LogisticRegression(**parameters)
    if family == "decision_tree":
        return DecisionTreeClassifier(**parameters)
    if family == "random_forest":
        return RandomForestClassifier(**parameters)
    if family == "xgboost":
        return XGBClassifier(**parameters)
    raise ValueError(f"Unknown estimator family: {family}")


def _run_randomized_search(
    family: str,
    x_train: sparse.csr_matrix,
    y_train: np.ndarray,
    x_validation: sparse.csr_matrix,
    y_validation: np.ndarray,
    *,
    positive_negative_ratio: float,
    trial_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    seed = RANDOM_SEED
    sampled_parameters = list(
        ParameterSampler(
            SEARCH_DISTRIBUTIONS[family],
            n_iter=trial_count,
            random_state=seed,
        )
    )
    results: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    search_started = time.perf_counter()
    for trial_index, sampled in enumerate(sampled_parameters, start=1):
        parameters = _estimator_parameters(
            family,
            sampled,
            positive_negative_ratio=positive_negative_ratio,
            seed=seed,
        )
        started = time.perf_counter()
        captured_warnings: list[str] = []
        record: dict[str, Any] = {
            "model_family": family,
            "trial": trial_index,
            "seed": seed,
            "status": "failed",
            "sampled_parameters": dict(sampled),
            "parameters": parameters,
        }
        try:
            estimator = _make_estimator(family, parameters)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                estimator.fit(x_train, y_train)
            captured_warnings = sorted({str(item.message) for item in caught})
            probabilities = estimator.predict_proba(x_validation)[:, 1]
            metrics = calculate_metrics(
                y_validation,
                probabilities,
                threshold=CLASSIFICATION_THRESHOLD,
            )
            record.update(
                {
                    "status": "completed",
                    "metrics": metrics,
                    "converged": (
                        bool(np.max(np.asarray(estimator.n_iter_)) < parameters["max_iter"])
                        if family == "logistic_regression"
                        and hasattr(estimator, "n_iter_")
                        else None
                    ),
                    "warnings": captured_warnings,
                }
            )
            if best is None or metrics["pr_auc"] > best["metrics"]["pr_auc"]:
                best = {
                    "trial": trial_index,
                    "sampled_parameters": dict(sampled),
                    "parameters": parameters,
                    "metrics": metrics,
                }
            del probabilities, estimator
        except Exception as exc:
            if isinstance(exc, MemoryError):
                raise
            record.update(
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            print(
                f"{family} trial {trial_index}/{trial_count} failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        record["runtime_seconds"] = time.perf_counter() - started
        results.append(record)
    if best is None:
        raise RuntimeError(f"Every {family} hyperparameter trial failed.")
    summary = {
        "model_family": family,
        "trial_budget": trial_count,
        "trials_completed": sum(item["status"] == "completed" for item in results),
        "trials_failed": sum(item["status"] == "failed" for item in results),
        "trials_pruned": 0,
        "best_trial": best["trial"],
        "best_inner_validation_average_precision": best["metrics"]["pr_auc"],
        "best_parameters": best["parameters"],
        "best_sampled_parameters": best["sampled_parameters"],
        "best_inner_validation_metrics": best["metrics"],
        "search_runtime_seconds": time.perf_counter() - search_started,
    }
    return summary, results, best


def _threshold_metrics(
    family: str, labels: np.ndarray, probabilities: np.ndarray
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        result = calculate_metrics(labels, probabilities, threshold=threshold)
        confusion = result["confusion_matrix"]
        rows.append(
            {
                "model_family": family,
                "threshold": threshold,
                "precision": result["precision"],
                "recall": result["recall"],
                "f1": result["f1"],
                "f2": result["f2"],
                "false_positives": confusion["false_positive"],
                "false_negatives": confusion["false_negative"],
                "flights_flagged": (
                    confusion["false_positive"] + confusion["true_positive"]
                ),
                "percent_flights_flagged": 100.0
                * (confusion["false_positive"] + confusion["true_positive"])
                / len(labels),
            }
        )
    return rows


def _feature_importance_rows(
    family: str,
    estimator: Any,
    transformed_names: Sequence[str],
) -> list[dict[str, Any]]:
    if hasattr(estimator, "coef_"):
        values = np.asarray(estimator.coef_).reshape(-1)
        method = "logistic_regression_coefficient"
    elif hasattr(estimator, "feature_importances_"):
        values = np.asarray(estimator.feature_importances_).reshape(-1)
        method = "tree_impurity_importance"
    else:
        return []
    if len(values) != len(transformed_names):
        raise ValueError(f"{family} importance shape does not match transformed features.")
    rows = []
    for name, value in zip(transformed_names, values):
        source = str(name)
        for categorical in CATEGORICAL_FEATURES:
            if source.startswith(f"{categorical}_"):
                source = categorical
                break
        rows.append(
            {
                "model_family": family,
                "transformed_feature": str(name),
                "source_feature": source,
                "method": method,
                "value": float(value),
                "absolute_value": abs(float(value)),
            }
        )
    return rows


def _plot_validation_curves(
    labels: np.ndarray,
    probabilities: Mapping[str, np.ndarray],
    output: Path,
) -> None:
    fig, axis = plt.subplots(figsize=(8, 6))
    for family, values in probabilities.items():
        precision, recall, _ = precision_recall_curve(labels, values)
        axis.plot(recall, precision, label=family.replace("_", " "))
    axis.axhline(float(labels.mean()), linestyle="--", color="gray", label="prevalence")
    axis.set(
        title="Phase 4.2.1 external-validation precision-recall",
        xlabel="Recall",
        ylabel="Precision",
    )
    axis.grid(alpha=0.2)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output / "external_validation_precision_recall.png", dpi=150)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(8, 6))
    for family, values in probabilities.items():
        false_positive_rate, true_positive_rate, _ = roc_curve(labels, values)
        axis.plot(false_positive_rate, true_positive_rate, label=family.replace("_", " "))
    axis.plot([0, 1], [0, 1], linestyle="--", color="gray")
    axis.set(
        title="Phase 4.2.1 external-validation ROC",
        xlabel="False positive rate",
        ylabel="True positive rate",
    )
    axis.grid(alpha=0.2)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output / "external_validation_roc.png", dpi=150)
    plt.close(fig)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(payload: Mapping[str, Any], destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def _check_output_directory(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(
            f"Refusing to overwrite existing optimization output: {path}"
        )


def run_optimization(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Run bounded internal searches and evaluate refit pipelines on validation."""
    _check_output_directory(output_directory)
    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    dataset_manifest = _validate_dataset_manifest()
    dataset_hash_before = _sha256_file(DATASET_PATH)
    phase42_hashes_before = _artifact_hashes(
        PHASE42_DIRECTORY, PHASE42_PROTECTED_FILES
    )
    phase43_hashes_before = _artifact_hashes(
        ROOT / "data" / "processed" / "ml" / "phase4_3"
    )

    parquet = pq.ParquetFile(DATASET_PATH)
    expected_columns = ["flight_date", "split", TARGET_COLUMN, *FEATURE_ALLOWLIST]
    if parquet.schema_arrow.names != expected_columns:
        raise ValueError("Combined feature dataset has unexpected columns.")
    x_inner_train, y_inner_train, inner_train_counts = _load_date_window(
        "train", INNER_TRAIN_START, INNER_TRAIN_END
    )
    x_inner_validation, y_inner_validation, inner_validation_counts = _load_date_window(
        "train", INNER_VALIDATION_START, INNER_VALIDATION_END
    )
    if inner_train_counts["end_date"] != INNER_TRAIN_END.isoformat():
        raise ValueError("Inner-training window does not reach February 1.")
    if inner_validation_counts["start_date"] != INNER_VALIDATION_START.isoformat():
        raise ValueError("Inner-validation window does not start February 2.")
    if (
        inner_train_counts["rows"] + inner_validation_counts["rows"]
        != EXPECTED_PARTITIONS["train"]["rows"]
        or inner_train_counts["delayed"] + inner_validation_counts["delayed"]
        != EXPECTED_PARTITIONS["train"]["delayed"]
        or inner_train_counts["non_delayed"]
        + inner_validation_counts["non_delayed"]
        != EXPECTED_PARTITIONS["train"]["non_delayed"]
    ):
        raise ValueError("Internal chronological windows do not reconcile to training.")
    if set(
        pq.read_table(
            DATASET_PATH,
            columns=["flight_date"],
            filters=_window_filters("train", INNER_TRAIN_START, INNER_TRAIN_END),
        )["flight_date"].to_pylist()
    ) & set(
        pq.read_table(
            DATASET_PATH,
            columns=["flight_date"],
            filters=_window_filters(
                "train", INNER_VALIDATION_START, INNER_VALIDATION_END
            ),
        )["flight_date"].to_pylist()
    ):
        raise ValueError("A calendar date appears in both internal partitions.")

    inner_distribution_shift = _category_distribution_shift(
        x_inner_train, x_inner_validation
    )
    inner_imputation_medians = _fit_numeric_medians_on_training_window(
        x_inner_train
    )
    _apply_numeric_medians(x_inner_train, inner_imputation_medians)
    _apply_numeric_medians(x_inner_validation, inner_imputation_medians)
    preprocessing_started = time.perf_counter()
    inner_preprocessor = make_preprocessor()
    x_inner_train_sparse = inner_preprocessor.fit_transform(x_inner_train, y_inner_train)
    x_inner_validation_sparse = inner_preprocessor.transform(x_inner_validation)
    if not sparse.issparse(x_inner_train_sparse) or not sparse.issparse(
        x_inner_validation_sparse
    ):
        raise RuntimeError("The training preprocessor unexpectedly produced dense data.")
    x_inner_train_sparse = x_inner_train_sparse.tocsr()
    x_inner_validation_sparse = x_inner_validation_sparse.tocsr()
    inner_preprocessing_seconds = time.perf_counter() - preprocessing_started
    del x_inner_train, x_inner_validation, inner_preprocessor
    gc.collect()

    inner_positive_negative_ratio = float(
        np.count_nonzero(y_inner_train == 0) / np.count_nonzero(y_inner_train == 1)
    )
    searches: dict[str, dict[str, Any]] = {}
    all_trials: list[dict[str, Any]] = []
    best_candidates: dict[str, dict[str, Any]] = {}
    for family, trial_count in TRIAL_BUDGETS.items():
        summary, trials, best = _run_randomized_search(
            family,
            x_inner_train_sparse,
            y_inner_train,
            x_inner_validation_sparse,
            y_inner_validation,
            positive_negative_ratio=inner_positive_negative_ratio,
            trial_count=trial_count,
        )
        searches[family] = summary
        all_trials.extend(trials)
        best_candidates[family] = best
        print(
            f"{family}: best inner AP={summary['best_inner_validation_average_precision']:.6f} "
            f"trial={summary['best_trial']}/{trial_count}"
        )

    del x_inner_train_sparse, x_inner_validation_sparse
    del y_inner_train, y_inner_validation
    gc.collect()

    x_train, y_train = _load_partition("train")
    x_validation, y_validation, external_validation_counts = _load_date_window(
        "validation",
        EXTERNAL_VALIDATION_START,
        EXTERNAL_VALIDATION_END,
        expected_rows=EXPECTED_PARTITIONS["validation"]["rows"],
    )
    if len(y_train) != EXPECTED_PARTITIONS["train"]["rows"]:
        raise ValueError("Full training partition row count does not match the audit.")
    if external_validation_counts["start_date"] != EXTERNAL_VALIDATION_START.isoformat() or (
        external_validation_counts["end_date"] != EXTERNAL_VALIDATION_END.isoformat()
    ):
        raise ValueError("External validation date boundaries do not match the audit.")
    external_distribution_shift = _category_distribution_shift(x_train, x_validation)

    final_preprocessor = make_preprocessor()
    x_train_sparse = final_preprocessor.fit_transform(x_train, y_train)
    x_validation_sparse = final_preprocessor.transform(x_validation)
    if not sparse.issparse(x_train_sparse) or not sparse.issparse(x_validation_sparse):
        raise RuntimeError("The final sparse preprocessing pipeline became dense.")
    x_train_sparse = x_train_sparse.tocsr()
    x_validation_sparse = x_validation_sparse.tocsr()
    del x_train
    gc.collect()

    full_positive_negative_ratio = float(
        np.count_nonzero(y_train == 0) / np.count_nonzero(y_train == 1)
    )
    original_validation_payload = json.loads(
        (PHASE42_DIRECTORY / "validation_metrics.json").read_text(encoding="utf-8")
    )
    original_metrics = {
        "logistic_regression": original_validation_payload["candidates"][
            "logistic_regression_balanced"
        ],
        "decision_tree": original_validation_payload["candidates"]["decision_tree"],
        "random_forest": original_validation_payload["candidates"]["random_forest"],
        "xgboost": original_validation_payload["candidates"]["xgboost"],
    }

    output_directory.mkdir(parents=True, exist_ok=True)
    transformed_names = [
        str(value) for value in final_preprocessor.get_feature_names_out()
    ]
    optimized_metrics: dict[str, dict[str, Any]] = {}
    probabilities_by_family: dict[str, np.ndarray] = {}
    thresholds: list[dict[str, Any]] = []
    confusion_rows: list[dict[str, Any]] = []
    importance_rows: list[dict[str, Any]] = []
    final_configuration: dict[str, Any] = {}
    final_fit_seconds: dict[str, float] = {}

    for family, best in best_candidates.items():
        parameters = _estimator_parameters(
            family,
            best["sampled_parameters"],
            positive_negative_ratio=full_positive_negative_ratio,
            seed=RANDOM_SEED,
        )
        started_fit = time.perf_counter()
        estimator = _make_estimator(family, parameters)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            estimator.fit(x_train_sparse, y_train)
        fit_seconds = time.perf_counter() - started_fit
        final_fit_seconds[family] = fit_seconds
        probabilities = estimator.predict_proba(x_validation_sparse)[:, 1]
        metrics = calculate_metrics(
            y_validation,
            probabilities,
            threshold=CLASSIFICATION_THRESHOLD,
        )
        optimized_metrics[family] = metrics
        probabilities_by_family[family] = probabilities
        thresholds.extend(_threshold_metrics(family, y_validation, probabilities))
        confusion_rows.append(
            {
                "model_family": family,
                **metrics["confusion_matrix"],
            }
        )
        importance_rows.extend(
            _feature_importance_rows(family, estimator, transformed_names)
        )
        final_configuration[family] = {
            "best_trial": best["trial"],
            "inner_validation_best_average_precision": best["metrics"]["pr_auc"],
            "tuned_parameters": best["parameters"],
            "final_refit_parameters": parameters,
            "scale_pos_weight_multiplier": best["sampled_parameters"].get(
                "scale_pos_weight_multiplier"
            ),
            "final_scale_pos_weight_fitting_ratio": (
                full_positive_negative_ratio if family == "xgboost" else None
            ),
            "fit_runtime_seconds": fit_seconds,
            "warnings": sorted({str(item.message) for item in caught}),
        }
        pipeline = Pipeline(
            steps=[
                ("preprocessor", final_preprocessor),
                ("classifier", estimator),
            ]
        )
        joblib.dump(
            pipeline,
            output_directory / f"{family}_optimized.joblib",
            compress=3,
        )
        del estimator, pipeline
        gc.collect()

    baseline_comparison: list[dict[str, Any]] = []
    for family in TRIAL_BUDGETS:
        old = original_metrics[family]
        new = optimized_metrics[family]
        row: dict[str, Any] = {
            "model_family": family,
            "phase42_precision": old["precision"],
            "optimized_precision": new["precision"],
            "precision_delta": new["precision"] - old["precision"],
            "phase42_recall": old["recall"],
            "optimized_recall": new["recall"],
            "recall_delta": new["recall"] - old["recall"],
            "phase42_f1": old["f1"],
            "optimized_f1": new["f1"],
            "f1_delta": new["f1"] - old["f1"],
            "phase42_f2": old["f2"],
            "optimized_f2": new["f2"],
            "f2_delta": new["f2"] - old["f2"],
            "phase42_average_precision": old["pr_auc"],
            "optimized_average_precision": new["pr_auc"],
            "average_precision_delta": new["pr_auc"] - old["pr_auc"],
            "phase42_roc_auc": old["roc_auc"],
            "optimized_roc_auc": new["roc_auc"],
            "phase42_balanced_accuracy": old["balanced_accuracy"],
            "optimized_balanced_accuracy": new["balanced_accuracy"],
        }
        row["improved_average_precision"] = row["average_precision_delta"] > 0
        baseline_comparison.append(row)

    pd.DataFrame(all_trials).to_json(
        output_directory / "randomized_search_trials.jsonl",
        orient="records",
        lines=True,
    )
    pd.DataFrame(baseline_comparison).to_csv(
        output_directory / "phase42_vs_optimized_validation.csv", index=False
    )
    pd.DataFrame(thresholds).to_csv(
        output_directory / "optimized_validation_thresholds.csv", index=False
    )
    pd.DataFrame(confusion_rows).to_csv(
        output_directory / "optimized_validation_confusion_matrices.csv",
        index=False,
    )
    pd.DataFrame(importance_rows).to_csv(
        output_directory / "optimized_feature_importance.csv", index=False
    )
    _write_json(searches, output_directory / "hyperparameter_search_summary.json")
    _write_json(final_configuration, output_directory / "best_configurations.json")
    _write_json(optimized_metrics, output_directory / "optimized_validation_metrics.json")
    _plot_validation_curves(
        y_validation,
        probabilities_by_family,
        output_directory,
    )

    phase42_hashes_after = _artifact_hashes(
        PHASE42_DIRECTORY, PHASE42_PROTECTED_FILES
    )
    phase43_hashes_after = _artifact_hashes(
        ROOT / "data" / "processed" / "ml" / "phase4_3"
    )
    _assert_hashes_unchanged(phase42_hashes_before, phase42_hashes_after, "Phase 4.2")
    _assert_hashes_unchanged(phase43_hashes_before, phase43_hashes_after, "Phase 4.3")
    dataset_hash_after = _sha256_file(DATASET_PATH)
    if dataset_hash_before != dataset_hash_after:
        raise ValueError("Combined feature dataset changed during optimization.")

    generated_files = sorted(
        path for path in output_directory.iterdir() if path.is_file()
    )
    artifact_checksums = {
        path.name: {
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in generated_files
        if path.name != "experiment_manifest.json"
    }
    manifest = {
        "phase": "4.2.1",
        "created_at_utc": created_at,
        "runtime_seconds": time.perf_counter() - started,
        "seed": RANDOM_SEED,
        "search_method": "sequential sklearn ParameterSampler with fixed seed",
        "optuna_installed": False,
        "parallel_jobs": 1,
        "optimization_objective": "inner-validation average precision (PR-AUC)",
        "threshold_for_trial_metrics": CLASSIFICATION_THRESHOLD,
        "thresholds_are_optimized": False,
        "trial_budgets": TRIAL_BUDGETS,
        "date_windows": {
            "inner_train": [
                INNER_TRAIN_START.isoformat(),
                INNER_TRAIN_END.isoformat(),
            ],
            "inner_validation": [
                INNER_VALIDATION_START.isoformat(),
                INNER_VALIDATION_END.isoformat(),
            ],
            "refit_train": ["2024-01-01", "2024-02-11"],
            "external_validation": [
                EXTERNAL_VALIDATION_START.isoformat(),
                EXTERNAL_VALIDATION_END.isoformat(),
            ],
            "test_partition_loaded_or_evaluated": False,
        },
        "partition_counts": {
            "inner_train": inner_train_counts,
            "inner_validation": inner_validation_counts,
            "original_training_refit": {
                "rows": int(len(y_train)),
                "delayed": int(np.count_nonzero(y_train == 1)),
                "non_delayed": int(np.count_nonzero(y_train == 0)),
                "positive_prevalence": float(y_train.mean()),
            },
            "external_validation": external_validation_counts,
        },
        "inner_preprocessing_seconds": inner_preprocessing_seconds,
        "inner_numeric_imputation": {
            "fit_partition": "inner training only",
            "fit_rows": inner_train_counts["rows"],
            "strategy": "median of observed values per numeric feature",
            "medians": inner_imputation_medians,
        },
        "inner_train_positive_negative_ratio": inner_positive_negative_ratio,
        "full_train_positive_negative_ratio": full_positive_negative_ratio,
        "feature_contract": {
            "allowlist_count": len(FEATURE_ALLOWLIST),
            "allowlist": list(FEATURE_ALLOWLIST),
            "transformed_feature_count": len(transformed_names),
            "leakage_columns_excluded": True,
            "categorical_unknown_handling": "OneHotEncoder(handle_unknown='ignore')",
            "preprocessing_fit_partitions": {
                "search": "inner training only",
                "final_refit": "full original training only",
            },
            "preprocessing_note": (
                "The existing Phase 4.2 ColumnTransformer transforms the three "
                "categorical and nine numeric columns and drops the nine approved "
                "missingness indicators via remainder='drop'; retained unchanged "
                "for baseline comparability."
            ),
        },
        "category_distribution_shift": {
            "inner_train_to_inner_validation": inner_distribution_shift,
            "full_train_to_external_validation": external_distribution_shift,
        },
        "searches": searches,
        "final_configurations": final_configuration,
        "external_validation_metrics": optimized_metrics,
        "phase42_external_validation_metrics": original_metrics,
        "phase42_comparison": baseline_comparison,
        "final_fit_runtime_seconds": final_fit_seconds,
        "source_dataset": {
            "path": str(DATASET_PATH.relative_to(ROOT)),
            "sha256_before": dataset_hash_before,
            "sha256_after": dataset_hash_after,
            "manifest_sha256": _sha256_file(DATASET_MANIFEST),
            "verified_manifest_rows": dataset_manifest.get("rows_written"),
        },
        "protected_phase42_artifact_sha256_before": phase42_hashes_before,
        "protected_phase42_artifact_sha256_after": phase42_hashes_after,
        "protected_phase43_artifact_sha256_before": phase43_hashes_before,
        "protected_phase43_artifact_sha256_after": phase43_hashes_after,
        "generated_artifacts": artifact_checksums,
        "package_versions": {
            package: importlib.metadata.version(package)
            for package in ("scikit-learn", "xgboost", "numpy", "pandas", "pyarrow")
        },
    }
    _write_json(manifest, output_directory / "experiment_manifest.json")
    return {
        "output_directory": str(output_directory),
        "manifest": manifest,
        "comparison": pd.DataFrame(baseline_comparison),
        "thresholds": pd.DataFrame(thresholds),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        result = run_optimization(args.output_dir.expanduser())
        print(f"Phase 4.2.1 outputs: {result['output_directory']}")
        print(f"Runtime: {result['manifest']['runtime_seconds']:.1f} seconds")
        print("External validation comparison:")
        print(result["comparison"].to_string(index=False))
        print("Thresholds:")
        print(
            result["thresholds"].groupby("model_family", sort=False).apply(
                lambda group: group.loc[group["threshold"].isin([0.2, 0.3, 0.4, 0.5])]
            ).to_string(index=False)
        )
        print("Test partition loaded or evaluated: False")
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, pa.ArrowException) as exc:
        print(f"Phase 4.2.1 optimization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
