"""Database queries for the airline catalog."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.app.database.models.airline import Airline
from backend.app.schemas.catalog import AirlineRead


def _escape_like(value: str) -> str:
    """Escape SQL LIKE metacharacters so search is literal substring matching."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_predicate(search: str | None) -> ColumnElement[bool] | None:
    if search is None or not search.strip():
        return None
    pattern = f"%{_escape_like(search.strip())}%"
    return or_(
        Airline.code.ilike(pattern, escape="\\"),
        Airline.name.ilike(pattern, escape="\\"),
    )


def search_airlines(
    *, session: Session, page: int, page_size: int, search: str | None
) -> tuple[list[AirlineRead], int]:
    """Apply database-side search, count, ordering and pagination."""
    predicate = _search_predicate(search)
    filters = [predicate] if predicate is not None else []
    total = session.scalar(select(func.count(Airline.code)).where(*filters)) or 0
    statement = (
        select(Airline)
        .where(*filters)
        .order_by(Airline.code.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    airlines = session.scalars(statement).all()
    return [AirlineRead.model_validate(airline) for airline in airlines], total


def get_airline(session: Session, airline_code: str) -> AirlineRead | None:
    """Look up a carrier code case-insensitively."""
    airline = session.scalar(
        select(Airline).where(Airline.code == airline_code.strip().upper())
    )
    return AirlineRead.model_validate(airline) if airline is not None else None
