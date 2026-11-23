"""Operational anomaly detection, distinctly separated from supervised delay prediction."""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from backend.app.config.settings import get_settings
from backend.app.feature_engineering.features import FEATURE_ALLOWLIST, to_feature_dataframe
from backend.app.schemas.live import LiveStateVector

logger = logging.getLogger(__name__)

PRIMARY_ANOMALY_DIR = Path("processed") / "ml" / "phase4_2"
MODEL_ID = "phase4.2-isolation-forest"

ANOMALY_LIMITATIONS = [
    "Statistical outlier scoring based on unsupervised January-February 2024 features.",
    "Lower decision_function values are more anomalous; the 0-100 score is relative to observed bounds.",
    "An anomaly is NOT a proof of delay, emergency, equipment failure, or safety violation.",
    "Delay prediction and anomaly detection are fundamentally separate machine learning tasks.",
]


class AnomalyModelUnavailable(RuntimeError):
    """Raised when the Isolation Forest artifact is missing or invalid."""


class AnomalyDetector:
    """Operational anomaly detection engine separating telemetry anomalies from delay models."""

    def __init__(self, data_directory: Path | None = None):
        self._data_dir = data_directory or get_settings().data_directory
        self._model: Any | None = None
        self._manifest: dict[str, Any] | None = None

    def _load_model(self) -> tuple[Any, dict[str, Any]]:
        if self._model is not None and self._manifest is not None:
            return self._model, self._manifest

        directory = self._data_dir / PRIMARY_ANOMALY_DIR
        artifact = directory / "isolation_forest.joblib"
        manifest_path = directory / "isolation_forest_manifest.json"

        if not artifact.is_file() or not manifest_path.is_file():
            # Check data/processed/ml/phase4_2
            alt_dir = Path("data") / PRIMARY_ANOMALY_DIR
            artifact = alt_dir / "isolation_forest.joblib"
            manifest_path = alt_dir / "isolation_forest_manifest.json"

        if not artifact.is_file() or not manifest_path.is_file():
            raise AnomalyModelUnavailable(f"Isolation Forest model artifact not found in {directory}")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            model = joblib.load(artifact)
            if not callable(getattr(model, "decision_function", None)):
                raise AnomalyModelUnavailable("Loaded anomaly model lacks decision_function method.")
            self._model = model
            self._manifest = manifest
            return model, manifest
        except Exception as exc:
            raise AnomalyModelUnavailable(f"Failed to load anomaly detection artifact: {exc}") from exc

    def score_features(self, feature_row: dict[str, Any]) -> dict[str, Any]:
        """Compute statistical outlier anomaly score on the 21-feature representation."""
        model, manifest = self._load_model()
        frame = to_feature_dataframe([feature_row])

        try:
            raw_score = float(model.decision_function(frame)[0])
            if not math.isfinite(raw_score):
                raise AnomalyModelUnavailable("Anomaly model computed a non-finite score.")

            bounds = manifest.get("decision_function", {"p1": -0.15, "p99": 0.15})
            low = float(bounds.get("p1", -0.15))
            high = float(bounds.get("p99", 0.15))

            if high <= low:
                normalized = 50.0
            else:
                ratio = (high - raw_score) / (high - low)
                normalized = round(max(0.0, min(100.0, ratio * 100.0)), 2)

            is_outlier = bool(raw_score < 0)

            return {
                "status": "available",
                "model_id": MODEL_ID,
                "task": "anomaly_detection",
                "decision_function": round(raw_score, 4),
                "anomaly_score": normalized,
                "is_statistical_outlier": is_outlier,
                "score_interpretation": (
                    "Relative statistical outlier score (0-100). Higher scores mean "
                    "less frequent operational configurations. Does not imply flight delay."
                ),
                "limitations": ANOMALY_LIMITATIONS,
            }
        except Exception as exc:
            raise AnomalyModelUnavailable(f"Anomaly scoring failed: {exc}") from exc

    def check_telemetry_anomaly(self, state: LiveStateVector) -> dict[str, Any]:
        """Check live ADS-B state vector for physical/operational telemetry outliers."""
        flags: list[str] = []
        severity: str = "normal"

        # 1. Extreme vertical rate check (climb/descent > 30 m/s ~ 6,000 fpm)
        if state.vertical_rate_mps is not None and abs(state.vertical_rate_mps) > 30.0:
            flags.append(f"Extreme vertical rate: {state.vertical_rate_mps:+.1f} m/s")
            severity = "warning"

        # 2. Inconsistent ground status vs altitude
        if state.on_ground and state.barometric_altitude_m and state.barometric_altitude_m > 600.0:
            flags.append(f"Reported on ground at high altitude: {state.barometric_altitude_m:.0f}m")
            severity = "warning"

        # 3. Excessive speed on ground (> 60 m/s ~ 116 knots)
        if state.on_ground and state.velocity_mps and state.velocity_mps > 60.0:
            flags.append(f"Excessive ground roll velocity: {state.velocity_mps:.1f} m/s")
            severity = "warning"

        # 4. Emergency squawk codes
        if state.squawk in {"7500", "7600", "7700"}:
            flags.append(f"Emergency transponder squawk: {state.squawk}")
            severity = "critical"

        return {
            "is_anomaly": len(flags) > 0,
            "severity": severity,
            "flags": flags,
            "icao24": state.icao24,
            "callsign": state.callsign,
            "last_contact": state.last_contact,
        }


@lru_cache(maxsize=1)
def get_anomaly_detector() -> AnomalyDetector:
    """Cached singleton instance of AnomalyDetector."""
    return AnomalyDetector()
