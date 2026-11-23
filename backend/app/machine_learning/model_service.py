"""Thread-safe ML model service for training, loading, and real-time inference."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from backend.app.config.settings import get_settings
from backend.app.feature_engineering.features import (
    FEATURE_ALLOWLIST,
    to_feature_dataframe,
    validate_feature_contract,
)

logger = logging.getLogger(__name__)

PRIMARY_MODEL_DIR = Path("processed") / "ml" / "phase4_2"
FALLBACK_MODEL_DIR = Path("models") / "delay"

MODEL_SPECS: dict[str, dict[str, str]] = {
    "logistic-regression": {
        "artifact": "logistic_regression.joblib",
        "model_id": "phase4.2-logistic-regression-balanced",
    },
    "random-forest": {
        "artifact": "random_forest.joblib",
        "model_id": "phase4.2-random-forest",
    },
    "decision-tree": {
        "artifact": "decision_tree.joblib",
        "model_id": "phase4.2-decision-tree",
    },
    "xgboost": {
        "artifact": "xgboost.joblib",
        "model_id": "phase4.2-xgboost",
    },
}

MODEL_CANDIDATE_KEYS: dict[str, str] = {
    "logistic-regression": "logistic_regression_unweighted",
    "random-forest": "random_forest",
    "decision-tree": "decision_tree",
    "xgboost": "xgboost",
}


class ModelLoadError(RuntimeError):
    """Raised when a requested ML model artifact cannot be loaded."""


class MLModelService:
    """Singleton service managing trained model pipelines and real-time inference."""

    _instance: MLModelService | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_directory: Path | None = None):
        if getattr(self, "_initialized", False):
            if model_directory != self._custom_model_dir:
                self._custom_model_dir = model_directory
                self._cached_models.clear()
                self._cached_manifest = None
                self._cached_validation_metrics = None
            return
        self._custom_model_dir = model_directory
        self._cached_models: dict[str, tuple[Pipeline, dict[str, Any]]] = {}
        self._cached_manifest: dict[str, Any] | None = None
        self._cached_validation_metrics: dict[str, Any] | None = None
        self._model_lock = threading.Lock()
        self._initialized = True

    def resolve_model_directory(self) -> Path:
        """Find the active model directory from configuration or standard paths."""
        if self._custom_model_dir is not None:
            return self._custom_model_dir

        base = get_settings().data_directory
        primary = base / PRIMARY_MODEL_DIR
        if primary.is_dir() and (primary / "experiment_manifest.json").is_file():
            return primary

        fallback = Path(FALLBACK_MODEL_DIR)
        if fallback.is_dir() and (fallback / "metadata.json").is_file():
            return fallback

        # Also check root data
        root_primary = Path("data") / PRIMARY_MODEL_DIR
        if root_primary.is_dir():
            return root_primary

        return primary

    def load_manifest(self) -> dict[str, Any]:
        """Load experiment manifest containing preprocessing parameters and medians."""
        if self._cached_manifest is not None:
            return self._cached_manifest

        model_dir = self.resolve_model_directory()
        manifest_path = model_dir / "experiment_manifest.json"
        if not manifest_path.is_file():
            manifest_path = model_dir / "metadata.json"
        if not manifest_path.is_file():
            raise ModelLoadError(f"Model manifest not found in {model_dir}")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._cached_manifest = manifest
            return manifest
        except Exception as exc:
            raise ModelLoadError(f"Failed to read model manifest: {exc}") from exc

    def load_validation_metrics(self) -> dict[str, Any]:
        """Load validation metrics report for dynamic best model selection."""
        if self._cached_validation_metrics is not None:
            return self._cached_validation_metrics

        model_dir = self.resolve_model_directory()
        metrics_path = model_dir / "validation_metrics.json"
        if not metrics_path.is_file():
            metrics_path = model_dir / "metrics.json"
        if not metrics_path.is_file():
            # Try to get from manifest
            manifest = self.load_manifest()
            if "validation_metrics" in manifest:
                val = {"candidates": manifest["validation_metrics"]}
                self._cached_validation_metrics = val
                return val
            raise ModelLoadError(f"Validation metrics not found in {model_dir}")

        try:
            data = json.loads(metrics_path.read_text(encoding="utf-8"))
            self._cached_validation_metrics = data
            return data
        except Exception as exc:
            raise ModelLoadError(f"Failed to read validation metrics: {exc}") from exc

    def select_best_model(self) -> tuple[str, float, dict[str, Any]]:
        """Select the highest validation F2 model among the 4 candidate families.

        Returns (model_name, threshold, selection_metadata).
        """
        metrics_data = self.load_validation_metrics()
        candidates = metrics_data.get("candidates", {})
        if not candidates:
            raise ModelLoadError("No candidates listed in validation metrics report.")

        # Rank candidate families
        ranked = []
        for name, key in MODEL_CANDIDATE_KEYS.items():
            if key not in candidates:
                # Check alternative key
                key = "logistic_regression_balanced" if name == "logistic-regression" else key
            if key in candidates:
                cand_metrics = candidates[key]
                f2 = float(cand_metrics.get("f2", 0.0))
                pr_auc = float(cand_metrics.get("pr_auc", 0.0))
                recall = float(cand_metrics.get("recall", 0.0))
                precision = float(cand_metrics.get("precision", 0.0))
                threshold = float(cand_metrics.get("threshold", 0.5))
                ranked.append(((f2, pr_auc, recall, precision), threshold, name))

        if not ranked:
            raise ModelLoadError("None of the standard candidate families found in validation metrics.")

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_rank, best_threshold, best_model_name = ranked[0]
        metadata = {
            "best_model": best_model_name,
            "metric": "validation F2",
            "metric_value": best_rank[0],
            "threshold": best_threshold,
            "compared_count": len(ranked),
        }
        return best_model_name, best_threshold, metadata

    def load_model(self, model_name: str = "best") -> tuple[Pipeline, dict[str, Any], float]:
        """Load and cache the specified model pipeline once into memory."""
        if model_name == "best":
            selected_name, default_threshold, _ = self.select_best_model()
            actual_name = selected_name
        else:
            actual_name = model_name
            default_threshold = 0.5

        if actual_name not in MODEL_SPECS:
            raise ModelLoadError(f"Unsupported model name: {actual_name}. Choices: {list(MODEL_SPECS)}")

        with self._model_lock:
            if actual_name in self._cached_models:
                pipe, manifest = self._cached_models[actual_name]
                threshold = self._get_candidate_threshold(actual_name, manifest)
                return pipe, manifest, threshold

            model_dir = self.resolve_model_directory()
            artifact_name = MODEL_SPECS[actual_name]["artifact"]
            artifact_path = model_dir / artifact_name
            if not artifact_path.is_file():
                # Check fallback model.joblib if directory has single model
                alt_path = model_dir / "model.joblib"
                if alt_path.is_file() and actual_name == "logistic-regression":
                    artifact_path = alt_path
                else:
                    raise ModelLoadError(f"Model artifact not found: {artifact_path}")

            manifest = self.load_manifest()

            # Version and feature contract checks
            expected_features = manifest.get("features", {}).get("allowlist", list(FEATURE_ALLOWLIST))
            validate_feature_contract(expected_features)

            try:
                pipeline = joblib.load(artifact_path)
            except Exception as exc:
                raise ModelLoadError(f"Failed to deserialize {actual_name} pipeline: {exc}") from exc

            # Verify pipeline capabilities
            if not callable(getattr(pipeline, "predict_proba", None)):
                raise ModelLoadError(f"{actual_name} does not provide probability outputs.")

            threshold = self._get_candidate_threshold(actual_name, manifest)
            self._cached_models[actual_name] = (pipeline, manifest)
            logger.info("Successfully loaded ML pipeline: %s (threshold: %.4f)", actual_name, threshold)
            return pipeline, manifest, threshold

    def _get_candidate_threshold(self, model_name: str, manifest: dict[str, Any]) -> float:
        """Extract the validation-tuned threshold for a candidate from manifest."""
        candidate_key = MODEL_CANDIDATE_KEYS.get(model_name, model_name)
        val_metrics = manifest.get("validation_metrics", {})
        if candidate_key in val_metrics:
            return float(val_metrics[candidate_key].get("threshold", 0.5))

        # Check validation_metrics.json
        try:
            report = self.load_validation_metrics()
            candidates = report.get("candidates", {})
            if candidate_key in candidates:
                return float(candidates[candidate_key].get("threshold", 0.5))
        except Exception:
            pass

        return 0.5

    def predict_delay_probability(
        self,
        features: dict[str, Any] | pd.DataFrame,
        model_name: str = "best",
    ) -> dict[str, Any]:
        """Perform real-time delay inference on a 21-feature row or DataFrame.

        Returns predictions, probability, threshold, and latency.
        """
        start_time = time.perf_counter()
        pipeline, manifest, threshold = self.load_model(model_name)

        if isinstance(features, dict):
            validate_feature_contract(list(features.keys()))
            frame = to_feature_dataframe([features])
        elif isinstance(features, pd.DataFrame):
            validate_feature_contract(list(features.columns))
            frame = features
        else:
            raise ValueError("Input must be a feature dict or DataFrame.")

        try:
            probabilities = pipeline.predict_proba(frame)
            classes = list(getattr(pipeline, "classes_", [0, 1]))
            pos_idx = classes.index(1) if 1 in classes else 1
            prob = float(probabilities[0, pos_idx])
        except Exception as exc:
            raise RuntimeError(f"Prediction failed during model evaluation: {exc}") from exc

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 3)
        prediction = 1 if prob >= threshold else 0
        predicted_class = "delayed" if prediction == 1 else "not_delayed"

        return {
            "prediction": prediction,
            "predicted_class": predicted_class,
            "delay_probability": round(prob, 4),
            "threshold": round(threshold, 6),
            "model_id": MODEL_SPECS.get(model_name, {}).get("model_id", f"phase4.2-{model_name}"),
            "model_version": manifest.get("created_at_utc", "v1.0"),
            "latency_ms": latency_ms,
        }

    def compute_feature_contributions(
        self,
        features: dict[str, Any],
        model_name: str = "best",
    ) -> list[dict[str, Any]]:
        """Compute top signed linear contributions or importances for a single prediction."""
        try:
            pipeline, _, _ = self.load_model(model_name)
            preprocessor = pipeline.named_steps.get("preprocessor")
            classifier = pipeline.named_steps.get("classifier")

            if classifier is None or not hasattr(classifier, "coef_"):
                return []

            frame = to_feature_dataframe([features])
            transformed = preprocessor.transform(frame)
            row_dense = transformed.toarray()[0] if hasattr(transformed, "toarray") else transformed[0]
            feature_names = preprocessor.get_feature_names_out()

            classes = list(getattr(pipeline, "classes_", [0, 1]))
            pos_idx = classes.index(1) if 1 in classes else 1
            coefs = classifier.coef_[0] if pos_idx == 1 else -classifier.coef_[0]

            contributions = []
            for name, val, coef in zip(feature_names, row_dense, coefs):
                product = float(val * coef)
                if abs(product) > 1e-6:
                    contributions.append({
                        "feature": str(name),
                        "contribution_logit": round(product, 4),
                        "direction": "increases_delay_prob" if product > 0 else "reduces_delay_prob",
                    })

            contributions.sort(key=lambda item: abs(item["contribution_logit"]), reverse=True)
            return contributions[:5]
        except Exception as exc:
            logger.debug("Feature contribution computation skipped: %s", exc)
            return []


@lru_cache(maxsize=1)
def get_model_service() -> MLModelService:
    """Return the cached singleton instance of MLModelService."""
    return MLModelService()
