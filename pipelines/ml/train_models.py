"""Train and evaluate baseline flight-delay classifiers on fixed date splits."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import sparse
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    fbeta_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
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
    LEAKAGE_DENYLIST,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = ROOT / "data" / "processed" / "ml" / "phase4_2"
RANDOM_SEED = 42
CLASSIFICATION_THRESHOLD = 0.5
EXPECTED_PARTITIONS = {
    "train": {"rows": 716_676, "delayed": 150_800, "non_delayed": 565_876},
    "validation": {"rows": 159_176, "delayed": 26_526, "non_delayed": 132_650},
    "test": {"rows": 164_787, "delayed": 23_971, "non_delayed": 140_816},
}
MODEL_SELECTION_RULE = (
    "Select the validation candidate with the highest F2 score at threshold 0.5; "
    "ties are broken by higher PR-AUC, then recall, then precision. F2 weights "
    "delayed-flight recall more heavily while retaining a precision penalty."
)


def validate_feature_names(feature_names: Sequence[str]) -> None:
    """Reject target, metadata, leakage, missing, or unexpected model columns."""
    names = list(feature_names)
    if names != list(FEATURE_ALLOWLIST):
        raise ValueError(
            "Model input columns must exactly match the Phase 4.1.6 allowlist "
            "in order."
        )
    prohibited = set(names) & (
        LEAKAGE_DENYLIST | {TARGET_COLUMN, "flight_date", "split"}
    )
    if prohibited:
        raise ValueError(f"Prohibited fields found in model features: {sorted(prohibited)}")


def _validate_dataset_manifest() -> dict[str, Any]:
    if not DATASET_PATH.is_file() or not DATASET_MANIFEST.is_file():
        raise FileNotFoundError(
            "The verified January-February feature dataset and manifest are required."
        )
    manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("validation_status") != "passed":
        raise ValueError("Combined feature manifest is not marked as passed.")
    if manifest.get("output_sha256") != _sha256_file(DATASET_PATH):
        raise ValueError("Combined feature dataset checksum does not match its manifest.")
    features = manifest.get("features", {})
    if features.get("allowlist") != list(FEATURE_ALLOWLIST):
        raise ValueError("Combined feature manifest has an unexpected feature allowlist.")
    if features.get("count") != len(FEATURE_ALLOWLIST):
        raise ValueError("Combined feature manifest feature count is incorrect.")
    if manifest.get("target", {}).get("column") != TARGET_COLUMN:
        raise ValueError("Combined feature manifest target column is incorrect.")
    imputation = manifest.get("numeric_imputation", {})
    if imputation.get("fit_partition") != "train":
        raise ValueError("Upstream numeric imputation was not fitted on training data.")
    if imputation.get("fit_rows") != EXPECTED_PARTITIONS["train"]["rows"]:
        raise ValueError("Upstream imputation training-row count is unexpected.")
    if manifest.get("split_strategy", {}).get("counts") != {
        split: {
            **counts,
            "start_date": (
                "2024-01-01"
                if split == "train"
                else "2024-02-12"
                if split == "validation"
                else "2024-02-21"
            ),
            "end_date": (
                "2024-02-11"
                if split == "train"
                else "2024-02-20"
                if split == "validation"
                else "2024-02-29"
            ),
        }
        for split, counts in EXPECTED_PARTITIONS.items()
    }:
        raise ValueError("Combined feature split counts/boundaries do not match audit.")
    for month, source in manifest.get("source_datasets", {}).items():
        path = ROOT / Path(source["path"])
        if not path.is_file() or _sha256_file(path) != source.get("sha256"):
            raise ValueError(f"Verified BTS source changed since feature preparation: {month}.")
    protected = manifest.get("preservation_checks", {}).get(
        "protected_artifacts_sha256", {}
    )
    if not protected:
        raise ValueError("Combined feature manifest lacks protected-artifact checksums.")
    for relative_path, expected_hash in protected.items():
        path = ROOT / Path(relative_path)
        if not path.is_file() or _sha256_file(path) != expected_hash:
            raise ValueError(f"Protected January/analytics artifact changed: {relative_path}.")
    return manifest


def _load_partition(split: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Read one Parquet partition and return only approved features and target."""
    if split not in EXPECTED_PARTITIONS:
        raise ValueError(f"Unknown data partition: {split}")
    expected_columns = [
        "flight_date",
        "split",
        TARGET_COLUMN,
        *FEATURE_ALLOWLIST,
    ]
    parquet = pq.ParquetFile(DATASET_PATH)
    if parquet.schema_arrow.names != expected_columns:
        raise ValueError("Combined dataset schema does not match the approved columns.")

    table = pq.read_table(
        DATASET_PATH,
        columns=expected_columns,
        filters=[("split", "=", split)],
    )
    if table.num_rows != EXPECTED_PARTITIONS[split]["rows"]:
        raise ValueError(
            f"{split} row count mismatch: expected "
            f"{EXPECTED_PARTITIONS[split]['rows']:,}, found {table.num_rows:,}."
        )
    if table[TARGET_COLUMN].null_count:
        raise ValueError(f"{split} partition contains a null target.")

    dates = table["flight_date"].to_pylist()
    split_names = table["split"].to_pylist()
    validate_partition_dates(dates, split_names)
    if any(assigned != split for assigned in split_names):
        raise ValueError(f"Date/split leakage found in {split}.")

    targets = np.asarray(
        table[TARGET_COLUMN].to_numpy(zero_copy_only=False), dtype=np.int8
    )
    positives = int(np.count_nonzero(targets == 1))
    negatives = int(np.count_nonzero(targets == 0))
    expected = EXPECTED_PARTITIONS[split]
    if positives != expected["delayed"] or negatives != expected["non_delayed"]:
        raise ValueError(f"{split} target counts do not match the verified manifest.")

    feature_table = table.select(FEATURE_ALLOWLIST)
    validate_feature_names(feature_table.column_names)
    frame = feature_table.to_pandas(strings_to_categorical=True)
    for name in CATEGORICAL_FEATURES:
        frame[name] = frame[name].astype("category")
    for name in NUMERIC_FEATURES:
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(np.float32)
    if frame.isna().any().any():
        raise ValueError(f"{split} feature matrix contains null values.")
    return frame, targets


