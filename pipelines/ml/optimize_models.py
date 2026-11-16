"""Tune Phase 4.2 classifiers with bounded chronological randomized searches."""

from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import io
import importlib.metadata
import json
import os
import sys
import tempfile
import time
import uuid
import warnings
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
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
from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    precision_recall_curve,
    roc_curve,
)
from sklearn.model_selection import ParameterSampler
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
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
    MISSING_INDICATOR_FEATURES,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)
from pipelines.ml.train_models import (
    CLASSIFICATION_THRESHOLD,
    EXPECTED_PARTITIONS,
    OUTPUT_DIRECTORY as PHASE42_DIRECTORY,
    _load_partition,
    calculate_metrics,
    validate_feature_names,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = ROOT / "data" / "processed" / "ml" / "phase4_2_improvements"
RANDOM_SEED = 42
INNER_TRAIN_SAMPLE_SIZE = 180_000
SAMPLE_SEED = 42
INNER_TRAIN_START = date(2024, 1, 1)
INNER_TRAIN_END = date(2024, 2, 1)
INNER_VALIDATION_START = date(2024, 2, 2)
INNER_VALIDATION_END = date(2024, 2, 11)
EXTERNAL_VALIDATION_START = date(2024, 2, 12)
EXTERNAL_VALIDATION_END = date(2024, 2, 20)
TRIAL_BUDGETS = {
    "logistic_regression": 8,
    "decision_tree": 8,
    "random_forest": 5,
    "xgboost": 8,
}
TRIAL_EXECUTION_LIMITS = {
    "logistic_regression": 8,
    "decision_tree": 8,
    "random_forest": 2,
    "xgboost": 2,
}
TRIAL_STOP_REASONS = {
    "random_forest": (
        "Stopped at 2 trials after trial 2 required 2,413 seconds; "
        "the in-progress third trial was interrupted and the remaining budget "
        "was skipped to keep this run resource-bounded."
    ),
    "xgboost": (
        "Stopped at 2 trials after trial 1 required 1,381 seconds; "
        "the remaining budget was skipped to keep this run resource-bounded."
    ),
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

SEARCH_SPACE_DESCRIPTION = {
    "logistic_regression": {
        "C": "log-uniform [0.001, 100]",
        "solver_penalty": ["liblinear:l1", "liblinear:l2", "saga:l1", "saga:l2"],
        "class_weight": [None, "balanced"],
        "max_iter": 500,
    },
    "decision_tree": {
        "max_depth": "4..30 or None",
        "min_samples_split": "integer 2..100",
        "min_samples_leaf": "integer 50..1000",
        "criterion": ["gini", "entropy"],
        "class_weight": [None, "balanced"],
    },
    "random_forest": {
        "n_estimators": "integer 100..400",
        "max_depth": "8..30 or None",
        "min_samples_split": "integer 2..50",
        "min_samples_leaf": "integer 20..500",
        "max_features": ["sqrt", 0.3, 0.6, 0.9],
        "class_weight": [None, "balanced", "balanced_subsample"],
    },
    "xgboost": {
        "n_estimators": "integer 100..500, early stopping patience 30",
        "learning_rate": "log-uniform [0.01, 0.2]",
        "max_depth": "integer 2..8",
        "min_child_weight": "integer 1..20",
        "subsample": "uniform [0.6, 1.0]",
        "colsample_bytree": "uniform [0.6, 1.0]",
        "reg_alpha": "uniform [0, 10]",
        "reg_lambda": "log-uniform [0.1, 20]",
        "scale_pos_weight": "fitting-data ratio multiplied by {0.5, 0.75, 1, 1.25, 1.5, 2}",
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


def _chronological_order(dates: Sequence[date]) -> np.ndarray:
    """Return a stable row order by calendar date."""
    return np.argsort(np.asarray(dates, dtype="datetime64[D]"), kind="stable")


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
    chronological_indices = _chronological_order(dates)
    if not np.array_equal(chronological_indices, np.arange(len(dates))):
        frame = frame.iloc[chronological_indices].reset_index(drop=True)
        target = target[chronological_indices]
        dates = [dates[index] for index in chronological_indices]
    counts = {
        "split": split,
        "start_date": minimum_date.isoformat(),
        "end_date": maximum_date.isoformat(),
        "rows": int(table.num_rows),
        "delayed": int(np.count_nonzero(target == 1)),
        "non_delayed": int(np.count_nonzero(target == 0)),
        "positive_prevalence": float(target.mean()),
        "unique_dates": int(len(set(dates))),
        "date_row_counts": {
            day.isoformat(): int(count)
            for day, count in sorted(Counter(dates).items())
        },
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


def make_optimizer_preprocessor() -> ColumnTransformer:
    """Fit sparse transforms over all 21 approved inputs."""
    validate_feature_names(FEATURE_ALLOWLIST)
    return ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=True,
                    dtype=np.float32,
                ),
                list(CATEGORICAL_FEATURES),
            ),
            (
                "numeric",
                StandardScaler(with_mean=False),
                [*NUMERIC_FEATURES, *MISSING_INDICATOR_FEATURES],
            ),
        ],
        remainder="drop",
        sparse_threshold=1.0,
        verbose_feature_names_out=False,
    )


def _deterministic_training_sample(
    frame: pd.DataFrame,
    labels: np.ndarray,
    *,
    sample_size: int = INNER_TRAIN_SAMPLE_SIZE,
    seed: int = SAMPLE_SEED,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Select a reproducible row sample while retaining original row order."""
    if len(frame) != len(labels):
        raise ValueError("Training feature/label lengths do not match.")
    if sample_size <= 0 or sample_size > len(labels):
        raise ValueError("Training sample size must be positive and no larger than input.")
    indices = np.sort(
        np.random.default_rng(seed).choice(len(labels), size=sample_size, replace=False)
    )
    return frame.iloc[indices].reset_index(drop=True), labels[indices], indices


def _run_fingerprint(dataset_hash: str) -> tuple[str, dict[str, Any]]:
    config = {
        "dataset_sha256": dataset_hash,
        "feature_allowlist": list(FEATURE_ALLOWLIST),
        "seed": RANDOM_SEED,
        "sample_seed": SAMPLE_SEED,
        "inner_train_sample_size": INNER_TRAIN_SAMPLE_SIZE,
        "trial_budgets": TRIAL_BUDGETS,
        "search_spaces": SEARCH_SPACE_DESCRIPTION,
        "dates": {
            "inner_train": [INNER_TRAIN_START.isoformat(), INNER_TRAIN_END.isoformat()],
            "inner_validation": [
                INNER_VALIDATION_START.isoformat(),
                INNER_VALIDATION_END.isoformat(),
            ],
            "external_validation": [
                EXTERNAL_VALIDATION_START.isoformat(),
                EXTERNAL_VALIDATION_END.isoformat(),
            ],
        },
        "search_method": "sklearn.ParameterSampler sequential single holdout",
    }
    fingerprint = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return fingerprint, config


def _prepare_run_state(output: Path, fingerprint: str, config: Mapping[str, Any]) -> bool:
    """Create fresh run metadata or validate an interrupted run for resumption."""
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "run_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != fingerprint or state.get("configuration") != config:
            raise ValueError(
                "Existing HPO state belongs to a different dataset or search configuration."
            )
        if state.get("status") == "completed":
            raise FileExistsError(
                "This HPO run is already complete; refusing to overwrite its artifacts."
            )
        return True
    existing = [path for path in output.iterdir() if path.name != "optimization.lock"]
    if existing:
        raise FileExistsError(
            "HPO output contains artifacts but no recovery state; refusing to overwrite."
        )
    _write_json(
        {
            "fingerprint": fingerprint,
            "configuration": config,
            "status": "running",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        state_path,
    )
    return False


@contextmanager
def _optimization_lock(output: Path):
    """Prevent concurrent runs for the same output directory."""
    lock_digest = hashlib.sha256(str(output.resolve()).encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"flightpulse-phase421-{lock_digest}.lock"
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another Phase 4.2.1 optimization process is active.") from exc
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Another Phase 4.2.1 optimization process is active.") from exc
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _estimator_parameters(
    family: str,
    sampled: Mapping[str, Any],
    *,
    positive_negative_ratio: float,
    seed: int,
    n_jobs: int = 1,
    early_stopping_rounds: int | None = None,
) -> dict[str, Any]:
    parameters = dict(sampled)
    if family == "logistic_regression":
        solver, penalty = parameters.pop("solver_penalty").split(":")
        parameters.update(
            {
                "solver": solver,
                "penalty": penalty,
                "max_iter": 500,
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
        if early_stopping_rounds is not None:
            parameters["early_stopping_rounds"] = early_stopping_rounds
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
    checkpoint_path: Path,
    run_fingerprint: str,
    early_stopping_rounds: int | None = None,
    execution_limit: int | None = None,
    stop_reason: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if execution_limit is None:
        execution_limit = trial_count
    if execution_limit < 1 or execution_limit > trial_count:
        raise ValueError("The executed trial limit must be within the trial budget.")
    seed = RANDOM_SEED
    sampled_parameters = list(
        ParameterSampler(
            SEARCH_DISTRIBUTIONS[family],
            n_iter=trial_count,
            random_state=seed,
        )
    )
    checkpoint: dict[str, Any] = {
        "run_fingerprint": run_fingerprint,
        "model_family": family,
        "trial_budget": trial_count,
        "trials": [],
    }
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            checkpoint.get("run_fingerprint") != run_fingerprint
            or checkpoint.get("model_family") != family
            or checkpoint.get("trial_budget") != trial_count
        ):
            raise ValueError(f"{family} checkpoint does not match the current run.")
    results = list(checkpoint.get("trials", []))
    best: dict[str, Any] | None = None
    completed_ids: set[int] = set()
    for record in results:
        trial_id = record.get("trial")
        if (
            not isinstance(trial_id, int)
            or trial_id < 1
            or trial_id > trial_count
            or trial_id in completed_ids
            or record.get("status") not in {"completed", "failed", "skipped"}
        ):
            raise ValueError(f"{family} checkpoint contains an invalid trial record.")
        completed_ids.add(trial_id)
    resumed_trial_count = len(completed_ids)
    for trial_index, sampled in enumerate(sampled_parameters, start=1):
        if trial_index in completed_ids:
            continue
        if trial_index > execution_limit:
            record = {
                "model_family": family,
                "trial": trial_index,
                "seed": seed,
                "status": "skipped",
                "sampled_parameters": dict(sampled),
                "skip_reason": stop_reason or "Trial execution limit reached.",
            }
            results.append(record)
            completed_ids.add(trial_index)
            checkpoint["trials"] = results
            _write_json(checkpoint, checkpoint_path)
            print(
                f"{family} trial {trial_index}/{trial_count}: skipped "
                f"(execution limit {execution_limit})",
                flush=True,
            )
            continue
        parameters = _estimator_parameters(
            family,
            sampled,
            positive_negative_ratio=positive_negative_ratio,
            seed=seed,
            early_stopping_rounds=early_stopping_rounds,
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
                if family == "xgboost":
                    estimator.fit(
                        x_train,
                        y_train,
                        eval_set=[(x_validation, y_validation)],
                        verbose=False,
                    )
                else:
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
                    "best_iteration": (
                        int(estimator.best_iteration)
                        if family == "xgboost" and hasattr(estimator, "best_iteration")
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
                    "best_iteration": record.get("best_iteration"),
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
        checkpoint["trials"] = results
        _write_json(checkpoint, checkpoint_path)
        print(
            f"{family} trial {trial_index}/{trial_count}: {record['status']}"
            + (
                f", AP={record['metrics']['pr_auc']:.6f}"
                if record["status"] == "completed"
                else ""
            ),
            flush=True,
        )
    successful = [item for item in results if item["status"] == "completed"]
    if not successful:
        raise RuntimeError(f"Every {family} hyperparameter trial failed.")
    best_record = max(successful, key=lambda item: float(item["metrics"]["pr_auc"]))
    best = {
        "trial": best_record["trial"],
        "sampled_parameters": best_record["sampled_parameters"],
        "parameters": best_record["parameters"],
        "metrics": best_record["metrics"],
        "best_iteration": best_record.get("best_iteration"),
    }
    total_trial_runtime = sum(float(item.get("runtime_seconds", 0.0)) for item in results)
    summary = {
        "model_family": family,
        "trial_budget": trial_count,
        "trials_completed": sum(item["status"] == "completed" for item in results),
        "trials_failed": sum(item["status"] == "failed" for item in results),
        "trials_skipped": sum(item["status"] == "skipped" for item in results),
        "trials_pruned": 0,
        "execution_limit": execution_limit,
        "stop_reason": stop_reason,
        "best_trial": best["trial"],
        "best_inner_validation_average_precision": best["metrics"]["pr_auc"],
        "best_parameters": best["parameters"],
        "best_sampled_parameters": best["sampled_parameters"],
        "best_inner_validation_metrics": best["metrics"],
        "search_runtime_seconds": total_trial_runtime,
        "resumed_trials": resumed_trial_count,
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
        method = (
            "xgboost_gain_importance"
            if family == "xgboost"
            else "tree_impurity_importance"
        )
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
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    _write_artifact_once(
        output / "external_validation_precision_recall.png", buffer.getvalue()
    )

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
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    _write_artifact_once(output / "external_validation_roc.png", buffer.getvalue())


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


def _write_artifact_once(destination: Path, content: bytes) -> None:
    """Create an output once; accept exact matches on safe resumption only."""
    if destination.exists():
        if destination.read_bytes() != content:
            raise FileExistsError(
                f"Refusing to overwrite an existing HPO artifact: {destination}"
            )
        return
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.tmp"
    )
    temporary.write_bytes(content)
    try:
        temporary.replace(destination)
    except OSError:
        if destination.is_file() and destination.read_bytes() == content:
            temporary.unlink(missing_ok=True)
            return
        raise


def _write_json_artifact_once(
    payload: Mapping[str, Any], destination: Path
) -> None:
    content = (
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    _write_artifact_once(destination, content)


def _write_csv_artifact_once(frame: pd.DataFrame, destination: Path) -> None:
    _write_artifact_once(destination, frame.to_csv(index=False).encode("utf-8"))


def run_optimization(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Run or resume the isolated, checkpointed optimization study."""
    with _optimization_lock(output_directory):
        return _run_optimization_locked(output_directory)


def _run_optimization_locked(output_directory: Path) -> dict[str, Any]:
    """Run bounded internal searches and evaluate refit pipelines on validation."""
    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    dataset_manifest = _validate_dataset_manifest()
    dataset_hash_before = _sha256_file(DATASET_PATH)
    fingerprint, configuration = _run_fingerprint(dataset_hash_before)
    resumed = _prepare_run_state(output_directory, fingerprint, configuration)
    run_state_path = output_directory / "run_state.json"
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
    inner_train_dates = [
        date.fromisoformat(day)
        for day, count in sorted(inner_train_counts["date_row_counts"].items())
        for _ in range(count)
    ]
    inner_validation_dates = [
        date.fromisoformat(day)
        for day, count in sorted(inner_validation_counts["date_row_counts"].items())
        for _ in range(count)
    ]
    if set(inner_train_dates) & set(inner_validation_dates):
        raise ValueError("A calendar date appears in both internal partitions.")

    inner_distribution_shift = _category_distribution_shift(
        x_inner_train, x_inner_validation
    )
    inner_imputation_medians = _fit_numeric_medians_on_training_window(
        x_inner_train
    )
    _apply_numeric_medians(x_inner_train, inner_imputation_medians)
    _apply_numeric_medians(x_inner_validation, inner_imputation_medians)
    x_inner_train, y_inner_train, sampled_indices = _deterministic_training_sample(
        x_inner_train,
        y_inner_train,
    )
    sampled_dates = [inner_train_dates[index] for index in sampled_indices]
    sampled_date_counts = {
        day.isoformat(): int(count)
        for day, count in sorted(Counter(sampled_dates).items())
    }
    sampled_positive_rows = int(np.count_nonzero(y_inner_train == 1))
    sampled_negative_rows = int(np.count_nonzero(y_inner_train == 0))
    sampled_positive_prevalence = float(y_inner_train.mean())
    preprocessing_started = time.perf_counter()
    inner_preprocessor = make_optimizer_preprocessor()
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
    all_trials: list[dict[str, Any]] = []
    best_candidates: dict[str, dict[str, Any]] = {}
    searches: dict[str, dict[str, Any]] = {}
    _write_json(
        {
            "fingerprint": fingerprint,
            "configuration": configuration,
            "status": "searching",
            "resumed": resumed,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        run_state_path,
    )
    for family, trial_count in TRIAL_BUDGETS.items():
        summary, trials, best = _run_randomized_search(
            family,
            x_inner_train_sparse,
            y_inner_train,
            x_inner_validation_sparse,
            y_inner_validation,
            positive_negative_ratio=inner_positive_negative_ratio,
            trial_count=trial_count,
            checkpoint_path=output_directory / f"trials_{family}.json",
            run_fingerprint=fingerprint,
            early_stopping_rounds=30 if family == "xgboost" else None,
            execution_limit=TRIAL_EXECUTION_LIMITS[family],
            stop_reason=TRIAL_STOP_REASONS.get(family),
        )
        searches[family] = summary
        all_trials.extend(trials)
        best_candidates[family] = best
        _write_json(
            {
                "fingerprint": fingerprint,
                "configuration": configuration,
                "status": "searching",
                "resumed": resumed,
                "completed_search_families": sorted(searches),
                "search_summaries": searches,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            run_state_path,
        )
        print(
            f"{family}: best inner AP={summary['best_inner_validation_average_precision']:.6f} "
            f"trial={summary['best_trial']}/{trial_count}"
        )

    del x_inner_train_sparse, x_inner_validation_sparse
    del y_inner_train, y_inner_validation
    gc.collect()
    _write_json(
        {
            "fingerprint": fingerprint,
            "configuration": configuration,
            "status": "refitting",
            "resumed": resumed,
            "completed_search_families": sorted(searches),
            "search_summaries": searches,
            "best_candidates": best_candidates,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        run_state_path,
    )

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

    final_preprocessor = make_optimizer_preprocessor()
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
        if family == "xgboost":
            if best["best_iteration"] is None:
                raise ValueError("XGBoost best trial has no early-stopping iteration.")
            parameters["n_estimators"] = int(best["best_iteration"]) + 1
        model_path = output_directory / f"{family}_optimized.joblib"
        refit_state_path = output_directory / f"refit_{family}.json"
        if model_path.exists():
            pipeline = joblib.load(model_path)
            if not isinstance(pipeline, Pipeline) or set(pipeline.named_steps) != {
                "preprocessor",
                "classifier",
            }:
                raise ValueError(f"Existing {family} model artifact is not a valid pipeline.")
            if list(pipeline.named_steps["preprocessor"].get_feature_names_out()) != transformed_names:
                raise ValueError(f"Existing {family} pipeline has an unexpected feature map.")
            estimator = pipeline.named_steps["classifier"]
            fitted_parameters = estimator.get_params(deep=False)
            for name, value in parameters.items():
                if fitted_parameters.get(name) != value:
                    raise ValueError(
                        f"Existing {family} pipeline has a conflicting {name} parameter."
                    )
            if refit_state_path.exists():
                refit_state = json.loads(refit_state_path.read_text(encoding="utf-8"))
                if refit_state.get("parameters") != _json_safe(parameters):
                    raise ValueError(f"Existing {family} refit checkpoint conflicts.")
                fit_seconds = refit_state.get("fit_runtime_seconds")
                fit_warnings = refit_state.get("warnings", [])
                recovered_existing_model = bool(
                    refit_state.get("recovered_existing_model", True)
                )
            else:
                fit_seconds = None
                fit_warnings = []
                recovered_existing_model = True
                _write_json(
                    {
                        "model_family": family,
                        "parameters": parameters,
                        "fit_runtime_seconds": None,
                        "warnings": [],
                        "recovered_existing_model": True,
                        "model_sha256": _sha256_file(model_path),
                    },
                    refit_state_path,
                )
        else:
            started_fit = time.perf_counter()
            estimator = _make_estimator(family, parameters)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                estimator.fit(x_train_sparse, y_train)
            fit_seconds = time.perf_counter() - started_fit
            fit_warnings = sorted({str(item.message) for item in caught})
            pipeline = Pipeline(
                steps=[
                    ("preprocessor", final_preprocessor),
                    ("classifier", estimator),
                ]
            )
            temporary_model_path = output_directory / (
                f".{family}_optimized.{uuid.uuid4().hex}.tmp"
            )
            joblib.dump(pipeline, temporary_model_path, compress=3)
            if model_path.exists():
                raise FileExistsError(
                    f"Refusing to overwrite an existing model: {model_path}"
                )
            os.replace(temporary_model_path, model_path)
            _write_json(
                {
                    "model_family": family,
                    "parameters": parameters,
                    "fit_runtime_seconds": fit_seconds,
                    "warnings": fit_warnings,
                    "recovered_existing_model": False,
                    "model_sha256": _sha256_file(model_path),
                },
                refit_state_path,
            )
            recovered_existing_model = False
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
            "reused_saved_model": recovered_existing_model,
            "artifact_path": model_path.name,
            "warnings": fit_warnings,
        }
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

    trials_jsonl = pd.DataFrame(all_trials).to_json(
        orient="records",
        lines=True,
    )
    _write_artifact_once(
        output_directory / "randomized_search_trials.jsonl",
        trials_jsonl.encode("utf-8"),
    )
    _write_csv_artifact_once(
        pd.DataFrame(baseline_comparison),
        output_directory / "phase42_vs_optimized_validation.csv",
    )
    _write_csv_artifact_once(
        pd.DataFrame(thresholds),
        output_directory / "optimized_validation_thresholds.csv",
    )
    _write_csv_artifact_once(
        pd.DataFrame(confusion_rows),
        output_directory / "optimized_validation_confusion_matrices.csv",
    )
    _write_csv_artifact_once(
        pd.DataFrame(importance_rows),
        output_directory / "optimized_feature_importance.csv",
    )
    search_summary_path = output_directory / "hyperparameter_search_summary.json"
    if search_summary_path.exists():
        persisted_searches = json.loads(search_summary_path.read_text(encoding="utf-8"))
        for family, persisted in persisted_searches.items():
            recomputed = searches.get(family)
            if recomputed is None:
                raise ValueError("Existing search summary contains an unknown model family.")
            persisted_stable = {
                key: value for key, value in persisted.items() if key != "resumed_trials"
            }
            recomputed_stable = {
                key: value for key, value in recomputed.items() if key != "resumed_trials"
            }
            if persisted_stable != recomputed_stable:
                raise FileExistsError(
                    f"Existing {family} search summary conflicts with recovered trials."
                )
            searches[family] = persisted
    _write_json_artifact_once(searches, search_summary_path)
    _write_json_artifact_once(
        final_configuration, output_directory / "best_configurations.json"
    )
    _write_json_artifact_once(
        optimized_metrics, output_directory / "optimized_validation_metrics.json"
    )
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
        if path.name not in {"experiment_manifest.json", "run_state.json"}
    }
    manifest = {
        "phase": "4.2.1",
        "created_at_utc": created_at,
        "runtime_seconds": time.perf_counter() - started,
        "seed": RANDOM_SEED,
        "search_method": "sequential sklearn ParameterSampler with fixed seed",
        "resumed_from_checkpoint": resumed,
        "optuna_installed": False,
        "parallel_jobs": 1,
        "optimization_objective": "inner-validation average precision (PR-AUC)",
        "threshold_for_trial_metrics": CLASSIFICATION_THRESHOLD,
        "thresholds_are_optimized": False,
        "trial_budgets": TRIAL_BUDGETS,
        "trials_executed_limits": TRIAL_EXECUTION_LIMITS,
        "trial_stop_reasons": TRIAL_STOP_REASONS,
        "search_space": SEARCH_SPACE_DESCRIPTION,
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
        "inner_train_sample": {
            "method": "uniform random sample without replacement, sorted back to source order",
            "seed": SAMPLE_SEED,
            "sampled_rows": int(len(sampled_indices)),
            "positive_rows": sampled_positive_rows,
            "negative_rows": sampled_negative_rows,
            "positive_prevalence": sampled_positive_prevalence,
            "date_row_counts": sampled_date_counts,
        },
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
                    "Phase 4.2.1 explicitly transforms all 21 allowlisted inputs, "
                    "including the nine missingness indicators. Phase 4.2 baseline "
                    "preprocessing dropped those indicators; that difference is "
                    "recorded when comparing baseline results."
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
    manifest_path = output_directory / "experiment_manifest.json"
    if manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            existing_manifest.get("run_fingerprint") != fingerprint
            or existing_manifest.get("generated_artifacts") != artifact_checksums
        ):
            raise FileExistsError(
                "Existing HPO experiment manifest conflicts with recovered outputs."
            )
        manifest = existing_manifest
    else:
        manifest["run_fingerprint"] = fingerprint
        _write_json_artifact_once(manifest, manifest_path)
    _write_json(
        {
            "fingerprint": fingerprint,
            "configuration": configuration,
            "status": "completed",
            "resumed": resumed,
            "completed_search_families": sorted(searches),
            "search_summaries": searches,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "experiment_manifest_sha256": _sha256_file(manifest_path),
        },
        run_state_path,
    )
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
        selected_thresholds = result["thresholds"].loc[
            result["thresholds"]["threshold"].isin([0.2, 0.3, 0.4, 0.5])
        ]
        print(
            selected_thresholds.to_string(index=False)
        )
        print("Test partition loaded or evaluated: False")
        return 0
    except (OSError, ValueError, RuntimeError, TypeError, pa.ArrowException) as exc:
        print(f"Phase 4.2.1 optimization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
