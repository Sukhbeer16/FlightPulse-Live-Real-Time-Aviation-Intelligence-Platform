"""Focused tests for the Phase 4.4.1 imbalance pilot design."""

from pipelines.ml.improve_phase4_4_1 import (
    CURRENT_TUNED_RF,
    THRESHOLDS,
    _expansion_candidates,
    _pilot_candidates,
)


def test_pilot_only_varies_class_imbalance_controls_and_is_sequential() -> None:
    candidates = _pilot_candidates(3.75)

    assert tuple(candidates) == (
        "rf_unweighted",
        "rf_balanced",
        "rf_balanced_subsample",
        "xgb_unweighted",
        "xgb_train_ratio_weighted",
    )
    rf = [candidates[name].get_params() for name in tuple(candidates)[:3]]
    assert all(params["n_estimators"] == 100 for params in rf)
    assert all(params["max_depth"] == 16 for params in rf)
    assert all(params["n_jobs"] == 1 for params in rf)
    assert [params["class_weight"] for params in rf] == [
        None,
        "balanced",
        "balanced_subsample",
    ]
    xgb_plain = candidates["xgb_unweighted"].get_params()
    xgb_weighted = candidates["xgb_train_ratio_weighted"].get_params()
    assert xgb_plain["scale_pos_weight"] == 1.0
    assert xgb_weighted["scale_pos_weight"] == 3.75
    assert xgb_plain["n_jobs"] == xgb_weighted["n_jobs"] == 1


def test_threshold_grid_is_fixed_and_success_reference_is_current_tuned_forest() -> None:
    assert THRESHOLDS[0] == 0.05
    assert THRESHOLDS[-1] == 0.8
    assert len(THRESHOLDS) == 16
    assert CURRENT_TUNED_RF == {"accuracy": 0.6712758204754485, "f1": 0.30698117955577925}


def test_expansion_is_small_and_covers_requested_controls() -> None:
    candidates = _expansion_candidates(3.75)

    assert len(candidates) == 6
    rf = candidates["rf_tuned_structure_unweighted"].get_params()
    rf_weighted = candidates["rf_tuned_structure_balanced"].get_params()
    rf_regularized = candidates["rf_regularized_balanced_log2"].get_params()
    assert rf["n_estimators"] == rf_weighted["n_estimators"] == 171
    assert rf["class_weight"] is None
    assert rf_weighted["class_weight"] == "balanced"
    assert rf_regularized["max_depth"] == 12
    assert rf_regularized["min_samples_split"] == 200
    assert rf_regularized["min_samples_leaf"] == 150
    assert rf_regularized["max_features"] == "log2"

    xgb_plain = candidates["xgb_tuned_structure_unweighted"].get_params()
    xgb_half = candidates["xgb_tuned_structure_half_ratio"].get_params()
    xgb_regularized = candidates["xgb_regularized_half_ratio"].get_params()
    assert xgb_plain["scale_pos_weight"] == 1.0
    assert xgb_half["scale_pos_weight"] == 1.875
    assert xgb_regularized["max_depth"] == 3
    assert xgb_regularized["min_child_weight"] == 12
    assert xgb_regularized["reg_alpha"] == 2.0
    assert xgb_regularized["reg_lambda"] == 5.0
    assert all(model.get_params()["n_jobs"] == 1 for model in candidates.values())
