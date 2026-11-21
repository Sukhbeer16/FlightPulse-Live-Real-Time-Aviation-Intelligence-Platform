"""Historical BTS flight search routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.schemas.flight import PaginationMetadata
from backend.app.schemas.historical import (
    HistoricalFlightDetailResponse,
    HistoricalFlightListResponse,
)
from backend.app.services.historical_flights import (
    get_historical_flight,
    search_historical_flights,
)


router = APIRouter(prefix="/historical/flights", tags=["historical flights"])


@router.get(
    "",
    response_model=HistoricalFlightListResponse,
    summary="Search historical BTS flights",
    description=(
        "Search imported BTS historical records. Times remain source-local HHMM "
        "values; these rows are not live flight states."
    ),
)
def list_historical_flights(
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    airline_code: Annotated[str | None, Query(min_length=1, max_length=3)] = None,
    origin: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    destination: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    cancelled: bool | None = None,
    diverted: bool | None = None,
    delayed: bool | None = Query(
        default=None,
        description="Arrival delay greater than 15 minutes; unknown delay is excluded.",
    ),
    session: Session = Depends(get_db),
) -> HistoricalFlightListResponse:
    """Return a page of historical source records matching all filters."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be on or before date_to.",
        )
    flights, total = search_historical_flights(
        session=session,
        page=page,
        page_size=page_size,
        airline_code=airline_code,
        origin=origin,
        destination=destination,
        date_from=date_from,
        date_to=date_to,
        cancelled=cancelled,
        diverted=diverted,
        delayed=delayed,
    )
    total_pages = (total + page_size - 1) // page_size
    return HistoricalFlightListResponse(
        data=flights,
        pagination=PaginationMetadata(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1 and total > 0,
        ),
    )


@router.get(
    "/{flight_id}",
    response_model=HistoricalFlightDetailResponse,
    summary="Get a historical BTS flight",
)
def historical_flight_detail(
    flight_id: Annotated[UUID, Path(description="Historical record UUID.")],
    session: Session = Depends(get_db),
) -> HistoricalFlightDetailResponse:
    flight = get_historical_flight(session, flight_id)
    if flight is None:
        raise HTTPException(status_code=404, detail="Historical flight not found.")
    return HistoricalFlightDetailResponse(data=flight)
