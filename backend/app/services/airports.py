"""Database queries for the airport catalog."""

from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.app.database.models.airport import Airport
from backend.app.schemas.catalog import AirportRead
from backend.app.schemas.flight import GeoPoint


def _escape_like(value: str) -> str:
    """Escape SQL LIKE metacharacters so search is literal substring matching."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(
    *, search: str | None, country_code: str | None
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if search is not None and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        filters.append(
            or_(
                Airport.name.ilike(pattern, escape="\\"),
                Airport.iata_code.ilike(pattern, escape="\\"),
                Airport.icao_code.ilike(pattern, escape="\\"),
            )
        )
    if country_code is not None:
        filters.append(Airport.country_code == country_code.strip().upper())
    return filters


def _airport_select():
    """Select airport rows and extract their PostGIS point coordinates."""
    geometry = cast(
        Airport.location,
        Geometry(geometry_type="POINT", srid=4326),
    )
    return select(
        Airport,
        func.ST_X(geometry).label("longitude"),
        func.ST_Y(geometry).label("latitude"),
    )


def _airport_read(row: Any) -> AirportRead:
    airport, longitude, latitude = row
    location = (
        GeoPoint(coordinates=(longitude, latitude))
        if longitude is not None and latitude is not None
        else None
    )
    return AirportRead(
        id=airport.id,
        iata_code=airport.iata_code,
        icao_code=airport.icao_code,
        name=airport.name,
        city=airport.city,
        country_code=airport.country_code,
        location=location,
        created_at=airport.created_at,
    )


def search_airports(
    *,
    session: Session,
    page: int,
    page_size: int,
    search: str | None,
    country_code: str | None,
) -> tuple[list[AirportRead], int]:
    """Apply database-side search, country filter, count and pagination."""
    filters = _filters(search=search, country_code=country_code)
    total = session.scalar(select(func.count(Airport.id)).where(*filters)) or 0
    statement = (
        _airport_select()
        .where(*filters)
        .order_by(Airport.name.asc(), Airport.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = session.execute(statement).all()
    return [_airport_read(row) for row in rows], total


def get_airport(session: Session, iata_code: str) -> AirportRead | None:
    """Look up an airport by IATA code, case-insensitively."""
    statement = _airport_select().where(Airport.iata_code == iata_code.strip().upper())
    row = session.execute(statement).first()
    return _airport_read(row) if row is not None else None
