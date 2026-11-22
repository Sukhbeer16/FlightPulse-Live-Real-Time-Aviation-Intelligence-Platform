"""Persistent evidence-backed alerts, with explicitly separated legacy demonstrations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4, uuid5, NAMESPACE_URL
import sqlite3
from contextlib import contextmanager
from backend.app.config.settings import get_settings

from backend.app.schemas.intelligence import AlertRead, RiskScoringRequest
from backend.app.services.risk_intelligence import score_risk


@contextmanager
def alert_database():
    path = get_settings().data_directory / "operations" / "alerts.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, severity TEXT NOT NULL,
            status TEXT NOT NULL, payload TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS alerts_time ON alerts(timestamp DESC)")
        with db:
            yield db
    finally:
        db.close()


def save_alert(alert: AlertRead) -> AlertRead:
    settings = get_settings()
    if settings.smtp_host and settings.alert_email_to and settings.smtp_from and alert.source != "demonstration":
        alert.delivery_status = "pending"
    with alert_database() as db:
        db.execute("INSERT OR IGNORE INTO alerts VALUES(?,?,?,?,?)",
                   (alert.id, alert.timestamp, alert.severity, alert.status, alert.model_dump_json()))
        return AlertRead.model_validate_json(db.execute("SELECT payload FROM alerts WHERE id=?", (alert.id,)).fetchone()[0])


def clear_alerts() -> None:
    with alert_database() as db:
        db.execute("DELETE FROM alerts")


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
    return save_alert(alert)


def list_alerts(
    *,
    page: int,
    page_size: int,
    severity: str | None = None,
    status: str | None = None,
) -> tuple[list[AlertRead], int]:
    filters, params = [], []
    for name, value in (("severity", severity), ("status", status)):
        if value is not None:
            filters.append(name + "=?")
            params.append(value)
    clause = " WHERE " + " AND ".join(filters) if filters else ""
    with alert_database() as db:
        total = db.execute("SELECT count(*) FROM alerts" + clause, params).fetchone()[0]
        rows = db.execute("SELECT payload FROM alerts" + clause + " ORDER BY timestamp DESC, id LIMIT ? OFFSET ?",
                          [*params, page_size, (page - 1) * page_size]).fetchall()
    return [AlertRead.model_validate_json(row[0]) for row in rows], total


def update_alert(alert_id, status):
    with alert_database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if row is None:
            return None
        alert = AlertRead.model_validate_json(row[0])
        if alert.status == "resolved" and status != "resolved":
            raise ValueError("Resolved alerts cannot be acknowledged again.")
        alert.status = status
        db.execute("UPDATE alerts SET status=?, payload=? WHERE id=?", (status, alert.model_dump_json(), alert_id))
        return alert


def create_historical_alert(source_file, source_row_number):
    from backend.app.services.processed_historical import search_processed_flights
    rows, _ = search_processed_flights(page=1, page_size=1, source_file=source_file, source_row_number=source_row_number)
    if not rows:
        raise LookupError("Historical source record not found.")
    row = rows[0]
    delay = row.arrival_delay_minutes
    if not row.cancelled and not row.diverted and (delay is None or delay <= 15):
        raise ValueError("This record has no reported delay over 15 minutes, cancellation or diversion.")
    reasons = "; ".join(f"{r['label']}: {r['minutes']:g} min" for r in row.delay_reasons)
    outcome = "Cancelled" if row.cancelled else "Diverted" if row.diverted else f"Arrived {delay:g} minutes late"
    return save_alert(AlertRead(
        id=str(uuid5(NAMESPACE_URL, f"bts:{source_file}:{source_row_number}")),
        alert_type="historical_delay", severity="high" if row.cancelled or row.diverted or (delay or 0) >= 60 else "warning",
        flight_reference=f"{row.reporting_airline}{row.flight_number}",
        timestamp=datetime.now(UTC).isoformat(), evidence_time=str(row.flight_date),
        title=f"{row.reporting_airline}{row.flight_number} · {outcome}",
        explanation=f"Historical BTS record for {row.flight_date}. {outcome}. " + (reasons or "The source does not report a specific delay cause.") + f" Source: {source_file}, row {source_row_number}.",
        factors=[], source="historical_bts", confidence_status="observed_only", status="open",
        origin=row.origin_bts_code, destination=row.destination_bts_code, airline=row.airline_name or row.reporting_airline,
    ))


def create_observation_alert(event):
    """Review flags from real, fresh telemetry. Never infer a delay from ADS-B."""
    import time
    state = event.state
    if event.source not in {"opensky", "adsb_lol"} or time.time() - state.last_contact > 300:
        return None
    rate = state.vertical_rate_mps
    if rate is None or abs(rate) <= 30 or state.on_ground:
        return None
    return save_alert(AlertRead(
        id=str(uuid5(NAMESPACE_URL, f"{event.source}:vertical-rate:{state.icao24}:{state.last_contact // 300}")),
        alert_type="telemetry_review", severity="warning", flight_reference=state.callsign or state.icao24,
        timestamp=datetime.now(UTC).isoformat(), evidence_time=datetime.fromtimestamp(state.last_contact, UTC).isoformat(),
        title=f"{state.callsign or state.icao24} · Vertical rate review",
        explanation=f"{event.source} reported a vertical rate of {rate:g} m/s, exceeding the ±30 m/s review threshold. Verify telemetry; this does not establish an emergency or flight delay.",
        factors=[], source=event.source, confidence_status="observed_only", status="open",
    ))
