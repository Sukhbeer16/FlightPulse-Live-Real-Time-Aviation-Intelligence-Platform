"""Request and response contracts for model-derived intelligence."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.app.schemas.flight import PaginationMetadata


class DelayPredictionRequest(BaseModel):
    """Pre-departure inputs matching the BTS 21-feature training contract."""

    model_config = ConfigDict(extra="forbid")

    reporting_airline: str = Field(min_length=1, max_length=8)
    origin: str = Field(min_length=3, max_length=3, pattern="^[A-Za-z0-9]{3}$")
    destination: str = Field(
        min_length=3, max_length=3, pattern="^[A-Za-z0-9]{3}$"
    )
    flight_date: date
    scheduled_departure_hhmm: int | None = Field(default=None, ge=0, le=2400)
    scheduled_arrival_hhmm: int | None = Field(default=None, ge=0, le=2400)
    scheduled_elapsed_time_minutes: float | None = Field(default=None, ge=0, le=2000)
    distance_miles: float | None = Field(default=None, ge=0, le=20_000)

    @field_validator("scheduled_departure_hhmm", "scheduled_arrival_hhmm")
    @classmethod
    def validate_hhmm(cls, value: int | None) -> int | None:
        if value is None or value == 2400:
            return value
        if value % 100 > 59 or value // 100 > 23:
            raise ValueError("Use a valid HHMM time or 2400.")
        return value


class DelayPredictionResponse(BaseModel):
    data_kind: Literal["model_prediction"] = "model_prediction"
    status: Literal["available", "unavailable"]
    model_id: str | None = None
    target: str | None = None
    model_score: float | None = None
    score_interpretation: str | None = None
    threshold: float | None = None
    predicted_class: Literal["delayed", "not_delayed"] | None = None
    explanation: str | None = None
    feature_contributions: list[dict[str, float | str]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reason: str | None = None


class UnavailableIntelligenceResponse(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    reason: str
    data: list[dict[str, object]] = Field(default_factory=list)


class AnomalyDetectionRequest(DelayPredictionRequest):
    """Request contract reusing the approved 21-feature flight context."""


class AnomalyDetectionResponse(BaseModel):
    data_kind: Literal["statistical_anomaly"] = "statistical_anomaly"
    status: Literal["available", "unavailable"]
    model_id: str | None = None
    decision_function: float | None = None
    anomaly_score: float | None = Field(default=None, ge=0, le=100)
    score_interpretation: str | None = None
    is_statistical_outlier: bool | None = None
    limitations: list[str] = Field(default_factory=list)
    reason: str | None = None


class RiskScoringRequest(DelayPredictionRequest):
    flight_reference: str | None = Field(default=None, max_length=80)
    observed_arrival_delay_minutes: float | None = Field(default=None, ge=-300, le=1440)
    include_anomaly: bool = True


class RiskFactor(BaseModel):
    source: Literal["model", "observed", "anomaly", "missing"]
    factor: str
    contribution: float
    evidence_status: Literal["available", "missing", "unavailable", "observed"]


class RiskScoringResponse(BaseModel):
    data_kind: Literal["operational_risk_assessment"] = "operational_risk_assessment"
    status: Literal["available", "unavailable"]
    flight_reference: str | None = None
    risk_score: float | None = Field(default=None, ge=0, le=100)
    risk_category: Literal["low", "medium", "high", "elevated"] | None = None
    predicted_delay_status: Literal["delayed", "not_delayed"] | None = None
    predicted_delay_score: float | None = None
    observed_arrival_delay_minutes: float | None = None
    anomaly_score: float | None = Field(default=None, ge=0, le=100)
    factors: list[RiskFactor] = Field(default_factory=list)
    explanation: str
    limitations: list[str] = Field(default_factory=list)
    reason: str | None = None


class AlertCreateRequest(BaseModel):
    risk: RiskScoringRequest
    flight_reference: str | None = Field(default=None, max_length=80)
    source: Literal["demonstration"] = "demonstration"


class AlertRead(BaseModel):
    id: str
    alert_type: Literal["risk_assessment", "statistical_anomaly"]
    severity: Literal["info", "warning", "high"]
    flight_reference: str | None
    timestamp: str
    explanation: str
    factors: list[RiskFactor]
    source: Literal["demonstration"]
    confidence_status: Literal["model_output", "observed_and_model", "observed_only"]
    status: Literal["open"]


class AlertListResponse(BaseModel):
    data_kind: Literal["demonstration_alerts"] = "demonstration_alerts"
    data: list[AlertRead]
    pagination: PaginationMetadata
