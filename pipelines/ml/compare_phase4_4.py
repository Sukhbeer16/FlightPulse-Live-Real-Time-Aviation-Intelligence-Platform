"""Compare retrained Phase 4.2 baselines with Phase 4.2.1 tuned models.

Only the verified chronological training and validation partitions are loaded.
The final test partition is never read by this experiment.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier

from pipelines.ml import optimize_models, train_models
from pipelines.ml.feature_dataset import FEATURE_ALLOWLIST


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = ROOT / "data" / "processed" / "ml" / "phase4_4"
TUNED_DIRECTORY = optimize_models.OUTPUT_DIRECTORY
PHASE42_DIRECTORY = train_models.OUTPUT_DIRECTORY
FAMILIES = ("logistic_regression", "decision_tree", "random_forest", "xgboost")
THRESHOLD = 0.5
SEED = 42


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(value: Mapping[str, Any], path: Path) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _atomic_joblib(value: Any, path: Path) -> None:
    temp = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        joblib.dump(value, temp, compress=3)
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _atomic_numpy(value: np.ndarray, path: Path) -> None:
    temp = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("wb") as handle:
            np.save(handle, value, allow_pickle=False)
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _peak_working_set_mb() -> float | None:
    """Read the current process peak working set on Windows without dependencies."""
    if os.name != "nt":
        try:
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return float(peak / (1024 * 1024 if sys.platform == "darwin" else 1024))
        except (ImportError, OSError, AttributeError):
            return None

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        ctypes.c_ulong,
    )
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
    return counters.PeakWorkingSetSize / (1024 * 1024) if ok else None


def _metrics(
    truth: Sequence[int] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    threshold: float = THRESHOLD,
) -> dict[str, Any]:
    """Report threshold, ranking and false-positive alert metrics."""
    result = train_models.calculate_metrics(truth, probabilities, threshold=threshold)
    cm = result["confusion_matrix"]
    negatives = cm["true_negative"] + cm["false_positive"]
    result["false_positive_rate"] = (
        cm["false_positive"] / negatives if negatives else 0.0
    )
    result["false_positive_alerts_per_100_flights"] = (
        100.0 * cm["false_positive"] / result["rows"]
    )
    result["alert_rate"] = (
        cm["false_positive"] + cm["true_positive"]
    ) / result["rows"]
    return result


def _baseline_estimators() -> dict[str, Any]:
    """Phase 4.2 settings, one worker; XGBoost uses fixed rounds for holdout integrity."""
    return {
        "logistic_regression": LogisticRegression(
            solver="saga",
            max_iter=1_000,
            tol=1e-3,
            class_weight="balanced",
            random_state=SEED,
        ),
        "decision_tree": DecisionTreeClassifier(
            max_depth=16,
            min_samples_leaf=200,
            min_samples_split=400,
            random_state=SEED,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            max_depth=16,
            min_samples_leaf=200,
            min_samples_split=400,
            max_features="sqrt",
            n_jobs=1,
            random_state=SEED,
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
            n_jobs=1,
            random_state=SEED,
        ),
    }


def _configuration(estimator: Any) -> dict[str, Any]:
    params = estimator.get_params(deep=False)
    return {
        str(key): (
            None
            if isinstance(value, (float, np.floating)) and not np.isfinite(value)
            else value.item() if isinstance(value, np.generic) else value
        )
        for key, value in sorted(params.items())
        if value is None or isinstance(value, (str, int, float, bool, np.generic))
    }


def _write_confusion_matrices(
    models: Mapping[str, Mapping[str, Any]], path: Path
) -> None:
    rows = []
    for family in FAMILIES:
        for phase in ("baseline", "tuned"):
            cm = models[family][phase]["metrics"]["confusion_matrix"]
            rows.append({"model_family": family, "model_version": phase, **cm})
    pd.DataFrame(rows).to_csv(path, index=False)


def _plot_confusions(models: Mapping[str, Mapping[str, Any]], path: Path) -> None:
    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    for column, family in enumerate(FAMILIES):
        for row, phase in enumerate(("baseline", "tuned")):
            cm = models[family][phase]["metrics"]["confusion_matrix"]
            matrix = np.array(
                [
                    [cm["true_negative"], cm["false_positive"]],
                    [cm["false_negative"], cm["true_positive"]],
                ]
            )
            axis = axes[row, column]
            image = axis.imshow(matrix, cmap="Blues")
            axis.set(
                xticks=[0, 1],
                yticks=[0, 1],
                xticklabels=["non-delayed", "delayed"],
                yticklabels=["non-delayed", "delayed"],
                title=f"{family.replace('_', ' ').title()} — {phase}",
                xlabel="Predicted",
                ylabel="Actual",
            )
            for r in range(2):
                for c in range(2):
                    axis.text(c, r, f"{matrix[r, c]:,}", ha="center", va="center")
            fig.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _assert_artifacts_unchanged(before: Mapping[str, str]) -> None:
    for label, expected in before.items():
        path = ROOT / label
        if not path.is_file() or _sha256(path) != expected:
            raise RuntimeError(f"Protected artifact changed during Phase 4.4: {label}")


def _protected_hashes() -> dict[str, str]:
    files = [
        *(PHASE42_DIRECTORY / name for name in (
            "validation_metrics.json",
            "experiment_manifest.json",
            "preprocessor.joblib",
            "logistic_regression.joblib",
            "decision_tree.joblib",
            "random_forest.joblib",
            "xgboost.joblib",
            "final_test_metrics.json",
        )),
        *(TUNED_DIRECTORY / name for name in (
            "best_configurations.json",
            "optimized_validation_metrics.json",
            "experiment_manifest.json",
            "logistic_regression_optimized.joblib",
            "decision_tree_optimized.joblib",
            "random_forest_optimized.joblib",
            "xgboost_optimized.joblib",
        )),
    ]
    files.extend(sorted((ROOT / "data/processed/ml/phase4_3").glob("*")))
    if any(not path.is_file() for path in files):
        raise FileNotFoundError("A protected Phase 4.2/4.2.1/4.3 artifact is missing.")
    return {str(path.relative_to(ROOT)): _sha256(path) for path in files}


def run_comparison(output_directory: Path = OUTPUT_DIRECTORY) -> dict[str, Any]:
    """Run or resume a single controlled comparison in an isolated directory."""
    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    state_path = output_directory / "run_state.json"
    if output_directory.exists() and any(output_directory.iterdir()) and not state_path.exists():
        raise FileExistsError(
            f"Phase 4.4 output is not empty; refusing to overwrite: {output_directory}"
        )

    dataset_manifest = train_models._validate_dataset_manifest()
    input_hash = _sha256(train_models.DATASET_PATH)
    protected_before = _protected_hashes()
    tuned_manifest_path = TUNED_DIRECTORY / "experiment_manifest.json"
    tuned_manifest = json.loads(tuned_manifest_path.read_text(encoding="utf-8"))
    if tuned_manifest.get("feature_contract", {}).get("allowlist") != list(FEATURE_ALLOWLIST):
        raise ValueError("Phase 4.2.1 feature allowlist does not match current contract.")
    tuned_metrics = json.loads(
        (TUNED_DIRECTORY / "optimized_validation_metrics.json").read_text(encoding="utf-8")
    )
    tuned_config = json.loads(
        (TUNED_DIRECTORY / "best_configurations.json").read_text(encoding="utf-8")
    )
    if set(tuned_metrics) != set(FAMILIES) or set(tuned_config) != set(FAMILIES):
        raise ValueError("Phase 4.2.1 is missing one or more tuned model records.")

    config = {
        "dataset_sha256": input_hash,
        "features": list(FEATURE_ALLOWLIST),
        "threshold": THRESHOLD,
        "seed": SEED,
        "families": list(FAMILIES),
        "baseline_configuration_source": "Phase 4.2 fixed configurations",
        "baseline_xgboost_early_stopping": False,
        "training_partition": "2024-01-01 through 2024-02-11",
        "validation_partition": "2024-02-12 through 2024-02-20",
        "final_test_partition_loaded": False,
    }
    fingerprint = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    output_directory.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != fingerprint:
            raise ValueError("Existing Phase 4.4 checkpoint does not match this run.")
        if state.get("status") == "completed":
            report_path = output_directory / "phase4_4_comparison.json"
            if not report_path.is_file():
                raise ValueError("Completed Phase 4.4 checkpoint lacks its report.")
            return json.loads(report_path.read_text(encoding="utf-8"))
    else:
        state = {
            "fingerprint": fingerprint,
            "configuration": config,
            "status": "running",
            "models": {},
        }
        _atomic_json(state, state_path)

    x_train, y_train = train_models._load_partition("train")
    x_validation, y_validation = train_models._load_partition("validation")
    preprocessor = optimize_models.make_optimizer_preprocessor()
    x_train_sparse = preprocessor.fit_transform(x_train, y_train)
    if not sparse.issparse(x_train_sparse):
        raise RuntimeError("Phase 4.4 training transform unexpectedly became dense.")
    x_train_sparse = x_train_sparse.tocsr()
    del x_train
    x_validation_sparse = preprocessor.transform(x_validation)
    if not sparse.issparse(x_validation_sparse):
        raise RuntimeError("Phase 4.4 validation transform unexpectedly became dense.")
    x_validation_sparse = x_validation_sparse.tocsr()
    del x_validation
    if x_train_sparse.shape[1] != x_validation_sparse.shape[1]:
        raise RuntimeError("Training and validation feature maps have different widths.")

    estimators = _baseline_estimators()
    baseline_configs = {family: _configuration(estimator) for family, estimator in estimators.items()}
    baseline_results: dict[str, dict[str, Any]] = {}
    durations: dict[str, float] = {}
    for family in FAMILIES:
        model_path = output_directory / f"baseline_{family}.joblib"
        probability_path = output_directory / f"baseline_{family}_validation_probabilities.npy"
        metrics_path = output_directory / f"baseline_{family}_validation_metrics.json"
        if family in state["models"]:
            record = state["models"][family]
            if (
                not model_path.is_file()
                or _sha256(model_path) != record["model_sha256"]
                or not probability_path.is_file()
                or _sha256(probability_path) != record["probabilities_sha256"]
            ):
                raise ValueError(f"Checkpoint artifacts are incomplete for {family}.")
            probabilities = np.load(probability_path, allow_pickle=False)
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            durations[family] = record["fit_runtime_seconds"]
            baseline_results[family] = {"metrics": metrics, "probabilities": probabilities}
            print(f"Resumed completed baseline: {family}", flush=True)
            continue

        estimator = estimators[family]
        print(f"Fitting baseline sequentially: {family}", flush=True)
        fit_started = time.perf_counter()
        estimator.fit(x_train_sparse, y_train)
        fit_seconds = time.perf_counter() - fit_started
        _atomic_joblib(estimator, model_path)
        probabilities = estimator.predict_proba(x_validation_sparse)[:, 1].astype(np.float64)
        metrics = _metrics(y_validation, probabilities)
        _atomic_numpy(probabilities, probability_path)
        _atomic_json(metrics, metrics_path)
        state["models"][family] = {
            "model_sha256": _sha256(model_path),
            "probabilities_sha256": _sha256(probability_path),
            "fit_runtime_seconds": fit_seconds,
            "metrics": metrics,
            "status": "completed",
        }
        _atomic_json(state, state_path)
        baseline_results[family] = {"metrics": metrics, "probabilities": probabilities}
        durations[family] = fit_seconds
        print(
            f"Checkpointed {family}: {fit_seconds:.1f}s, "
            f"validation F2={metrics['f2']:.6f}, AP={metrics['pr_auc']:.6f}",
            flush=True,
        )
        del estimator

    models: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        baseline_metrics = baseline_results[family]["metrics"]
        tuned_family_metrics = dict(tuned_metrics[family])
        cm = tuned_family_metrics["confusion_matrix"]
        negatives = cm["true_negative"] + cm["false_positive"]
        tuned_family_metrics["false_positive_rate"] = cm["false_positive"] / negatives if negatives else 0.0
        tuned_family_metrics["false_positive_alerts_per_100_flights"] = (
            100.0 * cm["false_positive"] / tuned_family_metrics["rows"]
        )
        tuned_family_metrics["alert_rate"] = (
            cm["false_positive"] + cm["true_positive"]
        ) / tuned_family_metrics["rows"]
        models[family] = {
            "baseline": {
                "threshold": THRESHOLD,
                "configuration": baseline_configs[family],
                "metrics": baseline_metrics,
                "artifact_path": f"baseline_{family}.joblib",
            },
            "tuned": {
                "threshold": THRESHOLD,
                "configuration": tuned_config[family]["final_refit_parameters"],
                "metrics": tuned_family_metrics,
                "artifact_path": tuned_config[family]["artifact_path"],
            },
            "metric_deltas_tuned_minus_baseline": {
                metric: tuned_family_metrics[metric] - baseline_metrics[metric]
                for metric in (
                    "accuracy", "precision", "recall", "f1", "f2", "roc_auc",
                    "pr_auc", "balanced_accuracy", "false_positive_rate",
                    "false_positive_alerts_per_100_flights", "alert_rate",
                )
            },
        }

    _write_confusion_matrices(models, output_directory / "confusion_matrices.csv")
    _plot_confusions(models, output_directory / "confusion_matrices.png")
    report = {
        "phase": "4.4",
        "created_at_utc": created_at,
        "runtime_seconds": time.perf_counter() - started,
        "baseline_fit_runtime_seconds": durations,
        "peak_working_set_mb": _peak_working_set_mb(),
        "random_seed": SEED,
        "threshold": THRESHOLD,
        "comparison_partition": "validation",
        "partition_dates": {
            "train": ["2024-01-01", "2024-02-11"],
            "validation": ["2024-02-12", "2024-02-20"],
        },
        "partition_counts": {
            "train": {
                "rows": int(len(y_train)),
                "delayed": int(np.count_nonzero(y_train == 1)),
                "non_delayed": int(np.count_nonzero(y_train == 0)),
            },
            "validation": {
                "rows": int(len(y_validation)),
                "delayed": int(np.count_nonzero(y_validation == 1)),
                "non_delayed": int(np.count_nonzero(y_validation == 0)),
            },
        },
        "feature_contract": {
            "feature_count": len(FEATURE_ALLOWLIST),
            "features": list(FEATURE_ALLOWLIST),
            "categorical": list(optimize_models.CATEGORICAL_FEATURES),
            "numeric_and_missing_indicators": [
                *optimize_models.NUMERIC_FEATURES,
                *optimize_models.MISSING_INDICATOR_FEATURES,
            ],
            "encoding": "OneHotEncoder(handle_unknown='ignore')",
            "numeric_scaling": "StandardScaler(with_mean=False)",
            "fit_partition": "train only",
        },
        "baseline_configuration_notes": {
            "logistic_regression": "Phase 4.2 balanced Logistic Regression candidate",
            "all_models": "Phase 4.2 fixed settings; worker count set to one",
            "xgboost": (
                "Fixed 250 estimators with early stopping disabled. The Phase 4.2 "
                "implementation used validation for early stopping; it is disabled "
                "here so validation remains an evaluation partition in Phase 4.4."
            ),
        },
        "models": models,
        "final_test_partition_loaded_or_used": False,
        "source_dataset": {
            "path": str(train_models.DATASET_PATH.relative_to(ROOT)),
            "sha256": input_hash,
            "manifest_sha256": _sha256(train_models.DATASET_MANIFEST),
            "verified_rows": dataset_manifest["rows_written"],
        },
        "protected_artifact_hashes_before": protected_before,
        "package_versions": {
            package: importlib.metadata.version(package)
            for package in ("scikit-learn", "xgboost", "numpy", "pandas", "pyarrow")
        },
    }
    if _sha256(train_models.DATASET_PATH) != input_hash:
        raise RuntimeError("Feature dataset changed during Phase 4.4.")
    _assert_artifacts_unchanged(protected_before)
    _atomic_json(report, output_directory / "phase4_4_comparison.json")
    state["status"] = "completed"
    state["runtime_seconds"] = report["runtime_seconds"]
    state["peak_working_set_mb"] = report["peak_working_set_mb"]
    _atomic_json(state, state_path)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    args = parser.parse_args(argv)
    report = run_comparison(args.output_dir)
    print(json.dumps(report["models"], indent=2))
    peak_mb = report.get("peak_working_set_mb")
    peak_text = f"{peak_mb:.1f} MB" if peak_mb is not None else "unavailable"
    print(
        "Phase 4.4 completed: "
        f"{report['runtime_seconds']:.1f}s packaging runtime, "
        f"peak working set {peak_text}"
    )
    print(f"Report: {args.output_dir / 'phase4_4_comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
