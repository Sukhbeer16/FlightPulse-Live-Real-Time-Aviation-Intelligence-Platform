"""Transparent, non-emergency operational risk assessments."""

from __future__ import annotations

from backend.app.schemas.intelligence import (
    RiskFactor,
    RiskScoringRequest,
)
from backend.app.services.anomaly_detection import (
    AnomalyUnavailable,
    detect_anomaly,
)
from backend.app.services.delay_prediction import (
    PredictionUnavailable,
    predict_delay,
)


LOW_THRESHOLD = 40.0
MEDIUM_THRESHOLD = 70.0
HIGH_THRESHOLD = 85.0

LIMITATIONS = [
    "Risk score combines one experimental historical delay model and optional observed/anomaly signals.",
    "It does not confirm a disruption, cancellation, diversion, emergency, or aviation incident.",
    "Missing model or anomaly evidence reduces the corresponding contribution.",
]


def score_risk(request: RiskScoringRequest) -> dict[str, object]:
    factors: list[RiskFactor] = []
    model_score: float | None = None
    predicted_status: str | None = None
    model_points = 0.0
    try:
        prediction = predict_delay(request)
        model_score = prediction.get("model_score")
        predicted_status = prediction.get("predicted_class")
        if model_score is not None:
            model_points = max(0.0, min(1.0, float(model_score))) * 60.0
            factors.append(
                RiskFactor(
                    source="model",
                    factor="Logistic regression arrival-delay score",
                    contribution=round(model_points, 2),
                    evidence_status="available",
                )
            )
    except PredictionUnavailable:
        factors.append(
            RiskFactor(
                source="missing",
                factor="Delay-model prediction unavailable",
                contribution=0.0,
                evidence_status="unavailable",
            )
        )

    observed_points = 0.0
    if request.observed_arrival_delay_minutes is not None:
        delay = request.observed_arrival_delay_minutes
        if delay >= 60:
            observed_points = 25.0
        elif delay >= 30:
            observed_points = 18.0
        elif delay >= 16:
            observed_points = 12.0
        elif delay >= 0:
            observed_points = 5.0
        else:
            observed_points = 0.0
        factors.append(
            RiskFactor(
                source="observed",
                factor="Observed arrival delay above schedule",
                contribution=observed_points,
                evidence_status="observed",
            )
        )
    else:
        factors.append(
            RiskFactor(
                source="missing",
                factor="Observed arrival delay missing",
                contribution=0.0,
                evidence_status="missing",
            )
        )

    anomaly_score: float | None = None
    anomaly_points = 0.0
    if request.include_anomaly:
        try:
            anomaly = detect_anomaly(request)
            anomaly_score = anomaly.get("anomaly_score")
            if anomaly_score is not None:
                anomaly_points = max(0.0, min(100.0, float(anomaly_score))) * 0.15
                factors.append(
                    RiskFactor(
                        source="anomaly",
                        factor="Isolation Forest statistical outlier score",
                        contribution=round(anomaly_points, 2),
                        evidence_status="available",
                    )
                )
        except AnomalyUnavailable:
            factors.append(
                RiskFactor(
                    source="missing",
                    factor="Anomaly score unavailable",
                    contribution=0.0,
                    evidence_status="unavailable",
                )
            )

    risk_score = round(min(100.0, model_points + observed_points + anomaly_points), 2)
    if risk_score < LOW_THRESHOLD:
        category = "low"
    elif risk_score < MEDIUM_THRESHOLD:
        category = "medium"
    elif risk_score < HIGH_THRESHOLD:
        category = "high"
    else:
        category = "elevated"

    return {
        "status": "available",
        "flight_reference": request.flight_reference,
        "risk_score": risk_score,
        "risk_category": category,
        "predicted_delay_status": predicted_status,
        "predicted_delay_score": model_score,
        "observed_arrival_delay_minutes": request.observed_arrival_delay_minutes,
        "anomaly_score": anomaly_score,
        "factors": factors,
        "explanation": (
            "Score = 60 percent of the model delay score, plus documented observed "
            "arrival-delay points, plus 15 percent of the normalized anomaly score."
        ),
        "limitations": LIMITATIONS,
        "reason": None,
    }
