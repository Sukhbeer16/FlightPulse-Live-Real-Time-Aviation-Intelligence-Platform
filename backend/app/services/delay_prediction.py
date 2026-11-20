"""Lazy inference adapter for the saved Phase 4.2 BTS delay baseline."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.config.settings import get_settings
from backend.app.schemas.intelligence import DelayPredictionRequest


MODEL_DIRECTORY = Path("processed") / "ml" / "phase4_2"
MODEL_ID = "phase4.2-logistic-regression-balanced"
MODEL_SPECS = {
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
MODEL_CANDIDATES = {
    "logistic-regression": "logistic_regression_balanced",
    "random-forest": "random_forest",
    "decision-tree": "decision_tree",
    "xgboost": "xgboost",
}
FEATURES = [
    "Reporting_Airline",
    "Origin",
    "Dest",
    "month",
    "day_of_month",
    "day_of_week",
    "scheduled_departure_sin",
    "scheduled_departure_cos",
    "scheduled_arrival_sin",
    "scheduled_arrival_cos",
    "scheduled_elapsed_time_minutes",
    "distance_miles",
    "is_missing_month",
    "is_missing_day_of_month",
    "is_missing_day_of_week",
    "is_missing_scheduled_departure_sin",
    "is_missing_scheduled_departure_cos",
    "is_missing_scheduled_arrival_sin",
    "is_missing_scheduled_arrival_cos",
    "is_missing_scheduled_elapsed_time_minutes",
    "is_missing_distance_miles",
]
LIMITATIONS = [
    "Experimental estimate only; trained on BTS January-February 2024 data.",
    "Class-weighted model output is not calibrated; treat the score as relative, not as a literal probability.",
    "The held-out test recall was 0.0590 at threshold 0.5; this is not operationally validated.",
    "The model estimates arrival delay greater than 15 minutes and does not use live flight state.",
    "Feature contributions are additive logit associations from this linear model, not causal explanations.",
]


class PredictionUnavailable(RuntimeError):
    """The local inference artifact is absent or incompatible."""


@lru_cache(maxsize=4)
def _load_model(model_name: str = "logistic-regression") -> tuple[Any, dict[str, Any]]:
    if model_name not in MODEL_SPECS:
        raise PredictionUnavailable("The requested delay model is not supported.")
    model_directory = get_settings().data_directory / MODEL_DIRECTORY
    manifest_path = model_directory / "experiment_manifest.json"
    model_path = model_directory / MODEL_SPECS[model_name]["artifact"]
    if not manifest_path.is_file() or not model_path.is_file():
        raise PredictionUnavailable("The saved delay model is not available.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_version = manifest["software_versions"]["scikit_learn"]
        import sklearn

        if sklearn.__version__ != expected_version:
            raise PredictionUnavailable(
                "Installed scikit-learn does not match the model artifact version."
            )
        if manifest.get("features", {}).get("allowlist") != FEATURES:
            raise PredictionUnavailable("The saved model contract is incompatible.")
        import joblib

        model = joblib.load(model_path)
    except PredictionUnavailable:
        raise
    except Exception as error:
        raise PredictionUnavailable("The saved delay model could not be loaded.") from error
    if not callable(getattr(model, "predict_proba", None)):
        raise PredictionUnavailable("The saved delay model lacks probability output.")
    return model, manifest


def _minutes_since_midnight(value: int | None) -> float | None:
    if value is None:
        return None
    if value == 2400:
        return 0.0
    hour, minute = divmod(value, 100)
    if hour > 23 or minute > 59:
        raise ValueError("Scheduled times must be valid HHMM values or 2400.")
    return float(hour * 60 + minute)


def _cyclic(value: int | None) -> tuple[float | None, float | None]:
    minutes = _minutes_since_midnight(value)
    if minutes is None:
        return None, None
    angle = 2 * math.pi * minutes / 1_440
    return math.sin(angle), math.cos(angle)


def _feature_row(request: DelayPredictionRequest, manifest: dict[str, Any]) -> dict[str, Any]:
    departure_sin, departure_cos = _cyclic(request.scheduled_departure_hhmm)
    arrival_sin, arrival_cos = _cyclic(request.scheduled_arrival_hhmm)
    raw_numeric: dict[str, float | None] = {
        "month": float(request.flight_date.month),
        "day_of_month": float(request.flight_date.day),
        "day_of_week": float(request.flight_date.weekday()),
        "scheduled_departure_sin": departure_sin,
        "scheduled_departure_cos": departure_cos,
        "scheduled_arrival_sin": arrival_sin,
        "scheduled_arrival_cos": arrival_cos,
        "scheduled_elapsed_time_minutes": request.scheduled_elapsed_time_minutes,
        "distance_miles": request.distance_miles,
    }
    medians = manifest["preprocessing"]["upstream_imputation"]["medians"]
    row: dict[str, Any] = {
        "Reporting_Airline": request.reporting_airline.strip().upper(),
        "Origin": request.origin.strip().upper(),
        "Dest": request.destination.strip().upper(),
    }
    for name, value in raw_numeric.items():
        if value is not None and not math.isfinite(float(value)):
            value = None
        row[name] = float(medians[name]) if value is None else float(value)
        row[f"is_missing_{name}"] = int(value is None)
    if set(row) != set(FEATURES):
        raise PredictionUnavailable("The request could not satisfy the feature contract.")
    return row


def _top_feature_contributions(model: Any, frame: Any) -> list[dict[str, float | str]]:
    """Return the largest signed logistic-logit contributions for one request."""
    try:
        feature_pipeline = model[:-1]
        classifier = model.steps[-1][1]
        classes = list(model.classes_)
        positive_index = classes.index(1)
        coefficients = classifier.coef_[positive_index]
        names = feature_pipeline.get_feature_names_out()
        transformed = feature_pipeline.transform(frame)
        values = transformed.toarray()[0] if hasattr(transformed, "toarray") else transformed[0]
        contributions = [
            (str(name), float(value * coefficient))
            for name, value, coefficient in zip(names, values, coefficients)
            if abs(float(value * coefficient)) > 1e-12
        ]
    except Exception:
        return []
    contributions.sort(key=lambda item: abs(item[1]), reverse=True)
    return [
        {
            "feature": name,
            "contribution_logit": value,
            "direction": "increases_score" if value > 0 else "decreases_score",
        }
        for name, value in contributions[:5]
    ]


def predict_delay(
    request: DelayPredictionRequest,
    model_name: str = "logistic-regression",
) -> dict[str, Any]:
    """Return an explicitly experimental score from the saved BTS baseline."""
    model, manifest = _load_model(model_name)
    try:
        import pandas as pd

        frame = pd.DataFrame([_feature_row(request, manifest)], columns=FEATURES)
        probabilities = model.predict_proba(frame)[0]
        classes = list(model.classes_)
        positive_index = classes.index(1)
        probability = float(probabilities[positive_index])
        contributions = _top_feature_contributions(model, frame)
    except PredictionUnavailable:
        raise
    except Exception as error:
        raise PredictionUnavailable("The model could not score this request.") from error
    candidate = MODEL_CANDIDATES[model_name]
    validation_metrics = manifest.get("validation_metrics", {})
    candidate_metrics = validation_metrics.get(candidate, {})
    threshold = float(candidate_metrics.get("threshold", 0.5))
    return {
        "status": "available",
        "model_id": MODEL_SPECS[model_name]["model_id"],
        "target": "arrival delay greater than 15 minutes",
        "model_score": probability,
        "score_interpretation": "Uncalibrated relative model score on a 0-to-1 scale.",
        "threshold": threshold,
        "predicted_class": "delayed" if probability >= threshold else "not_delayed",
        "explanation": (
            f"The relative model score is compared with the validation-selected "
            f"threshold of {threshold:.2f}. Feature contributions are model "
            "associations, not causes."
        ),
        "feature_contributions": contributions,
        "limitations": LIMITATIONS,
        "reason": None,
    }
