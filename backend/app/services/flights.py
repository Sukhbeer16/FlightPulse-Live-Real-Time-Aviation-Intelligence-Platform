"""Database queries and response mapping for flight discovery."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload
from sqlalchemy.sql.elements import ColumnElement

from backend.app.database.models.airport import Airport
from backend.app.database.models.flight import Flight
from backend.app.schemas.flight import (
    AirlineSummary,
    AirportSummary,
    FlightRead,
    GeoPoint,
)


def _filters(
    *,
    flight_number: str | None,
    airline_code: str | None,
    origin: str | None,
    destination: str | None,
    flight_date: date | None,
) -> list[ColumnElement[bool]]:
    """Build SQL-side predicates shared by the count and row queries."""
    predicates: list[ColumnElement[bool]] = []
    if flight_number is not None:
        normalized_number = flight_number.strip().upper()
        if normalized_number:
            predicates.append(Flight.flight_number == normalized_number)
    if airline_code is not None:
        normalized_airline = airline_code.strip().upper()
        if normalized_airline:
            predicates.append(Flight.airline_code == normalized_airline)
    if origin is not None:
        code = origin.strip().upper()
        predicates.append(
            Flight.origin_airport.has(
                or_(Airport.iata_code == code, Airport.icao_code == code)
            )
        )
    if destination is not None:
        code = destination.strip().upper()
        predicates.append(
            Flight.destination_airport.has(
                or_(Airport.iata_code == code, Airport.icao_code == code)
            )
        )
    if flight_date is not None:
        start = datetime.combine(flight_date, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        predicates.extend(
            (
                Flight.scheduled_departure_at >= start,
                Flight.scheduled_departure_at < end,
            )
        )
    return predicates


def _airport_schema(
    airport: Airport | None,
    longitude: float | None,
    latitude: float | None,
) -> AirportSummary | None:
    """Map an airport and optional PostGIS coordinates to its response schema."""
    if airport is None:
        return None
    location = (
        GeoPoint(coordinates=(longitude, latitude))
        if longitude is not None and latitude is not None
        else None
    )
    return AirportSummary(
        id=airport.id,
        iata_code=airport.iata_code,
        icao_code=airport.icao_code,
        name=airport.name,
        city=airport.city,
        country_code=airport.country_code,
        location=location,
    )


def _flight_select():
    """Build one joined query for flights and their scalar related records."""
    origin = aliased(Airport, name="origin_airport")
    destination = aliased(Airport, name="destination_airport")
    origin_geometry = cast(origin.location, Geometry(geometry_type="POINT", srid=4326))
    destination_geometry = cast(
        destination.location, Geometry(geometry_type="POINT", srid=4326)
    )
    statement = (
        select(
            Flight,
            origin,
            destination,
            func.ST_X(origin_geometry).label("origin_longitude"),
            func.ST_Y(origin_geometry).label("origin_latitude"),
            func.ST_X(destination_geometry).label("destination_longitude"),
            func.ST_Y(destination_geometry).label("destination_latitude"),
        )
        .outerjoin(origin, Flight.origin_airport_id == origin.id)
        .outerjoin(destination, Flight.destination_airport_id == destination.id)
        .options(joinedload(Flight.airline))
    )
    return statement


def _flight_schema(row: Any) -> FlightRead:
    """Convert a joined query row into the response schema without lazy loads."""
    (
        flight,
        origin,
        destination,
        origin_longitude,
        origin_latitude,
        destination_longitude,
        destination_latitude,
    ) = row
    return FlightRead(
        id=flight.id,
        source=flight.source,
        source_flight_id=flight.source_flight_id,
        flight_number=flight.flight_number,
        callsign=flight.callsign,
        airline_code=flight.airline_code,
        origin_airport_id=flight.origin_airport_id,
        destination_airport_id=flight.destination_airport_id,
        scheduled_departure_at=flight.scheduled_departure_at,
        scheduled_arrival_at=flight.scheduled_arrival_at,
        actual_departure_at=flight.actual_departure_at,
        actual_arrival_at=flight.actual_arrival_at,
        status=flight.status,
        updated_at=flight.updated_at,
        airline=(
            AirlineSummary.model_validate(flight.airline)
            if flight.airline is not None
            else None
        ),
        origin_airport=_airport_schema(origin, origin_longitude, origin_latitude),
        destination_airport=_airport_schema(
            destination, destination_longitude, destination_latitude
        ),
    )


def search_flights(
    *,
    session: Session,
    page: int,
    page_size: int,
    flight_number: str | None,
    airline_code: str | None,
    origin: str | None,
    destination: str | None,
    flight_date: date | None,
    sort_order: Literal["asc", "desc"],
) -> tuple[list[FlightRead], int]:
    """Filter and page database rows, returning schemas and the total count."""
    predicates = _filters(
        flight_number=flight_number,
        airline_code=airline_code,
        origin=origin,
        destination=destination,
        flight_date=flight_date,
    )
    total = session.scalar(
        select(func.count(Flight.id)).where(*predicates)
    ) or 0

    departure_order = (
        Flight.scheduled_departure_at.asc()
        if sort_order == "asc"
        else Flight.scheduled_departure_at.desc()
    )
    statement = (
        _flight_select()
        .where(*predicates)
        .order_by(departure_order, Flight.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = session.execute(statement).all()
    return [_flight_schema(row) for row in rows], total


def get_flight(session: Session, flight_id: UUID) -> FlightRead | None:
    """Fetch one flight with airline, airport and point details in joined SQL."""
    statement = _flight_select().where(Flight.id == flight_id)
    row = session.execute(statement).first()
    return _flight_schema(row) if row is not None else None
