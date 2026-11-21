"""Historical record search directly over processed BTS Parquet."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.schemas.flight import PaginationMetadata
from backend.app.schemas.historical import ProcessedParquetFlightListResponse
from backend.app.services.processed_historical import (
    HistoricalParquetUnavailable,
    SOURCE_PERIOD,
    search_processed_flights,
)


router = APIRouter(prefix="/historical", tags=["historical flights"])


@router.get(
    "/processed-flights",
    response_model=ProcessedParquetFlightListResponse,
    summary="Search processed BTS flight history",
    description=(
        "Query the available January and February 2024 BTS sources directly. "
        "Local HHMM values remain local; source row numbers identify records "
        "within this file and are not flight identifiers."
    ),
    responses={503: {"description": "The processed Parquet source is unavailable."}},
)
def list_processed_historical_flights(
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    flight_number: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
    airline_code: Annotated[str | None, Query(min_length=1, max_length=3)] = None,
    origin: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    destination: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    flight_date: Annotated[date | None, Query()] = None,
    cancelled: bool | None = None,
    diverted: bool | None = None,
    delayed: bool | None = Query(
        default=None,
        description="Arrival delay greater than 15 minutes; missing delay is excluded.",
    ),
    flight_identifier: Annotated[
        str | None, Query(min_length=1, max_length=16)
    ] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    departure_delay_min: Annotated[float | None, Query()] = None,
    departure_delay_max: Annotated[float | None, Query()] = None,
    arrival_delay_min: Annotated[float | None, Query()] = None,
    arrival_delay_max: Annotated[float | None, Query()] = None,
    sort_by: Literal[
        "source_row",
        "flight_date",
        "flight_number",
        "departure_delay",
        "arrival_delay",
    ] = "source_row",
    sort_order: Literal["asc", "desc"] = "asc",
) -> ProcessedParquetFlightListResponse:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not exceed date_to.")
    for minimum, maximum in (
        (departure_delay_min, departure_delay_max),
        (arrival_delay_min, arrival_delay_max),
    ):
        if minimum is not None and maximum is not None and minimum > maximum:
            raise HTTPException(
                status_code=422,
                detail="Delay minimum must not exceed delay maximum.",
            )
    try:
        flights, total = search_processed_flights(
            page=page,
            page_size=page_size,
            flight_number=flight_number,
            airline_code=airline_code,
            origin=origin,
            destination=destination,
            flight_date=flight_date,
            cancelled=cancelled,
            diverted=diverted,
            delayed=delayed,
            flight_identifier=flight_identifier,
            date_from=date_from,
            date_to=date_to,
            departure_delay_min=departure_delay_min,
            departure_delay_max=departure_delay_max,
            arrival_delay_min=arrival_delay_min,
            arrival_delay_max=arrival_delay_max,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except HistoricalParquetUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Historical Parquet records are unavailable.",
        ) from None
    total_pages = (total + page_size - 1) // page_size
    return ProcessedParquetFlightListResponse(
        source_period=SOURCE_PERIOD,
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
