"""Focused safeguards and metric tests for the Phase 4.4 comparison."""

from __future__ import annotations

import numpy as np
import pytest

from pipelines.ml.compare_phase4_4 import (
    FAMILIES,
    THRESHOLD,
    _baseline_estimators,
    _metrics,
)


def test_baselines_are_phase42_fixed_models_with_sequential_workers() -> None:
    models = _baseline_estimators()

    assert tuple(models) == FAMILIES
    assert models["logistic_regression"].get_params()["class_weight"] == "balanced"
    assert models["decision_tree"].get_params()["max_depth"] == 16
    assert models["random_forest"].get_params()["n_estimators"] == 100
    assert models["random_forest"].get_params()["n_jobs"] == 1
    assert models["xgboost"].get_params()["n_estimators"] == 250
    assert models["xgboost"].get_params()["n_jobs"] == 1
    assert models["xgboost"].get_params()["early_stopping_rounds"] is None


def test_comparison_metrics_include_all_required_metrics_and_false_alert_rates() -> None:
    result = _metrics(
        np.asarray([0, 0, 1, 1], dtype=np.int8),
        np.asarray([0.1, 0.8, 0.4, 0.9]),
    )

    assert result["threshold"] == THRESHOLD
    assert result["accuracy"] == 0.5
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["f1"] == 0.5
    assert result["f2"] == 0.5
    assert result["roc_auc"] == 0.75
    assert result["pr_auc"] == pytest.approx(5 / 6)
    assert result["balanced_accuracy"] == 0.5
    assert result["false_positive_rate"] == 0.5
    assert result["false_positive_alerts_per_100_flights"] == 25.0
    assert result["alert_rate"] == 0.5
    assert result["confusion_matrix"] == {
        "labels": ["non_delayed", "delayed"],
        "true_negative": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_positive": 1,
    }
