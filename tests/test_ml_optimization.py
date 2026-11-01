"""Focused tests for chronological, bounded Phase 4.2.1 tuning."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from pipelines.ml.feature_dataset import FEATURE_ALLOWLIST, NUMERIC_FEATURES
from pipelines.ml.optimize_models import (
    SEARCH_DISTRIBUTIONS,
    TRIAL_BUDGETS,
    _apply_numeric_medians,
    _category_distribution_shift,
    _check_output_directory,
    _estimator_parameters,
    _make_estimator,
    _run_randomized_search,
    _window_filters,
    _fit_numeric_medians_on_training_window,
)


def _features(rows: int = 8) -> pd.DataFrame:
    data: dict[str, object] = {
        "Reporting_Airline": pd.Series(["AA", "DL"] * (rows // 2), dtype="category"),
        "Origin": pd.Series(["JFK", "ATL"] * (rows // 2), dtype="category"),
        "Dest": pd.Series(["LAX", "ORD"] * (rows // 2), dtype="category"),
    }
    for index, name in enumerate(NUMERIC_FEATURES):
        data[name] = np.arange(rows, dtype=np.float32) + index
        data[f"is_missing_{name}"] = np.zeros(rows, dtype=np.int8)
    return pd.DataFrame(data).loc[:, FEATURE_ALLOWLIST]


def test_search_budgets_and_date_filters_are_bounded_and_exclude_test() -> None:
    assert TRIAL_BUDGETS == {
        "logistic_regression": 20,
        "decision_tree": 20,
        "random_forest": 15,
        "xgboost": 20,
    }
    filters = _window_filters(
        "train", pd.Timestamp("2024-02-02").date(), pd.Timestamp("2024-02-11").date()
    )
    assert filters == [
        ("split", "=", "train"),
        ("flight_date", ">=", pd.Timestamp("2024-02-02").date()),
        ("flight_date", "<=", pd.Timestamp("2024-02-11").date()),
    ]
    with pytest.raises(ValueError, match="never read the test"):
        _window_filters(
            "test",
            pd.Timestamp("2024-02-21").date(),
            pd.Timestamp("2024-02-29").date(),
        )
    with pytest.raises(ValueError, match="outside"):
        _window_filters(
            "train",
            pd.Timestamp("2024-02-12").date(),
            pd.Timestamp("2024-02-20").date(),
        )
    assert set(SEARCH_DISTRIBUTIONS) == set(TRIAL_BUDGETS)


def test_numeric_imputation_uses_only_observed_fit_window_values() -> None:
    frame = _features(4)
    frame["distance_miles"] = [100.0, 900.0, 450.0, 450.0]
    frame["is_missing_distance_miles"] = [0, 0, 1, 1]

    medians = _fit_numeric_medians_on_training_window(frame)
    _apply_numeric_medians(frame, medians)

    assert medians["distance_miles"] == 500.0
    assert frame["distance_miles"].tolist() == [100.0, 900.0, 500.0, 500.0]


def test_category_shift_reports_unknowns_and_total_variation() -> None:
    reference = _features(4)
    comparison = _features(4)
    comparison["Reporting_Airline"] = pd.Series(
        ["AA", "AA", "NEW", "NEW"], dtype="category"
    )

    shift = _category_distribution_shift(reference, comparison)

    assert shift["Reporting_Airline"]["unseen_comparison_rows"] == 2
    assert shift["Reporting_Airline"]["unseen_comparison_rate"] == 0.5
    assert shift["Reporting_Airline"]["total_variation_distance"] == 0.5


def test_scale_pos_weight_is_derived_from_training_ratio_only() -> None:
    sampled = {
        "scale_pos_weight_multiplier": 1.5,
        "n_estimators": 100,
        "learning_rate": 0.05,
        "max_depth": 4,
        "min_child_weight": 2,
        "subsample": 0.8,
        "colsample_bytree": 0.7,
        "reg_alpha": 1.0,
        "reg_lambda": 2.0,
    }

    params = _estimator_parameters(
        "xgboost",
        sampled,
        positive_negative_ratio=4.0,
        seed=42,
    )
    estimator = _make_estimator("xgboost", params)

    assert estimator.get_params()["scale_pos_weight"] == 6.0
    assert params["n_jobs"] == 1
    assert params["tree_method"] == "hist"
    assert params["objective"] == "binary:logistic"


def test_logistic_parameter_combinations_are_solver_compatible() -> None:
    for combination in SEARCH_DISTRIBUTIONS["logistic_regression"]["solver_penalty"]:
        solver, penalty = combination.split(":")
        params = _estimator_parameters(
            "logistic_regression",
            {
                "C": 1.0,
                "solver_penalty": combination,
                "class_weight": "balanced",
            },
            positive_negative_ratio=4.0,
            seed=42,
        )
        estimator = _make_estimator("logistic_regression", params)
        assert estimator.get_params()["solver"] == solver
        assert estimator.get_params()["penalty"] == penalty


def test_optimizer_refuses_to_overwrite_existing_outputs(tmp_path) -> None:
    output = tmp_path / "phase4_2_improvements"
    output.mkdir()
    (output / "do-not-overwrite.txt").write_text("protected", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        _check_output_directory(output)


def test_sparse_logistic_randomized_search_ranks_by_average_precision() -> None:
    rng = np.random.default_rng(42)
    x_train = sparse.csr_matrix(rng.normal(size=(80, 5)).astype(np.float32))
    y_train = np.asarray([0, 1] * 40, dtype=np.int8)
    x_validation = sparse.csr_matrix(rng.normal(size=(40, 5)).astype(np.float32))
    y_validation = np.asarray([0, 1] * 20, dtype=np.int8)

    summary, trials, best = _run_randomized_search(
        "logistic_regression",
        x_train,
        y_train,
        x_validation,
        y_validation,
        positive_negative_ratio=1.0,
        trial_count=3,
    )

    completed = [trial for trial in trials if trial["status"] == "completed"]
    assert len(trials) == 3
    assert summary["trials_completed"] == len(completed)
    assert summary["trials_pruned"] == 0
    assert summary["best_trial"] == max(
        completed, key=lambda trial: trial["metrics"]["pr_auc"]
    )["trial"]
    assert summary["best_inner_validation_average_precision"] == best["metrics"]["pr_auc"]
    assert all(trial["metrics"]["rows"] == len(y_validation) for trial in completed)