def validate_partition_dates(dates: Sequence[Any], split_names: Sequence[str]) -> None:
    """Enforce date-grouped, chronological partition assignments."""
    if len(dates) != len(split_names):
        raise ValueError("Flight-date and split arrays have different lengths.")
    bounds = {
        "train": (datetime(2024, 1, 1).date(), datetime(2024, 2, 11).date()),
        "validation": (datetime(2024, 2, 12).date(), datetime(2024, 2, 20).date()),
        "test": (datetime(2024, 2, 21).date(), datetime(2024, 2, 29).date()),
    }
    assignments: dict[Any, set[str]] = {}
    for day, split in zip(dates, split_names):
        if split not in bounds:
            raise ValueError(f"Unknown date partition: {split}.")
        assignments.setdefault(day, set()).add(split)
    if any(len(splits) != 1 for splits in assignments.values()):
        raise ValueError("A calendar date appears in multiple data partitions.")
    if any(
        not bounds[split][0] <= day <= bounds[split][1]
        for day, splits in assignments.items()
        for split in splits
    ):
        raise ValueError("A flight date is outside its approved chronological partition.")


def make_preprocessor() -> ColumnTransformer:
    """Build sparse one-hot preprocessing with no validation/test fitting."""
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
                list(NUMERIC_FEATURES),
            ),
        ],
        remainder="drop",
        sparse_threshold=1.0,
        verbose_feature_names_out=False,
    )


