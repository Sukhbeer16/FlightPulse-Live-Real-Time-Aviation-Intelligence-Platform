"""Flight discovery HTTP endpoints."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.schemas.flight import FlightDetailResponse, FlightListResponse
from backend.app.services.flights import get_flight, search_flights


router = APIRouter(prefix="/flights", tags=["flights"])


@router.get(
    "",
    response_model=FlightListResponse,
    summary="Search flights",
    description=(
        "Search source-backed flight records, which may be historical. The "
        "status value is source-provided and does not imply real-time tracking. "
        "Flight numbers and airport codes use exact matching; flight_date is "
        "the scheduled departure date in UTC. Results are ordered by scheduled "
        "departure time."
    ),
)
def list_flights(
    page: Annotated[int, Query(ge=1, le=1_000_000, description="1-based page number.")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Results per page (maximum 100).")
    ] = 20,
    flight_number: Annotated[
        str | None,
        Query(min_length=1, max_length=20, description="Exact flight number."),
    ] = None,
    airline_code: Annotated[
        str | None,
        Query(min_length=1, max_length=3, description="Airline carrier code."),
    ] = None,
    origin: Annotated[
        str | None,
        Query(min_length=3, max_length=4, description="Origin IATA or ICAO code."),
    ] = None,
    destination: Annotated[
        str | None,
        Query(
            min_length=3,
            max_length=4,
            description="Destination IATA or ICAO code.",
        ),
    ] = None,
    flight_date: Annotated[
        date | None,
        Query(description="Scheduled departure date in UTC (YYYY-MM-DD)."),
    ] = None,
    sort_order: Annotated[
        Literal["asc", "desc"],
        Query(description="Scheduled departure sort direction."),
    ] = "asc",
    session: Session = Depends(get_db),
) -> FlightListResponse:
    """Return a page of flights matching all supplied filters."""
    flights, total = search_flights(
        session=session,
        page=page,
        page_size=page_size,
        flight_number=flight_number,
        airline_code=airline_code,
        origin=origin,
        destination=destination,
        flight_date=flight_date,
        sort_order=sort_order,
    )
    total_pages = (total + page_size - 1) // page_size
    return FlightListResponse(
        data=flights,
        pagination={
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1 and total > 0,
        },
    )


@router.get(
    "/search",
    response_model=FlightListResponse,
    summary="Search operational flights",
)
def search_flights_alias(
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    flight_number: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    airline_code: Annotated[str | None, Query(min_length=1, max_length=3)] = None,
    origin: Annotated[str | None, Query(min_length=3, max_length=4)] = None,
    destination: Annotated[str | None, Query(min_length=3, max_length=4)] = None,
    flight_date: Annotated[date | None, Query()] = None,
    session: Session = Depends(get_db),
) -> FlightListResponse:
    from backend.app.services.flights import search_flights

    flights, total = search_flights(
        session=session,
        page=page,
        page_size=page_size,
        flight_number=flight_number,
        airline_code=airline_code,
        origin=origin,
        destination=destination,
        flight_date=flight_date,
        sort_order="asc",
    )
    total_pages = (total + page_size - 1) // page_size
    return FlightListResponse(
        data=flights,
        pagination={
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1 and total > 0,
        },
    )


@router.get(
    "/{flight_id}",
    response_model=FlightDetailResponse,
    summary="Get a flight",
    description=(
        "Return a source-backed flight and its available airline and airport "
        "details. A source-provided status is not a real-time guarantee."
    ),
)
def flight_detail(
    flight_id: Annotated[UUID, Path(description="Flight UUID.")],
    session: Session = Depends(get_db),
) -> FlightDetailResponse:
    """Return a flight by UUID or a 404 response when it is absent."""
    flight = get_flight(session, flight_id)
    if flight is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Flight not found.",
        )
    return FlightDetailResponse(data=flight)
