"""Run the small, sequential Phase 4.4.1 imbalance and threshold pilot.

Only train and validation rows are read. Pilot candidates are a fixed,
reproducible set; there is no cross-validation or final-test access.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

from pipelines.ml import compare_phase4_4, optimize_models, train_models
from pipelines.ml.feature_dataset import FEATURE_ALLOWLIST


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = ROOT / "data" / "processed" / "ml" / "phase4_4_1"
THRESHOLDS = tuple(float(x) for x in np.arange(0.05, 0.801, 0.05))
SEED = 42
CURRENT_TUNED_RF = {"accuracy": 0.6712758204754485, "f1": 0.30698117955577925}


def _atomic_json(value: Any, destination: Path) -> None:
    temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(destination)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _frame_digest(frame: pd.DataFrame, labels: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=False, categorize=True).values.tobytes())
    digest.update(np.asarray(labels, dtype=np.int8).tobytes())
    return digest.hexdigest()


def _pilot_candidates(positive_negative_ratio: float) -> dict[str, Any]:
    """Compare weighting alone while holding model structure fixed."""
    rf_common = {
        "n_estimators": 100,
        "max_depth": 16,
        "min_samples_split": 400,
        "min_samples_leaf": 200,
        "max_features": "sqrt",
        "n_jobs": 1,
        "random_state": SEED,
    }
    xgb_common = {
        "objective": "binary:logistic",
        "eval_metric": "aucpr",
        "n_estimators": 250,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "max_bin": 128,
        "tree_method": "hist",
        "n_jobs": 1,
        "random_state": SEED,
    }
    return {
        "rf_unweighted": RandomForestClassifier(**rf_common, class_weight=None),
        "rf_balanced": RandomForestClassifier(**rf_common, class_weight="balanced"),
        "rf_balanced_subsample": RandomForestClassifier(
            **rf_common, class_weight="balanced_subsample"
        ),
        "xgb_unweighted": XGBClassifier(**xgb_common, scale_pos_weight=1.0),
        "xgb_train_ratio_weighted": XGBClassifier(
            **xgb_common, scale_pos_weight=positive_negative_ratio
        ),
    }


def _threshold_rows(
    candidate: str, truth: np.ndarray, probabilities: np.ndarray
) -> list[dict[str, Any]]:
    rows = []
    for threshold in THRESHOLDS:
        metrics = compare_phase4_4._metrics(truth, probabilities, threshold)
        rows.append({"candidate": candidate, **metrics})
    return rows


def _checkpoint_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pilot_fingerprint(train_hash: str, validation_hash: str, ratio: float) -> str:
    config = {
        "stage": "pilot",
        "train_rows_hash": train_hash,
        "validation_rows_hash": validation_hash,
        "feature_allowlist": list(FEATURE_ALLOWLIST),
        "positive_negative_ratio_train": ratio,
        "seed": SEED,
        "thresholds": list(THRESHOLDS),
        "candidate_names": [
            "rf_unweighted", "rf_balanced", "rf_balanced_subsample",
            "xgb_unweighted", "xgb_train_ratio_weighted",
        ],
    }
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def run_pilot(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Run/resume the fixed five-fit pilot, then save validation threshold curves."""
    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    output_directory.mkdir(parents=True, exist_ok=True)
    state_path = output_directory / "pilot_state.json"

    # These two calls are deliberately the only partition reads in this module.
    x_train, y_train = train_models._load_partition("train")
    x_validation, y_validation = train_models._load_partition("validation")
    train_models.validate_feature_names(x_train.columns.tolist())
    train_models.validate_feature_names(x_validation.columns.tolist())
    train_hash = _frame_digest(x_train, y_train)
    validation_hash = _frame_digest(x_validation, y_validation)
    ratio = float(np.count_nonzero(y_train == 0) / np.count_nonzero(y_train == 1))
    fingerprint = _pilot_fingerprint(train_hash, validation_hash, ratio)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != fingerprint:
            raise ValueError("Existing pilot checkpoints do not match current train/validation data.")
        if state.get("status") == "completed":
            report_path = output_directory / "pilot_results.json"
            if not report_path.is_file():
                raise ValueError("Completed pilot state is missing its report.")
            return json.loads(report_path.read_text(encoding="utf-8"))
    else:
        if any(output_directory.iterdir()):
            raise FileExistsError(f"Refusing to use a non-empty output directory: {output_directory}")
        state = {
            "fingerprint": fingerprint,
            "status": "running",
            "completed_candidates": {},
            "train_rows_hash": train_hash,
            "validation_rows_hash": validation_hash,
        }
        _atomic_json(state, state_path)

    preprocessor = optimize_models.make_optimizer_preprocessor()
    x_train_sparse = preprocessor.fit_transform(x_train, y_train)
    x_validation_sparse = preprocessor.transform(x_validation)
    if not sparse.issparse(x_train_sparse) or not sparse.issparse(x_validation_sparse):
        raise RuntimeError("The Phase 4.4.1 feature transform unexpectedly became dense.")
    x_train_sparse = x_train_sparse.tocsr()
    x_validation_sparse = x_validation_sparse.tocsr()
    del x_train, x_validation

    estimators = _pilot_candidates(ratio)
    candidate_results: dict[str, dict[str, Any]] = {}
    all_threshold_rows: list[dict[str, Any]] = []
    fit_seconds: dict[str, float] = {}
    for name, estimator in estimators.items():
        model_path = output_directory / f"{name}.joblib"
        probability_path = output_directory / f"{name}_validation_probabilities.npy"
        metrics_path = output_directory / f"{name}_threshold_metrics.json"
        if name in state["completed_candidates"]:
            saved = state["completed_candidates"][name]
            if (
                _checkpoint_hash(model_path) != saved["model_sha256"]
                or _checkpoint_hash(probability_path) != saved["probabilities_sha256"]
                or _checkpoint_hash(metrics_path) != saved["metrics_sha256"]
            ):
                raise ValueError(f"Pilot checkpoint checksum mismatch for {name}.")
            probabilities = np.load(probability_path, allow_pickle=False)
            rows = json.loads(metrics_path.read_text(encoding="utf-8"))
            candidate_results[name] = {"configuration": saved["configuration"], "thresholds": rows}
            all_threshold_rows.extend(rows)
            fit_seconds[name] = saved["fit_runtime_seconds"]
            print(f"Resumed pilot checkpoint: {name}", flush=True)
            continue

        print(f"Fitting pilot candidate sequentially: {name}", flush=True)
        fit_start = time.perf_counter()
        estimator.fit(x_train_sparse, y_train)
        duration = time.perf_counter() - fit_start
        temp_model = model_path.with_name(f".{model_path.stem}.{uuid.uuid4().hex}.tmp")
        joblib.dump(estimator, temp_model, compress=3)
        temp_model.replace(model_path)
        probabilities = estimator.predict_proba(x_validation_sparse)[:, 1].astype(np.float64)
        rows = _threshold_rows(name, y_validation, probabilities)
        temp_probs = probability_path.with_name(f".{probability_path.stem}.{uuid.uuid4().hex}.tmp")
        with temp_probs.open("wb") as handle:
            np.save(handle, probabilities, allow_pickle=False)
        temp_probs.replace(probability_path)
        _atomic_json(rows, metrics_path)
        configuration = compare_phase4_4._configuration(estimator)
        state["completed_candidates"][name] = {
            "model_sha256": _checkpoint_hash(model_path),
            "probabilities_sha256": _checkpoint_hash(probability_path),
            "metrics_sha256": _checkpoint_hash(metrics_path),
            "fit_runtime_seconds": duration,
            "configuration": configuration,
        }
        _atomic_json(state, state_path)
        candidate_results[name] = {"configuration": configuration, "thresholds": rows}
        all_threshold_rows.extend(rows)
        fit_seconds[name] = duration
        print(
            f"Checkpointed {name}: {duration:.1f}s; "
            f"best validation F1={max(row['f1'] for row in rows):.4f}",
            flush=True,
        )
        del estimator

    thresholds_frame = pd.DataFrame(all_threshold_rows)
    thresholds_frame.to_csv(output_directory / "pilot_thresholds.csv", index=False)
    summaries = {}
    for name, result in candidate_results.items():
        rows = result["thresholds"]
        at_half = min(rows, key=lambda row: abs(row["threshold"] - 0.5))
        best_f1 = max(rows, key=lambda row: (row["f1"], row["accuracy"]))
        qualifying = [
            row for row in rows
            if row["accuracy"] > CURRENT_TUNED_RF["accuracy"]
            and row["f1"] > CURRENT_TUNED_RF["f1"]
        ]
        best_joint = max(qualifying, key=lambda row: row["f1"]) if qualifying else None
        summaries[name] = {
            "configuration": result["configuration"],
            "threshold_0_5": at_half,
            "best_observed_f1_on_validation_grid": best_f1,
            "best_f1_threshold_meeting_both_current_tuned_rf_criteria": best_joint,
        }

    report = {
        "phase": "4.4.1",
        "stage": "pilot",
        "created_at_utc": created_at,
        "runtime_seconds": time.perf_counter() - started,
        "candidate_fit_runtime_seconds": fit_seconds,
        "candidate_fit_runtime_total_seconds": float(sum(fit_seconds.values())),
        "peak_working_set_mb": compare_phase4_4._peak_working_set_mb(),
        "seed": SEED,
        "thresholds": list(THRESHOLDS),
        "threshold_selection_note": (
            "The reported best threshold is selected on this validation partition; "
            "it is a validation result and is not an unbiased post-selection estimate."
        ),
        "current_tuned_random_forest_reference": CURRENT_TUNED_RF,
        "partition_counts": {
            "train": {
                "rows": int(len(y_train)),
                "delayed": int(np.count_nonzero(y_train == 1)),
                "non_delayed": int(np.count_nonzero(y_train == 0)),
                "positive_negative_ratio": ratio,
            },
            "validation": {
                "rows": int(len(y_validation)),
                "delayed": int(np.count_nonzero(y_validation == 1)),
                "non_delayed": int(np.count_nonzero(y_validation == 0)),
            },
        },
        "feature_contract": {"count": len(FEATURE_ALLOWLIST), "features": list(FEATURE_ALLOWLIST)},
        "final_test_partition_loaded_or_used": False,
        "candidates": summaries,
        "package_versions": {
            package: importlib.metadata.version(package)
            for package in ("scikit-learn", "xgboost", "numpy", "pandas", "pyarrow")
        },
    }
    _atomic_json(report, output_directory / "pilot_results.json")
    state["status"] = "completed"
    state["candidate_fit_runtime_seconds"] = fit_seconds
    _atomic_json(state, state_path)
    return report


