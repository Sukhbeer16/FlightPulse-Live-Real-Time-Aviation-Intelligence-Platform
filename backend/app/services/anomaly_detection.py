"""Loading and inference for the saved Isolation Forest artifact."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from backend.app.config.settings import get_settings
from backend.app.schemas.intelligence import AnomalyDetectionRequest
from backend.app.services.delay_prediction import FEATURES, _feature_row


MODEL_DIRECTORY = Path("processed") / "ml" / "phase4_2"
MODEL_ID = "phase4.2-isolation-forest"
LIMITATIONS = [
    "A statistical outlier score from unsupervised January-February 2024 BTS features.",
    "Lower decision_function values are more anomalous; the score is not calibrated.",
    "An anomaly is not proof of an aviation emergency, live disruption, or equipment failure.",
]


class AnomalyUnavailable(RuntimeError):
    """The local anomaly artifact is absent or incompatible."""


@lru_cache(maxsize=1)
def _load_anomaly_model() -> tuple[Any, dict[str, Any]]:
    directory = get_settings().data_directory / MODEL_DIRECTORY
    artifact = directory / "isolation_forest.joblib"
    manifest_path = directory / "isolation_forest_manifest.json"
    if not artifact.is_file() or not manifest_path.is_file():
        raise AnomalyUnavailable("The saved Isolation Forest artifact is not available.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("features", {}).get("allowlist") != FEATURES:
            raise AnomalyUnavailable("The Isolation Forest feature contract is incompatible.")
        model = joblib.load(artifact)
        if not callable(getattr(model, "decision_function", None)):
            raise AnomalyUnavailable("The saved Isolation Forest lacks decision_function.")
    except AnomalyUnavailable:
        raise
    except Exception as error:
        raise AnomalyUnavailable("The saved Isolation Forest could not be loaded.") from error
    return model, manifest


def detect_anomaly(request: AnomalyDetectionRequest) -> dict[str, Any]:
    model, manifest = _load_anomaly_model()
    try:
        directory = get_settings().data_directory / MODEL_DIRECTORY
        base_path = directory / "isolation_forest_base_manifest.json"
        if not base_path.is_file():
            base_path = directory / "experiment_manifest.json"
        base_manifest = json.loads(base_path.read_text(encoding="utf-8"))
        row = _feature_row(request, base_manifest)
        frame = pd.DataFrame([row], columns=FEATURES)
        raw_score = float(model.decision_function(frame)[0])
        if not math.isfinite(raw_score):
            raise AnomalyUnavailable("The anomaly model produced an invalid score.")
        percentile = manifest["decision_function"]
        low = float(percentile["p1"])
        high = float(percentile["p99"])
        if high <= low:
            raise AnomalyUnavailable("The anomaly score scale is invalid.")
        anomaly_score = (high - raw_score) / (high - low)
        anomaly_score = round(max(0.0, min(100.0, anomaly_score * 100.0)), 2)
    except AnomalyUnavailable:
        raise
    except Exception as error:
        raise AnomalyUnavailable("The anomaly model could not score this request.") from error
    return {
        "status": "available",
        "model_id": MODEL_ID,
        "decision_function": raw_score,
        "anomaly_score": anomaly_score,
        "score_interpretation": (
            "Relative outlier score within the saved training scale; "
            "higher means more statistically unusual."
        ),
        "is_statistical_outlier": raw_score < 0,
        "limitations": LIMITATIONS,
        "reason": None,
    }
