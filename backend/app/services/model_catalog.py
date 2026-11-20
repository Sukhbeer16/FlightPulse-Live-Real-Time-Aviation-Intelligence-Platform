"""Validated inventory of existing saved model artifacts."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from backend.app.config.settings import get_settings
from backend.app.schemas.models import ModelCatalogEntry, ModelMetrics
from backend.app.services.delay_prediction import FEATURES


logger = logging.getLogger(__name__)
MODEL_DIRECTORY = Path("processed") / "ml" / "phase4_2"
MODEL_SPECS = (
    {
        "model_id": "phase4.2-logistic-regression-balanced",
        "candidate": "logistic_regression_balanced",
        "algorithm": "Logistic Regression",
        "artifact": "logistic_regression.joblib",
        "inference_supported": True,
    },
    {
        "model_id": "phase4.2-random-forest",
        "candidate": "random_forest",
        "algorithm": "Random Forest",
        "artifact": "random_forest.joblib",
        "inference_supported": True,
    },
    {
        "model_id": "phase4.2-decision-tree",
        "candidate": "decision_tree",
        "algorithm": "Decision Tree",
        "artifact": "decision_tree.joblib",
        "inference_supported": True,
    },
    {
        "model_id": "phase4.2-xgboost",
        "candidate": "xgboost",
        "algorithm": "XGBoost",
        "artifact": "xgboost.joblib",
        "inference_supported": True,
        "package": "xgboost",
    },
    {
        "model_id": "isolation-forest",
        "candidate": None,
        "algorithm": "Isolation Forest",
        "artifact": "isolation_forest.joblib",
        "task": "anomaly_detection",
        "inference_supported": True,
    },
)
_METRIC_NAMES = ("precision", "recall", "pr_auc", "roc_auc", "threshold")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _metrics(value: Any) -> ModelMetrics | None:
    if not isinstance(value, dict):
        return None
    try:
        return ModelMetrics(**{name: float(value[name]) for name in _METRIC_NAMES})
    except (KeyError, TypeError, ValueError):
        return None


@lru_cache(maxsize=8)
def _validate_artifact(
    artifact_path: str,
    expected_features: tuple[str, ...],
) -> tuple[bool, str | None]:
    try:
        import joblib

        model = joblib.load(artifact_path)
    except Exception as error:
        logger.warning(
            "Unable to load model artifact %s (%s).",
            Path(artifact_path).name,
            type(error).__name__,
        )
        return False, "The saved model artifact could not be loaded."

    if not callable(getattr(model, "predict_proba", None)):
        return False, "The saved model does not provide probability output."
    feature_names = getattr(model, "feature_names_in_", None)
    if feature_names is None or tuple(str(name) for name in feature_names) != expected_features:
        return False, "The saved model feature ordering is incompatible."
    return True, None


def _runtime_package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _unavailable_entry(
    spec: dict[str, Any],
    reason: str,
    *,
    model_version: str | None = None,
    training_period: str | None = None,
    feature_count: int | None = None,
) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        model_id=spec["model_id"],
        algorithm=spec["algorithm"],
        task=spec.get("task", "delay_prediction"),
        status="unavailable",
        artifact=spec["artifact"],
        inference_supported=False,
        model_version=model_version,
        training_period=training_period,
        feature_count=feature_count,
        reason=reason,
    )


def get_model_catalog() -> list[ModelCatalogEntry]:
    """Report only artifacts with a matching manifest and verified feature order."""
    model_directory = get_settings().data_directory / MODEL_DIRECTORY
    manifest = _read_json(model_directory / "experiment_manifest.json")
    if manifest is None:
        return [
            _unavailable_entry(
                spec, "The saved model manifest is not available or is invalid."
            )
            for spec in MODEL_SPECS
        ]

    feature_contract = manifest.get("features")
    model_selection = manifest.get("model_selection")
    software_versions = manifest.get("software_versions")
    if not all(
        isinstance(section, dict)
        for section in (feature_contract, model_selection, software_versions)
    ):
        return [
            _unavailable_entry(
                spec, "The saved model manifest is not available or is invalid."
            )
            for spec in MODEL_SPECS
        ]

    features = feature_contract.get("allowlist")
    expected_sklearn = software_versions.get("scikit_learn")
    installed_sklearn = _runtime_package_version("scikit-learn")
    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        dataset = {}
    date_coverage = dataset.get("date_coverage", [])
    training_period = (
        f"{date_coverage[0]} to {date_coverage[1]}"
        if (
            isinstance(date_coverage, list)
            and len(date_coverage) == 2
            and all(isinstance(value, str) for value in date_coverage)
        )
        else None
    )
    feature_count = len(features) if isinstance(features, list) else None
    manifest_valid = (
        features == FEATURES
        and model_selection.get("selected_candidate") == "logistic_regression_balanced"
        and expected_sklearn == installed_sklearn
    )

    validation_report = _read_json(model_directory / "validation_metrics.json") or {}
    validation_candidates = validation_report.get("candidates", {})
    if not isinstance(validation_candidates, dict):
        validation_candidates = {}
    final_report = _read_json(model_directory / "final_test_metrics.json") or {}
    final_candidate = final_report.get("selected_candidate")
    final_metrics = final_report.get("metrics")
    result: list[ModelCatalogEntry] = []

    for spec in MODEL_SPECS:
        if spec.get("task") == "anomaly_detection":
            isolation_artifact = model_directory / "isolation_forest.joblib"
            isolation_manifest = _read_json(
                model_directory / "isolation_forest_manifest.json"
            )
            if not isolation_artifact.is_file() or isolation_manifest is None:
                result.append(
                    _unavailable_entry(
                        spec, "No trained Isolation Forest artifact is available."
                    )
                )
            elif isolation_manifest.get("features", {}).get("allowlist") != FEATURES:
                result.append(
                    _unavailable_entry(
                        spec, "The Isolation Forest feature contract is incompatible."
                    )
                )
            else:
                try:
                    import joblib
                    isolation_model = joblib.load(isolation_artifact)
                    if not callable(getattr(isolation_model, "decision_function", None)):
                        raise ValueError("missing decision_function")
                except Exception:
                    result.append(
                        _unavailable_entry(
                            spec, "The saved Isolation Forest artifact could not be loaded."
                        )
                    )
                else:
                    result.append(
                        ModelCatalogEntry(
                            model_id=spec["model_id"],
                            algorithm=spec["algorithm"],
                            task="anomaly_detection",
                            status="available",
                            artifact=spec["artifact"],
                            inference_supported=True,
                            model_version=isolation_manifest.get("model_id"),
                            training_period=(
                                isolation_manifest.get("training", {}).get("dataset")
                            ),
                            feature_count=21,
                            reason=None,
                        )
                    )
            continue

        reason = None
        if not manifest_valid:
            reason = "The model manifest, runtime version, or feature contract is incompatible."
        elif spec.get("package"):
            expected_package_version = software_versions.get(spec["package"])
            if expected_package_version != _runtime_package_version(spec["package"]):
                reason = "The installed model package version does not match the artifact."

        artifact_path = model_directory / spec["artifact"]
        if reason is None and not artifact_path.is_file():
            reason = "The saved model artifact is not available."
        if reason is None:
            compatible, reason = _validate_artifact(
                str(artifact_path.resolve()), tuple(FEATURES)
            )
            if not compatible and reason is None:
                reason = "The saved model artifact is incompatible."

        if reason is not None:
            result.append(
                _unavailable_entry(
                    spec,
                    reason,
                    model_version="phase4.2",
                    training_period=training_period,
                    feature_count=feature_count,
                )
            )
            continue

        candidate = spec["candidate"]
        validation_metrics = _metrics(validation_candidates.get(candidate))
        test_metrics = (
            _metrics(final_metrics)
            if final_candidate == candidate and isinstance(final_metrics, dict)
            else None
        )
        result.append(
            ModelCatalogEntry(
                model_id=spec["model_id"],
                algorithm=spec["algorithm"],
                task="delay_prediction",
                status="available",
                artifact=spec["artifact"],
                inference_supported=spec["inference_supported"],
                model_version="phase4.2",
                training_period=training_period,
                feature_count=feature_count,
                validation_metrics=validation_metrics,
                test_metrics=test_metrics,
            )
        )
    return result