def calculate_metrics(
    y_true: Sequence[int] | np.ndarray,
    y_probability: Sequence[float] | np.ndarray,
    *,
    threshold: float = CLASSIFICATION_THRESHOLD,
) -> dict[str, Any]:
    """Calculate threshold and ranking metrics with delayed flights as positive."""
    truth = np.asarray(y_true, dtype=np.int8)
    probabilities = np.asarray(y_probability, dtype=np.float64)
    if truth.ndim != 1 or probabilities.ndim != 1 or len(truth) != len(probabilities):
        raise ValueError("Truth and probability arrays must be matching 1D arrays.")
    if not len(truth) or not np.isfinite(probabilities).all():
        raise ValueError("Metrics require non-empty finite prediction probabilities.")
    if not set(np.unique(truth)).issubset({0, 1}):
        raise ValueError("Target values must be binary 0/1.")
    predicted = (probabilities >= threshold).astype(np.int8)
    matrix = confusion_matrix(truth, predicted, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    return {
        "rows": int(len(truth)),
        "positive_prevalence": float(np.mean(truth == 1)),
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(truth, predicted)),
        "precision": float(precision_score(truth, predicted, zero_division=0)),
        "recall": float(recall_score(truth, predicted, zero_division=0)),
        "f1": float(f1_score(truth, predicted, zero_division=0)),
        "f2": float(fbeta_score(truth, predicted, beta=2, zero_division=0)),
        "roc_auc": float(roc_auc_score(truth, probabilities)),
        "pr_auc": float(average_precision_score(truth, probabilities)),
        "balanced_accuracy": float(balanced_accuracy_score(truth, predicted)),
        "confusion_matrix": {
            "labels": ["non_delayed", "delayed"],
            "true_negative": tn,
            "false_positive": fp,
            "false_negative": fn,
            "true_positive": tp,
        },
    }


def select_validation_candidate(
    validation_metrics: Mapping[str, Mapping[str, Any]],
) -> str:
    """Select by prespecified recall-weighted F2, then PR-AUC/recall/precision."""
    if not validation_metrics:
        raise ValueError("No validation metrics were provided for model selection.")
    required = ("f2", "pr_auc", "recall", "precision")
    for name, metrics in validation_metrics.items():
        missing = [key for key in required if key not in metrics]
        if missing:
            raise ValueError(f"Candidate {name} lacks selection metrics: {missing}")
    return max(
        validation_metrics,
        key=lambda name: tuple(
            float(validation_metrics[name][metric])
            for metric in ("f2", "pr_auc", "recall", "precision")
        ),
    )


