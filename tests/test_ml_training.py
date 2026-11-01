"""Focused tests for leakage-safe model training and evaluation helpers."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from pipelines.ml.feature_dataset import (
    CATEGORICAL_FEATURES,
    FEATURE_ALLOWLIST,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)
from pipelines.ml.train_models import (
    calculate_metrics,
    evaluate_selected_test_once,
    make_preprocessor,
    select_validation_candidate,
    validate_feature_names,
    validate_partition_dates,
)


def _feature_frame() -> pd.DataFrame:
    rows = 4
    data: dict[str, object] = {
        "Reporting_Airline": pd.Series(["AA", "DL", "AA", "DL"], dtype="category"),
        "Origin": pd.Series(["JFK", "ATL", "JFK", "ATL"], dtype="category"),
        "Dest": pd.Series(["LAX", "ORD", "LAX", "ORD"], dtype="category"),
    }
    for index, name in enumerate(NUMERIC_FEATURES):
        data[name] = np.asarray([index, index + 1, index + 2, index + 3], dtype=np.float32)
        data[f"is_missing_{name}"] = np.zeros(rows, dtype=np.int8)
    return pd.DataFrame(data).loc[:, FEATURE_ALLOWLIST]


def test_model_input_requires_exact_allowlist_and_rejects_metadata() -> None:
    validate_feature_names(FEATURE_ALLOWLIST)

    with pytest.raises(ValueError, match="exactly match"):
        validate_feature_names([*FEATURE_ALLOWLIST, TARGET_COLUMN])
    with pytest.raises(ValueError, match="exactly match"):
        validate_feature_names([*FEATURE_ALLOWLIST, "flight_date"])
    with pytest.raises(ValueError, match="exactly match"):
        validate_feature_names(FEATURE_ALLOWLIST[:-1])


def test_preprocessor_fits_categories_only_on_training_and_is_sparse() -> None:
    training = _feature_frame()
    validation = _feature_frame().iloc[:1].copy()
    for name in CATEGORICAL_FEATURES:
        validation[name] = pd.Series(["UNSEEN"], dtype="category")
    validation = validation.loc[:, FEATURE_ALLOWLIST]

    preprocessor = make_preprocessor()
    train_matrix = preprocessor.fit_transform(training)
    training_scaler_mean = (
        preprocessor.named_transformers_["numeric"].mean_.copy()
    )
    for name in NUMERIC_FEATURES:
        validation[name] = np.full(len(validation), 100_000, dtype=np.float32)
    validation_matrix = preprocessor.transform(validation)

    assert sparse.issparse(train_matrix)
    assert sparse.issparse(validation_matrix)
    assert "UNSEEN" not in repr(preprocessor.named_transformers_["categorical"].categories_)
    assert train_matrix.shape[1] == len(preprocessor.get_feature_names_out())
    assert validation_matrix.shape[1] == train_matrix.shape[1]
    assert np.isfinite(train_matrix.data).all()
    assert np.array_equal(
        preprocessor.named_transformers_["numeric"].mean_,
        training_scaler_mean,
    )


def test_metrics_treat_delayed_as_positive_and_report_full_confusion_matrix() -> None:
    result = calculate_metrics(
        [0, 0, 1, 1],
        [0.1, 0.8, 0.4, 0.9],
        threshold=0.5,
    )

    assert result["rows"] == 4
    assert result["positive_prevalence"] == 0.5
    assert result["accuracy"] == 0.5
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["f1"] == 0.5
    assert result["f2"] == 0.5
    assert result["roc_auc"] == 0.75
    assert result["pr_auc"] == pytest.approx(5 / 6)
    assert result["balanced_accuracy"] == 0.5
    assert result["confusion_matrix"] == {
        "labels": ["non_delayed", "delayed"],
        "true_negative": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_positive": 1,
    }


def test_candidate_selection_uses_only_provided_validation_scores() -> None:
    candidates = {
        "high-accuracy-low-recall": {
            "f2": 0.60,
            "pr_auc": 0.80,
            "recall": 0.55,
            "precision": 0.75,
        },
        "recall-priority": {
            "f2": 0.75,
            "pr_auc": 0.70,
            "recall": 0.85,
            "precision": 0.40,
        },
    }

    assert select_validation_candidate(candidates) == "recall-priority"


def test_same_date_cannot_cross_chronological_partitions() -> None:
    validate_partition_dates(
        [pd.Timestamp("2024-02-11").date(), pd.Timestamp("2024-02-12").date()],
        ["train", "validation"],
    )
    with pytest.raises(ValueError, match="outside its approved"):
        validate_partition_dates(
            [pd.Timestamp("2024-02-12").date()],
            ["train"],
        )
    with pytest.raises(ValueError, match="multiple data partitions"):
        validate_partition_dates(
            [pd.Timestamp("2024-02-11").date(), pd.Timestamp("2024-02-11").date()],
            ["train", "validation"],
        )


def test_final_test_evaluation_is_one_time_and_model_is_reloadable(
    tmp_path: Path,
) -> None:
    frame = _feature_frame()
    preprocessor = make_preprocessor()
    matrix = preprocessor.fit_transform(frame)
    estimator = LogisticRegression(random_state=7).fit(matrix, [0, 1, 0, 1])
    state = {"evaluated": False}

    probabilities, metrics = evaluate_selected_test_once(
        estimator,
        sparse.csr_matrix(matrix),
        np.asarray([0, 1, 0, 1], dtype=np.int8),
        state,
    )

    assert state["evaluated"] is True
    assert len(probabilities) == 4
    assert metrics["rows"] == 4
    with pytest.raises(RuntimeError, match="already been evaluated"):
        evaluate_selected_test_once(
            estimator,
            sparse.csr_matrix(matrix),
            np.asarray([0, 1, 0, 1], dtype=np.int8),
            state,
        )

    artifact = tmp_path / "pipeline.joblib"
    joblib.dump(
        Pipeline([("preprocessor", preprocessor), ("classifier", estimator)]),
        artifact,
    )
    restored = joblib.load(artifact)
    assert np.allclose(
        restored.predict_proba(frame)[:, 1],
        estimator.predict_proba(matrix)[:, 1],
    )
