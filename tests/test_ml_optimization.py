"""Focused tests for chronological, bounded Phase 4.2.1 tuning."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from pipelines.ml.feature_dataset import FEATURE_ALLOWLIST, NUMERIC_FEATURES
from pipelines.ml.optimize_models import (
    SEARCH_DISTRIBUTIONS,
    TRIAL_EXECUTION_LIMITS,
    TRIAL_BUDGETS,
    _apply_numeric_medians,
    _category_distribution_shift,
    _chronological_order,
    _deterministic_training_sample,
    _estimator_parameters,
    _feature_importance_rows,
    _fit_numeric_medians_on_training_window,
    _make_estimator,
    _prepare_run_state,
    _run_fingerprint,
    _run_randomized_search,
    _threshold_metrics,
    _window_filters,
    _write_artifact_once,
    _write_json,
    make_optimizer_preprocessor,
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
        "logistic_regression": 8,
        "decision_tree": 8,
        "random_forest": 5,
        "xgboost": 8,
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
    assert all(
        1 <= TRIAL_EXECUTION_LIMITS[family] <= budget
        for family, budget in TRIAL_BUDGETS.items()
    )


def test_numeric_imputation_uses_only_observed_fit_window_values() -> None:
    frame = _features(4)
    frame["distance_miles"] = [100.0, 900.0, 450.0, 450.0]
    frame["is_missing_distance_miles"] = [0, 0, 1, 1]

    medians = _fit_numeric_medians_on_training_window(frame)
    _apply_numeric_medians(frame, medians)

    assert medians["distance_miles"] == 500.0
    assert frame["distance_miles"].tolist() == [100.0, 900.0, 500.0, 500.0]


def test_training_sample_is_reproducible_and_preserves_input_order() -> None:
    frame = _features(20)
    labels = np.asarray([0, 1] * 10, dtype=np.int8)

    sample_one, labels_one, indices_one = _deterministic_training_sample(
        frame, labels, sample_size=7, seed=19
    )
    sample_two, labels_two, indices_two = _deterministic_training_sample(
        frame, labels, sample_size=7, seed=19
    )

    assert indices_one.tolist() == indices_two.tolist()
    assert indices_one.tolist() == sorted(indices_one.tolist())
    assert sample_one.equals(sample_two)
    assert np.array_equal(labels_one, labels_two)
    with pytest.raises(ValueError, match="no larger"):
        _deterministic_training_sample(frame, labels, sample_size=21)


def test_chronological_order_stably_sorts_rows_by_date() -> None:
    dates = [
        pd.Timestamp("2024-02-01").date(),
        pd.Timestamp("2024-01-01").date(),
        pd.Timestamp("2024-02-01").date(),
        pd.Timestamp("2024-01-02").date(),
    ]

    assert _chronological_order(dates).tolist() == [1, 3, 0, 2]


def test_optimizer_preprocessor_uses_exact_21_allowlisted_features() -> None:
    frame = _features(40)
    preprocessor = make_optimizer_preprocessor()
    matrix = preprocessor.fit_transform(frame, np.asarray([0, 1] * 20))
    transformed_names = set(preprocessor.get_feature_names_out())
    frame_with_forbidden_fields = frame.assign(
        ArrDelay=np.arange(len(frame), dtype=np.float32),
        target_arr_delay_gt_15=np.asarray([0, 1] * 20),
    )
    transformed_with_forbidden_fields = preprocessor.transform(
        frame_with_forbidden_fields
    )

    assert matrix.shape[1] == len(transformed_names)
    assert all(name in transformed_names for name in NUMERIC_FEATURES)
    assert all(f"is_missing_{name}" in transformed_names for name in NUMERIC_FEATURES)
    assert sparse.issparse(matrix)
    assert (matrix != transformed_with_forbidden_fields).nnz == 0


def test_threshold_metrics_report_confusion_and_flagged_rate() -> None:
    labels = np.asarray([0, 1, 1, 0], dtype=np.int8)
    probabilities = np.asarray([0.1, 0.4, 0.8, 0.9])

    metrics = _threshold_metrics("fixture", labels, probabilities)
    at_half = next(row for row in metrics if row["threshold"] == 0.5)

    assert at_half["precision"] == 0.5
    assert at_half["recall"] == 0.5
    assert at_half["f1"] == 0.5
    assert at_half["f2"] == 0.5
    assert at_half["false_positives"] == 1
    assert at_half["false_negatives"] == 1
    assert at_half["flights_flagged"] == 2
    assert at_half["percent_flights_flagged"] == 50.0


def test_feature_importance_maps_categories_and_labels_model_method() -> None:
    class FixtureEstimator:
        feature_importances_ = np.asarray([0.6, 0.3, 0.1])

    names = ["Reporting_Airline_DL", "month", "is_missing_month"]
    forest_rows = _feature_importance_rows(
        "random_forest", FixtureEstimator(), names
    )
    xgboost_rows = _feature_importance_rows(
        "xgboost", FixtureEstimator(), names
    )

    assert forest_rows[0]["source_feature"] == "Reporting_Airline"
    assert forest_rows[0]["method"] == "tree_impurity_importance"
    assert xgboost_rows[0]["method"] == "xgboost_gain_importance"
    assert xgboost_rows[1]["source_feature"] == "month"


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


def test_run_state_recovers_matching_configuration_without_overwriting(
    tmp_path,
) -> None:
    output = tmp_path / "phase4_2_improvements"
    fingerprint, configuration = _run_fingerprint("dataset-hash")

    assert _prepare_run_state(output, fingerprint, configuration) is False
    assert _prepare_run_state(output, fingerprint, configuration) is True
    with pytest.raises(ValueError, match="different dataset"):
        _prepare_run_state(output, fingerprint, {**configuration, "seed": 99})

    state_path = output / "run_state.json"
    state = {
        "fingerprint": fingerprint,
        "configuration": configuration,
        "status": "completed",
    }
    _write_json(state, state_path)
    with pytest.raises(FileExistsError, match="already complete"):
        _prepare_run_state(output, fingerprint, configuration)


def test_artifact_writer_accepts_identical_content_only(tmp_path) -> None:
    destination = tmp_path / "artifact.csv"
    _write_artifact_once(destination, b"saved")
    _write_artifact_once(destination, b"saved")

    assert destination.read_bytes() == b"saved"
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        _write_artifact_once(destination, b"different")


def test_sparse_logistic_randomized_search_ranks_by_average_precision(
    tmp_path, monkeypatch
) -> None:
    rng = np.random.default_rng(42)
    x_train = sparse.csr_matrix(rng.normal(size=(80, 5)).astype(np.float32))
    y_train = np.asarray([0, 1] * 40, dtype=np.int8)
    x_validation = sparse.csr_matrix(rng.normal(size=(40, 5)).astype(np.float32))
    y_validation = np.asarray([0, 1] * 20, dtype=np.int8)
    fit_calls = []
    original_fit = LogisticRegression.fit

    def counted_fit(estimator, *args, **kwargs):
        fit_calls.append(estimator)
        return original_fit(estimator, *args, **kwargs)

    monkeypatch.setattr(LogisticRegression, "fit", counted_fit)

    summary, trials, best = _run_randomized_search(
        "logistic_regression",
        x_train,
        y_train,
        x_validation,
        y_validation,
        positive_negative_ratio=1.0,
        trial_count=3,
        checkpoint_path=tmp_path / "logistic_trials.json",
        run_fingerprint="fixture-fingerprint",
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
    assert summary["resumed_trials"] == 0
    assert len(fit_calls) == 3

    resumed_summary, resumed_trials, resumed_best = _run_randomized_search(
        "logistic_regression",
        x_train,
        y_train,
        x_validation,
        y_validation,
        positive_negative_ratio=1.0,
        trial_count=3,
        checkpoint_path=tmp_path / "logistic_trials.json",
        run_fingerprint="fixture-fingerprint",
    )

    assert resumed_summary["resumed_trials"] == 3
    assert resumed_trials == trials
    assert resumed_best == best
    assert len(fit_calls) == 3


def test_search_records_resource_capped_trials_without_fitting_them(tmp_path) -> None:
    rng = np.random.default_rng(7)
    x_train = sparse.csr_matrix(rng.normal(size=(40, 4)).astype(np.float32))
    y_train = np.asarray([0, 1] * 20, dtype=np.int8)
    x_validation = sparse.csr_matrix(rng.normal(size=(20, 4)).astype(np.float32))
    y_validation = np.asarray([0, 1] * 10, dtype=np.int8)

    summary, trials, _ = _run_randomized_search(
        "logistic_regression",
        x_train,
        y_train,
        x_validation,
        y_validation,
        positive_negative_ratio=1.0,
        trial_count=3,
        checkpoint_path=tmp_path / "capped_trials.json",
        run_fingerprint="capped-fixture",
        execution_limit=1,
        stop_reason="Test resource limit.",
    )

    assert summary["trials_completed"] == 1
    assert summary["trials_skipped"] == 2
    assert [trial["status"] for trial in trials] == [
        "completed",
        "skipped",
        "skipped",
    ]
    assert all(trial["skip_reason"] == "Test resource limit." for trial in trials[1:])