def _expansion_candidates(positive_negative_ratio: float) -> dict[str, Any]:
    """Return six bounded parameter ablations motivated by the pilot results."""
    tuned = json.loads(
        (optimize_models.OUTPUT_DIRECTORY / "best_configurations.json").read_text(
            encoding="utf-8"
        )
    )
    rf_tuned = dict(tuned["random_forest"]["final_refit_parameters"])
    rf_tuned["n_jobs"] = 1
    xgb_tuned = dict(tuned["xgboost"]["final_refit_parameters"])
    xgb_tuned["n_jobs"] = 1
    xgb_tuned["early_stopping_rounds"] = None
    xgb_tuned["scale_pos_weight"] = 1.0
    xgb_half_weight = dict(xgb_tuned)
    xgb_half_weight["scale_pos_weight"] = positive_negative_ratio * 0.5
    xgb_regularized = {
        "objective": "binary:logistic",
        "eval_metric": "aucpr",
        "n_estimators": 300,
        "max_depth": 3,
        "learning_rate": 0.08,
        "min_child_weight": 12,
        "subsample": 0.8,
        "colsample_bytree": 0.75,
        "reg_alpha": 2.0,
        "reg_lambda": 5.0,
        "scale_pos_weight": positive_negative_ratio * 0.5,
        "max_bin": 128,
        "tree_method": "hist",
        "n_jobs": 1,
        "random_state": SEED,
    }
    return {
        "rf_tuned_structure_unweighted": RandomForestClassifier(
            **{**rf_tuned, "class_weight": None}
        ),
        "rf_tuned_structure_balanced": RandomForestClassifier(
            **{**rf_tuned, "class_weight": "balanced"}
        ),
        "rf_regularized_balanced_log2": RandomForestClassifier(
            n_estimators=100,
            max_depth=12,
            min_samples_split=200,
            min_samples_leaf=150,
            max_features="log2",
            class_weight="balanced",
            n_jobs=1,
            random_state=SEED,
        ),
        "xgb_tuned_structure_unweighted": XGBClassifier(**xgb_tuned),
        "xgb_tuned_structure_half_ratio": XGBClassifier(**xgb_half_weight),
        "xgb_regularized_half_ratio": XGBClassifier(**xgb_regularized),
    }


