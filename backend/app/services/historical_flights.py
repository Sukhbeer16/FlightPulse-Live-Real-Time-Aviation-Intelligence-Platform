"""Database-side search for imported historical BTS flight records."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

from backend.app.database.models.historical import HistoricalBTSFlight
from backend.app.schemas.historical import HistoricalFlightRead


def _filters(
    *,
    airline_code: str | None,
    origin: str | None,
    destination: str | None,
    date_from: date | None,
    date_to: date | None,
    cancelled: bool | None,
    diverted: bool | None,
    delayed: bool | None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if airline_code is not None:
        filters.append(
            HistoricalBTSFlight.reporting_airline_code
            == airline_code.strip().upper()
        )
    if origin is not None:
        filters.append(HistoricalBTSFlight.origin_bts_code == origin.strip().upper())
    if destination is not None:
        filters.append(
            HistoricalBTSFlight.destination_bts_code == destination.strip().upper()
        )
    if date_from is not None:
        filters.append(HistoricalBTSFlight.flight_date >= date_from)
    if date_to is not None:
        filters.append(HistoricalBTSFlight.flight_date <= date_to)
    if cancelled is not None:
        filters.append(HistoricalBTSFlight.cancelled == int(cancelled))
    if diverted is not None:
        filters.append(HistoricalBTSFlight.diverted == int(diverted))
    if delayed is True:
        filters.append(HistoricalBTSFlight.arrival_delay_minutes > 15)
    elif delayed is False:
        filters.append(
            HistoricalBTSFlight.arrival_delay_minutes.is_not(None)
            & (HistoricalBTSFlight.arrival_delay_minutes <= 15)
        )
    return filters


def search_historical_flights(
    *,
    session: Session,
    page: int,
    page_size: int,
    airline_code: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    cancelled: bool | None = None,
    diverted: bool | None = None,
    delayed: bool | None = None,
) -> tuple[list[HistoricalFlightRead], int]:
    """Filter and paginate in PostgreSQL; do not reinterpret BTS local time."""
    predicates = _filters(
        airline_code=airline_code,
        origin=origin,
        destination=destination,
        date_from=date_from,
        date_to=date_to,
        cancelled=cancelled,
        diverted=diverted,
        delayed=delayed,
    )
    total = session.scalar(
        select(func.count(HistoricalBTSFlight.id)).where(*predicates)
    ) or 0
    statement = (
        select(HistoricalBTSFlight)
        .options(joinedload(HistoricalBTSFlight.release))
        .where(*predicates)
        .order_by(
            HistoricalBTSFlight.flight_date.desc(),
            HistoricalBTSFlight.id.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = session.scalars(statement).all()
    return [HistoricalFlightRead.model_validate(row) for row in rows], total


def get_historical_flight(
    session: Session, flight_id: UUID
) -> HistoricalFlightRead | None:
    """Fetch one historical row and its release provenance without lazy loads."""
    statement = (
        select(HistoricalBTSFlight)
        .options(joinedload(HistoricalBTSFlight.release))
        .where(HistoricalBTSFlight.id == flight_id)
    )
    row = session.scalar(statement)
    return HistoricalFlightRead.model_validate(row) if row is not None else None