def evaluate_selected_test_once(
    estimator: Any,
    transformed_test: sparse.spmatrix,
    y_test: np.ndarray,
    state: dict[str, bool],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Make one final test prediction call and prevent accidental re-evaluation."""
    if state.get("evaluated", False):
        raise RuntimeError("The test partition has already been evaluated.")
    probabilities = estimator.predict_proba(transformed_test)[:, 1]
    metrics = calculate_metrics(y_test, probabilities)
    state["evaluated"] = True
    return probabilities, metrics


def _model_candidates() -> dict[str, Any]:
    """Return bounded, deterministic baseline estimator configurations."""
    return {
        "logistic_regression_unweighted": LogisticRegression(
            solver="saga",
            max_iter=1_000,
            tol=1e-3,
            class_weight=None,
            random_state=RANDOM_SEED,
        ),
        "logistic_regression_balanced": LogisticRegression(
            solver="saga",
            max_iter=1_000,
            tol=1e-3,
            class_weight="balanced",
            random_state=RANDOM_SEED,
        ),
        "decision_tree": DecisionTreeClassifier(
            max_depth=16,
            min_samples_leaf=200,
            min_samples_split=400,
            random_state=RANDOM_SEED,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            max_depth=16,
            min_samples_leaf=200,
            min_samples_split=400,
            max_features="sqrt",
            n_jobs=2,
            random_state=RANDOM_SEED,
        ),
        "xgboost": XGBClassifier(
            objective="binary:logistic",
            eval_metric="aucpr",
            n_estimators=250,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            max_bin=128,
            tree_method="hist",
            n_jobs=2,
            random_state=RANDOM_SEED,
            early_stopping_rounds=25,
        ),
    }


def _plot_validation_curves(
    labels: np.ndarray,
    probabilities: Mapping[str, np.ndarray],
    path: Path,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for name, values in probabilities.items():
        fpr, tpr, _ = roc_curve(labels, values)
        precision, recall, _ = precision_recall_curve(labels, values)
        axes[0].plot(fpr, tpr, label=name)
        axes[1].plot(recall, precision, label=name)
    axes[0].plot([0, 1], [0, 1], linestyle="--", color="gray")
    axes[0].set(title="Validation ROC", xlabel="False positive rate", ylabel="True positive rate")
    axes[1].axhline(float(np.mean(labels)), linestyle="--", color="gray", label="prevalence")
    axes[1].set(title="Validation precision-recall", xlabel="Recall", ylabel="Precision")
    for axis in axes:
        axis.legend(fontsize="small")
        axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _plot_confusion_matrix(metrics: Mapping[str, Any], path: Path, title: str) -> None:
    values = metrics["confusion_matrix"]
    matrix = np.array(
        [
            [values["true_negative"], values["false_positive"]],
            [values["false_negative"], values["true_positive"]],
        ]
    )
    fig, axis = plt.subplots(figsize=(5, 4))
    image = axis.imshow(matrix, cmap="Blues")
    axis.set(
        xticks=[0, 1],
        yticks=[0, 1],
        xticklabels=["non-delayed", "delayed"],
        yticklabels=["non-delayed", "delayed"],
        xlabel="Predicted",
        ylabel="Actual",
        title=title,
    )
    for row in range(2):
        for column in range(2):
            axis.text(column, row, f"{matrix[row, column]:,}", ha="center", va="center")
    fig.colorbar(image, ax=axis)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _importance_rows(
    candidate_name: str,
    estimator: Any,
    feature_names: Sequence[str],
) -> list[dict[str, Any]]:
    if hasattr(estimator, "coef_"):
        values = np.asarray(estimator.coef_).reshape(-1)
        method = "logistic_regression_coefficient"
    elif hasattr(estimator, "feature_importances_"):
        values = np.asarray(estimator.feature_importances_).reshape(-1)
        method = "tree_impurity_importance"
    else:
        return []
    if len(values) != len(feature_names):
        raise ValueError(f"Importance vector mismatch for {candidate_name}.")
    return [
        {
            "model_candidate": candidate_name,
            "feature": feature,
            "method": method,
            "value": float(value),
            "absolute_value": abs(float(value)),
        }
        for feature, value in zip(feature_names, values)
    ]


def _atomic_json(payload: Mapping[str, Any], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _train_into_directory(
    output_directory: Path, data_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Run training into a fresh staging directory."""
    source_hash = _sha256_file(DATASET_PATH)
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    output_directory.mkdir(parents=True, exist_ok=True)

    x_train, y_train = _load_partition("train")
    preprocessor = make_preprocessor()
    x_train_sparse = preprocessor.fit_transform(x_train, y_train)
    if not sparse.issparse(x_train_sparse):
        raise RuntimeError("Preprocessor unexpectedly produced a dense training matrix.")
    x_train_sparse = x_train_sparse.tocsr()
    del x_train

    x_validation, y_validation = _load_partition("validation")
    x_validation_sparse = preprocessor.transform(x_validation)
    if not sparse.issparse(x_validation_sparse):
        raise RuntimeError("Preprocessor unexpectedly produced a dense validation matrix.")
    x_validation_sparse = x_validation_sparse.tocsr()
    del x_validation

    x_test, y_test = _load_partition("test")
    x_test_sparse = preprocessor.transform(x_test)
    if not sparse.issparse(x_test_sparse):
        raise RuntimeError("Preprocessor unexpectedly produced a dense test matrix.")
    x_test_sparse = x_test_sparse.tocsr()
    del x_test
    feature_names = [str(name) for name in preprocessor.get_feature_names_out()]

    candidates = _model_candidates()
    validation_metrics: dict[str, dict[str, Any]] = {}
    validation_probabilities: dict[str, np.ndarray] = {}
    fitted: dict[str, Any] = {}
    training_durations: dict[str, float] = {}
    importance: list[dict[str, Any]] = []

    for name, estimator in candidates.items():
        model_started = time.perf_counter()
        if name == "xgboost":
            estimator.fit(
                x_train_sparse,
                y_train,
                eval_set=[(x_validation_sparse, y_validation)],
                verbose=False,
            )
        else:
            estimator.fit(x_train_sparse, y_train)
        training_durations[name] = time.perf_counter() - model_started
        probabilities = estimator.predict_proba(x_validation_sparse)[:, 1]
        validation_probabilities[name] = probabilities
        validation_metrics[name] = calculate_metrics(y_validation, probabilities)
        fitted[name] = estimator
        importance.extend(_importance_rows(name, estimator, feature_names))

    selected_candidate = select_validation_candidate(validation_metrics)
    logistic_candidate = select_validation_candidate(
        {
            name: metrics
            for name, metrics in validation_metrics.items()
            if name.startswith("logistic_regression_")
        }
    )
    family_artifacts = {
        "logistic_regression": fitted[logistic_candidate],
        "decision_tree": fitted["decision_tree"],
        "random_forest": fitted["random_forest"],
        "xgboost": fitted["xgboost"],
    }

    joblib.dump(preprocessor, output_directory / "preprocessor.joblib", compress=3)
    for family, estimator in family_artifacts.items():
        pipeline = Pipeline(
            steps=[
                ("preprocessor", preprocessor),
                ("classifier", estimator),
            ]
        )
        joblib.dump(
            pipeline,
            output_directory / f"{family}.joblib",
            compress=3,
        )

    test_state = {"evaluated": False}
    test_probabilities, final_test_metrics = evaluate_selected_test_once(
        fitted[selected_candidate], x_test_sparse, y_test, test_state
    )
    _plot_validation_curves(
        y_validation,
        validation_probabilities,
        output_directory / "validation_roc_pr.png",
    )
    _plot_confusion_matrix(
        validation_metrics[selected_candidate],
        output_directory / "selected_validation_confusion_matrix.png",
        f"Validation: {selected_candidate}",
    )
    _plot_confusion_matrix(
        final_test_metrics,
        output_directory / "selected_test_confusion_matrix.png",
        f"Final test: {selected_candidate}",
    )
    test_fpr, test_tpr, _ = roc_curve(y_test, test_probabilities)
    test_precision, test_recall, _ = precision_recall_curve(y_test, test_probabilities)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].plot(test_fpr, test_tpr)
    axes[0].plot([0, 1], [0, 1], linestyle="--", color="gray")
    axes[0].set(title="Selected model — final test ROC", xlabel="False positive rate", ylabel="True positive rate")
    axes[1].plot(test_recall, test_precision)
    axes[1].axhline(final_test_metrics["positive_prevalence"], linestyle="--", color="gray")
    axes[1].set(title="Selected model — final test precision-recall", xlabel="Recall", ylabel="Precision")
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_directory / "selected_test_roc_pr.png", dpi=140)
    plt.close(fig)

    importance_path = output_directory / "feature_importance.csv"
    pd.DataFrame(importance).to_csv(importance_path, index=False)
    validation_payload = {
        "threshold": CLASSIFICATION_THRESHOLD,
        "positive_class": "delayed",
        "positive_prevalence": float(np.mean(y_validation == 1)),
        "selection_rule": MODEL_SELECTION_RULE,
        "selected_candidate": selected_candidate,
        "logistic_weighting_candidate_selected_for_artifact": logistic_candidate,
        "candidates": validation_metrics,
        "training_seconds": training_durations,
    }
    _atomic_json(validation_payload, output_directory / "validation_metrics.json")
    test_payload = {
        "evaluation_partition": "test",
        "test_evaluation_calls": 1,
        "selected_candidate": selected_candidate,
        "metrics": final_test_metrics,
    }
    _atomic_json(test_payload, output_directory / "final_test_metrics.json")

    elapsed = time.perf_counter() - started
    artifact_files = sorted(
        path.name
        for path in output_directory.iterdir()
        if path.is_file()
    )
    artifact_files.append("experiment_manifest.json")
    manifest = {
        "validation_status": "passed",
        "created_at_utc": started_at,
        "training_runtime_seconds": elapsed,
        "dataset": {
            "path": DATASET_PATH.relative_to(ROOT).as_posix(),
            "sha256": source_hash,
            "rows": data_manifest["rows_written"],
            "train_rows": EXPECTED_PARTITIONS["train"]["rows"],
            "validation_rows": EXPECTED_PARTITIONS["validation"]["rows"],
            "test_rows": EXPECTED_PARTITIONS["test"]["rows"],
            "date_coverage": ["2024-01-01", "2024-02-29"],
            "coverage_limit": (
                "January-February 2024 only; results do not establish "
                "generalization across seasons or years."
            ),
        },
        "target": {
            "column": TARGET_COLUMN,
            "definition": "1 when ArrDelay > 15 minutes; otherwise 0.",
            "positive_class": "delayed",
            "train_prevalence": float(np.mean(y_train == 1)),
            "validation_prevalence": float(np.mean(y_validation == 1)),
            "test_prevalence": float(np.mean(y_test == 1)),
        },
        "features": {
            "allowlist": list(FEATURE_ALLOWLIST),
            "feature_count": len(FEATURE_ALLOWLIST),
            "categorical": list(CATEGORICAL_FEATURES),
            "numeric": list(NUMERIC_FEATURES),
            "transformed_feature_count": len(feature_names),
            "transformed_feature_names": feature_names,
            "metadata_excluded": ["flight_date", "split"],
            "leakage_denylist": sorted(LEAKAGE_DENYLIST),
        },
        "preprocessing": {
            "type": "sklearn ColumnTransformer",
            "categorical": (
                "OneHotEncoder(handle_unknown='ignore', sparse_output=True)"
            ),
            "numeric": "passthrough; upstream train-only median imputation retained",
            "fit_partition": "train",
            "train_rows": len(y_train),
            "upstream_imputation": data_manifest["numeric_imputation"],
            "sparse_matrix_shape": list(x_train_sparse.shape),
            "sparse_matrix_nnz": int(x_train_sparse.nnz),
        },
        "model_selection": {
            "rule": MODEL_SELECTION_RULE,
            "selected_candidate": selected_candidate,
            "selection_partition": "validation",
            "test_used_for_selection": False,
        },
        "models": {
            "candidates": {
                name: _json_safe(estimator.get_params(deep=False))
                for name, estimator in candidates.items()
            },
            "training_seconds": training_durations,
            "xgboost_best_iteration": getattr(
                fitted["xgboost"], "best_iteration", None
            ),
            "random_seed": RANDOM_SEED,
            "max_parallel_jobs": 2,
        },
        "validation_metrics": validation_metrics,
        "final_test_metrics": final_test_metrics,
        "test_evaluation_calls": 1,
        "interpretability": {
            "artifact": importance_path.name,
            "methods": (
                "Logistic coefficients are signed associations in the fitted "
                "one-hot space; tree importances are impurity-based. None imply "
                "causality, and correlated features can redistribute importance."
            ),
        },
        "artifacts": artifact_files,
        "software_versions": {
            "python": sys.version.split()[0],
            "scikit_learn": importlib.metadata.version("scikit-learn"),
            "xgboost": importlib.metadata.version("xgboost"),
            "scipy": importlib.metadata.version("scipy"),
            "numpy": importlib.metadata.version("numpy"),
        },
    }
    _atomic_json(manifest, output_directory / "experiment_manifest.json")

    if _sha256_file(DATASET_PATH) != source_hash:
        raise ValueError("Training unexpectedly modified the feature dataset.")
    return {
        "output_directory": str(output_directory),
        "selected_candidate": selected_candidate,
        "validation_metrics": validation_metrics,
        "final_test_metrics": final_test_metrics,
        "runtime_seconds": elapsed,
        "artifact_files": artifact_files,
    }


