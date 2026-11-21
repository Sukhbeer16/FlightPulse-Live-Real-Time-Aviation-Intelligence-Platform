"""Honest prediction, anomaly, risk, and alert response contracts."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from backend.app.schemas.intelligence import (
    DelayPredictionRequest,
    DelayPredictionResponse,
    UnavailableIntelligenceResponse,
    AnomalyDetectionRequest,
    AnomalyDetectionResponse,
    RiskScoringRequest,
    RiskScoringResponse,
    AlertCreateRequest,
    AlertRead,
    AlertListResponse,
)
from backend.app.schemas.models import ModelCatalogResponse
from backend.app.services.delay_prediction import (
    LIMITATIONS,
    PredictionUnavailable,
    predict_delay,
)
from backend.app.services.model_catalog import get_model_catalog
from backend.app.services.anomaly_detection import (
    AnomalyUnavailable,
    detect_anomaly,
)
from backend.app.services.risk_intelligence import score_risk
from backend.app.services.alerts import create_demonstration_alert, list_alerts
from backend.app.schemas.flight import PaginationMetadata


router = APIRouter(tags=["flight intelligence"])


@router.get(
    "/models",
    response_model=ModelCatalogResponse,
    summary="List saved model artifacts",
    description=(
        "Report saved delay-model availability and evaluation provenance. "
        "Only the selected logistic-regression model currently has a prediction "
        "endpoint; no Isolation Forest artifact is available."
    ),
)
def model_catalog() -> ModelCatalogResponse:
    return ModelCatalogResponse(models=get_model_catalog())


@router.post(
    "/intelligence/delay-predictions",
    response_model=DelayPredictionResponse,
    summary="Estimate BTS arrival-delay probability",
    description=(
        "Run the saved Phase 4.2 logistic model using pre-departure features. "
        "This experimental January-February 2024 BTS model is not an operational "
        "delay label or a live-state estimate."
    ),
)
def delay_prediction(request: DelayPredictionRequest) -> DelayPredictionResponse:
    try:
        result = predict_delay(request)
    except PredictionUnavailable as error:
        return DelayPredictionResponse(
            status="unavailable",
            reason=str(error),
            limitations=LIMITATIONS,
        )
    return DelayPredictionResponse(**result)


@router.post(
    "/intelligence/delay-predictions/{model_name}",
    response_model=DelayPredictionResponse,
    summary="Run one saved delay model",
)
def named_delay_prediction(
    model_name: Literal[
        "logistic-regression",
        "random-forest",
        "decision-tree",
        "xgboost",
    ],
    request: DelayPredictionRequest,
) -> DelayPredictionResponse:
    try:
        result = predict_delay(request, model_name)
    except PredictionUnavailable as error:
        return DelayPredictionResponse(status="unavailable", reason=str(error))
    return DelayPredictionResponse(**result)


@router.post(
    "/predictions/delay",
    response_model=DelayPredictionResponse,
    summary="Run a selected saved delay model",
)
def selected_delay_prediction(
    request: DelayPredictionRequest,
    model: Literal[
        "logistic-regression",
        "random-forest",
        "decision-tree",
        "xgboost",
    ] = "logistic-regression",
) -> DelayPredictionResponse:
    try:
        result = predict_delay(request, model)
    except PredictionUnavailable as error:
        return DelayPredictionResponse(status="unavailable", reason=str(error))
    return DelayPredictionResponse(**result)


@router.post(
    "/intelligence/anomalies",
    response_model=AnomalyDetectionResponse,
    summary="Score a flight context with the saved Isolation Forest",
)
def anomaly_detection(request: AnomalyDetectionRequest) -> AnomalyDetectionResponse:
    try:
        return AnomalyDetectionResponse(**detect_anomaly(request))
    except AnomalyUnavailable as error:
        return AnomalyDetectionResponse(
            status="unavailable",
            reason=str(error),
            limitations=[
                "Statistical anomaly inference is unavailable until a compatible artifact exists.",
            ],
        )


@router.post(
    "/anomalies",
    response_model=AnomalyDetectionResponse,
    include_in_schema=True,
)
def anomalies_alias(request: AnomalyDetectionRequest) -> AnomalyDetectionResponse:
    return anomaly_detection(request)


@router.get(
    "/intelligence/anomalies",
    response_model=UnavailableIntelligenceResponse,
    summary="Check anomaly endpoint contract",
)
def anomaly_status() -> UnavailableIntelligenceResponse:
    return UnavailableIntelligenceResponse(
        reason="Use POST with the approved 21-feature request to run anomaly detection."
    )


@router.post(
    "/intelligence/risk",
    response_model=RiskScoringResponse,
    summary="Calculate a transparent operational risk assessment",
)
def risk_assessment(request: RiskScoringRequest) -> RiskScoringResponse:
    return RiskScoringResponse(**score_risk(request))


@router.post(
    "/risk",
    response_model=RiskScoringResponse,
)
def risk_alias(request: RiskScoringRequest) -> RiskScoringResponse:
    return risk_assessment(request)


@router.post(
    "/alerts/evaluate",
    response_model=AlertRead,
    summary="Create an explicitly labeled demonstration risk alert",
)
def evaluate_alert(request: AlertCreateRequest) -> AlertRead:
    return create_demonstration_alert(request.risk, request.flight_reference)


@router.get(
    "/alerts",
    response_model=AlertListResponse,
    summary="List in-process demonstration alerts",
)
def alerts(
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    severity: Literal["info", "warning", "high"] | None = None,
    status: Literal["open"] | None = None,
) -> AlertListResponse:
    rows, total = list_alerts(
        page=page,
        page_size=page_size,
        severity=severity,
        status=status,
    )
    total_pages = (total + page_size - 1) // page_size
    return AlertListResponse(
        data=rows,
        pagination=PaginationMetadata(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1 and total > 0,
        ),
    )