def run_expansion(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Run/resume the fixed, six-fit follow-up without changing the pilot outputs."""
    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    pilot_state_path = output_directory / "pilot_state.json"
    pilot_report_path = output_directory / "pilot_results.json"
    if not pilot_state_path.is_file() or not pilot_report_path.is_file():
        raise FileNotFoundError("Complete the Phase 4.4.1 pilot before expansion.")
    pilot_state = json.loads(pilot_state_path.read_text(encoding="utf-8"))
    pilot_report = json.loads(pilot_report_path.read_text(encoding="utf-8"))
    if pilot_state.get("status") != "completed":
        raise ValueError("The pilot is not marked completed; expansion is blocked.")

    # Explicitly load only the original training and validation partitions.
    x_train, y_train = train_models._load_partition("train")
    x_validation, y_validation = train_models._load_partition("validation")
    train_models.validate_feature_names(x_train.columns.tolist())
    train_models.validate_feature_names(x_validation.columns.tolist())
    train_hash = _frame_digest(x_train, y_train)
    validation_hash = _frame_digest(x_validation, y_validation)
    if (
        train_hash != pilot_state["train_rows_hash"]
        or validation_hash != pilot_state["validation_rows_hash"]
    ):
        raise ValueError("Train/validation rows differ from the completed pilot.")
    ratio = float(np.count_nonzero(y_train == 0) / np.count_nonzero(y_train == 1))
    estimators = _expansion_candidates(ratio)
    config_view = {
        name: compare_phase4_4._configuration(model)
        for name, model in estimators.items()
    }
    fingerprint_data = {
        "stage": "expansion",
        "pilot_fingerprint": pilot_state["fingerprint"],
        "configurations": config_view,
        "thresholds": list(THRESHOLDS),
        "seed": SEED,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    state_path = output_directory / "expansion_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != fingerprint:
            # Permit a resource-bounded candidate adjustment only when every
            # completed fit remains byte-verified and its exact config is unchanged.
            for completed_name, saved in state.get("completed_candidates", {}).items():
                if (
                    completed_name not in config_view
                    or saved.get("configuration") != config_view[completed_name]
                ):
                    raise ValueError(
                        "Expansion checkpoints do not match current data/configuration."
                    )
                for suffix, key in (
                    (".joblib", "model_sha256"),
                    ("_validation_probabilities.npy", "probabilities_sha256"),
                    ("_threshold_metrics.json", "metrics_sha256"),
                ):
                    if _checkpoint_hash(output_directory / f"{completed_name}{suffix}") != saved[key]:
                        raise ValueError(f"Completed checkpoint changed: {completed_name}")
            state["fingerprint"] = fingerprint
            state["resource_adjustment"] = (
                "An unfinished max_features=0.6 RF fit was stopped after exceeding "
                "900 CPU-seconds; it was replaced by max_features='log2'. "
                "Previously completed model checkpoints were verified and reused."
            )
            _atomic_json(state, state_path)
        if state.get("status") == "completed":
            report_path = output_directory / "expansion_results.json"
            if not report_path.is_file():
                raise ValueError("Completed expansion state is missing its report.")
            return json.loads(report_path.read_text(encoding="utf-8"))
    else:
        state = {
            "fingerprint": fingerprint,
            "status": "running",
            "completed_candidates": {},
        }
        _atomic_json(state, state_path)

    preprocessor = optimize_models.make_optimizer_preprocessor()
    x_train_sparse = preprocessor.fit_transform(x_train, y_train).tocsr()
    x_validation_sparse = preprocessor.transform(x_validation).tocsr()
    del x_train, x_validation
    candidate_results: dict[str, dict[str, Any]] = {}
    fit_seconds: dict[str, float] = {}
    for name, estimator in estimators.items():
        model_path = output_directory / f"{name}.joblib"
        probability_path = output_directory / f"{name}_validation_probabilities.npy"
        metrics_path = output_directory / f"{name}_threshold_metrics.json"
        if name in state["completed_candidates"]:
            saved = state["completed_candidates"][name]
            if (
                _checkpoint_hash(model_path) != saved["model_sha256"]
                or _checkpoint_hash(probability_path) != saved["probabilities_sha256"]
                or _checkpoint_hash(metrics_path) != saved["metrics_sha256"]
            ):
                raise ValueError(f"Expansion checkpoint checksum mismatch for {name}.")
            rows = json.loads(metrics_path.read_text(encoding="utf-8"))
            candidate_results[name] = {"configuration": saved["configuration"], "thresholds": rows}
            fit_seconds[name] = saved["fit_runtime_seconds"]
            print(f"Resumed expansion checkpoint: {name}", flush=True)
            continue
        print(f"Fitting expansion candidate sequentially: {name}", flush=True)
        fit_start = time.perf_counter()
        estimator.fit(x_train_sparse, y_train)
        duration = time.perf_counter() - fit_start
        temp_model = model_path.with_name(f".{model_path.stem}.{uuid.uuid4().hex}.tmp")
        joblib.dump(estimator, temp_model, compress=3)
        temp_model.replace(model_path)
        probabilities = estimator.predict_proba(x_validation_sparse)[:, 1].astype(np.float64)
        rows = _threshold_rows(name, y_validation, probabilities)
        temp_probs = probability_path.with_name(f".{probability_path.stem}.{uuid.uuid4().hex}.tmp")
        with temp_probs.open("wb") as handle:
            np.save(handle, probabilities, allow_pickle=False)
        temp_probs.replace(probability_path)
        _atomic_json(rows, metrics_path)
        configuration = compare_phase4_4._configuration(estimator)
        state["completed_candidates"][name] = {
            "model_sha256": _checkpoint_hash(model_path),
            "probabilities_sha256": _checkpoint_hash(probability_path),
            "metrics_sha256": _checkpoint_hash(metrics_path),
            "fit_runtime_seconds": duration,
            "configuration": configuration,
        }
        _atomic_json(state, state_path)
        candidate_results[name] = {"configuration": configuration, "thresholds": rows}
        fit_seconds[name] = duration
        print(
            f"Checkpointed {name}: {duration:.1f}s; "
            f"best validation F1={max(row['f1'] for row in rows):.4f}",
            flush=True,
        )
        del estimator

    all_rows: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for name, result in candidate_results.items():
        rows = result["thresholds"]
        all_rows.extend(rows)
        at_half = min(rows, key=lambda row: abs(row["threshold"] - 0.5))
        best_f1 = max(rows, key=lambda row: (row["f1"], row["accuracy"]))
        joint = [
            row for row in rows
            if row["accuracy"] > CURRENT_TUNED_RF["accuracy"]
            and row["f1"] > CURRENT_TUNED_RF["f1"]
        ]
        summaries[name] = {
            "configuration": result["configuration"],
            "threshold_0_5": at_half,
            "best_observed_f1_on_validation_grid": best_f1,
            "best_f1_threshold_meeting_both_current_tuned_rf_criteria": (
                max(joint, key=lambda row: row["f1"]) if joint else None
            ),
        }
    pd.DataFrame(all_rows).to_csv(output_directory / "expansion_thresholds.csv", index=False)
    report = {
        "phase": "4.4.1",
        "stage": "bounded_expansion",
        "created_at_utc": created_at,
        "runtime_seconds": time.perf_counter() - started,
        "candidate_fit_runtime_seconds": fit_seconds,
        "candidate_fit_runtime_total_seconds": float(sum(fit_seconds.values())),
        "peak_working_set_mb": compare_phase4_4._peak_working_set_mb(),
        "pilot_fingerprint": pilot_state["fingerprint"],
        "seed": SEED,
        "thresholds": list(THRESHOLDS),
        "threshold_selection_note": pilot_report["threshold_selection_note"],
        "current_tuned_random_forest_reference": CURRENT_TUNED_RF,
        "feature_contract": {"count": len(FEATURE_ALLOWLIST), "features": list(FEATURE_ALLOWLIST)},
        "final_test_partition_loaded_or_used": False,
        "candidates": summaries,
        "package_versions": {
            package: importlib.metadata.version(package)
            for package in ("scikit-learn", "xgboost", "numpy", "pandas", "pyarrow")
        },
    }
    _atomic_json(report, output_directory / "expansion_results.json")
    state["status"] = "completed"
    state["candidate_fit_runtime_seconds"] = fit_seconds
    _atomic_json(state, state_path)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("pilot", "expansion"), default="pilot")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    args = parser.parse_args(argv)
    result = run_pilot(args.output_dir) if args.stage == "pilot" else run_expansion(args.output_dir)
    for candidate, metrics in result["candidates"].items():
        best = metrics["best_f1_threshold_meeting_both_current_tuned_rf_criteria"]
        print(
            candidate,
            "threshold_0.5=", metrics["threshold_0_5"]["accuracy"], metrics["threshold_0_5"]["f1"],
            "best_f1=", metrics["best_observed_f1_on_validation_grid"]["threshold"],
            metrics["best_observed_f1_on_validation_grid"]["accuracy"],
            metrics["best_observed_f1_on_validation_grid"]["f1"],
            "joint_success=", bool(best),
        )
    print(f"{args.stage.title()} results saved to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