def _json_safe(value: Any) -> Any:
    """Normalize estimator configuration values for strict JSON manifests."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return "NaN" if np.isnan(value) else "Infinity" if value > 0 else "-Infinity"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def run_training(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Train models in staging, then publish the complete artifact directory."""
    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError(
            f"Phase 4.2 output directory already contains artifacts: {output_directory}"
        )
    data_manifest = _validate_dataset_manifest()
    staging_directory = output_directory.with_name(
        f".{output_directory.name}.{uuid.uuid4().hex}.tmp"
    )
    staging_directory.mkdir(parents=True)
    try:
        result = _train_into_directory(staging_directory, data_manifest)
        if output_directory.exists():
            output_directory.rmdir()
        staging_directory.replace(output_directory)
        result["output_directory"] = str(output_directory)
        return result
    finally:
        if staging_directory.exists():
            shutil.rmtree(staging_directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        result = run_training(args.output_dir.expanduser())
        print(f"Artifacts: {result['output_directory']}")
        print(f"Validation-selected model: {result['selected_candidate']}")
        print(f"Runtime: {result['runtime_seconds']:.1f} seconds")
        for candidate, metrics in result["validation_metrics"].items():
            print(
                f"Validation {candidate}: recall={metrics['recall']:.4f}, "
                f"precision={metrics['precision']:.4f}, "
                f"PR-AUC={metrics['pr_auc']:.4f}, F2={metrics['f2']:.4f}"
            )
        print("Final test metrics:")
        print(json.dumps(result["final_test_metrics"], indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, pa.ArrowException) as exc:
        print(f"Phase 4.2 training failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
