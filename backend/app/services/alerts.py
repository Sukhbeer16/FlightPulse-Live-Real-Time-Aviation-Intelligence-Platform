"""In-memory demonstration alerts generated from validated risk assessments."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from backend.app.schemas.intelligence import AlertRead, RiskScoringRequest
from backend.app.services.risk_intelligence import score_risk


_alerts: list[AlertRead] = []
_lock = Lock()


def clear_alerts() -> None:
    with _lock:
        _alerts.clear()


def create_demonstration_alert(
    risk_request: RiskScoringRequest,
    flight_reference: str | None = None,
) -> AlertRead:
    risk = score_risk(risk_request)
    category = risk["risk_category"]
    if category == "elevated":
        severity = "high"
    elif category in {"high", "medium"}:
        severity = "warning"
    else:
        severity = "info"
    observed = risk["observed_arrival_delay_minutes"]
    confidence = (
        "observed_and_model"
        if observed is not None and risk["predicted_delay_score"] is not None
        else "observed_only"
        if observed is not None
        else "model_output"
    )
    alert = AlertRead(
        id=str(uuid4()),
        alert_type="risk_assessment",
        severity=severity,
        flight_reference=flight_reference or risk_request.flight_reference,
        timestamp=datetime.now(UTC).isoformat(),
        explanation=(
            "Demonstration risk assessment only. "
            f"Risk category is {category}; this is not a confirmed disruption."
        ),
        factors=risk["factors"],
        source="demonstration",
        confidence_status=confidence,
        status="open",
    )
    with _lock:
        _alerts.insert(0, alert)
    return alert


def list_alerts(
    *,
    page: int,
    page_size: int,
    severity: str | None = None,
    status: str | None = None,
) -> tuple[list[AlertRead], int]:
    with _lock:
        rows = list(_alerts)
    if severity is not None:
        rows = [row for row in rows if row.severity == severity]
    if status is not None:
        rows = [row for row in rows if row.status == status]
    total = len(rows)
    start = (page - 1) * page_size
    return rows[start : start + page_size], total
