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


@router.get("/delay-explanation", summary="Source reported BTS delay causes")
def delay_explanation(
    source_file: Annotated[str, Query(min_length=1, max_length=100)],
    source_row_number: Annotated[int, Query(ge=1)],
):
    try:
        rows, _ = search_processed_flights(page=1, page_size=1,
                                           source_file=source_file, source_row_number=source_row_number)
    except HistoricalParquetUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    if not rows:
        raise HTTPException(404, "Historical source record not found.")
    row = rows[0]
    reasons = row.delay_reasons
    total = sum(reason["minutes"] for reason in reasons)
    return {"data_kind": "historical_bts_delay_explanation",
            "flight_reference": "".join(x for x in (row.reporting_airline, row.flight_number) if x) or None,
            "airline": row.airline_name or row.reporting_airline,
            "origin": row.origin_bts_code, "destination": row.destination_bts_code,
            "flight_date": row.flight_date,
            "arrival_delay_minutes": row.arrival_delay_minutes,
            "departure_delay_minutes": row.departure_delay_minutes,
            "reported_causes": [{**reason, "percent_of_reported": round(100*reason["minutes"]/total, 2)}
                                for reason in reasons] if total > 0 else [],
            "total_reported_cause_minutes": total if reasons else None,
            "status": "reported" if reasons else "not_reported",
            "message": "BTS reported historical delay causes." if reasons else
                       "No specific delay cause was reported in the BTS record.",
            "provenance": {"source_file": row.source_file,
                           "source_row_number": row.source_row_number,
                           "record_date": row.flight_date}}


@router.get("/map-coverage", summary="Dataset airport and route coverage")
def map_coverage(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
    city: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    airport: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    origin: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    destination: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    airline: Annotated[str | None, Query(min_length=1, max_length=3)] = None,
    flight_number: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    delayed: bool | None = None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not exceed date_to.")
    from backend.app.services.map_coverage import coverage
    try:
        return coverage(page=page, page_size=page_size, city=city, airport=airport,
                        origin=origin, destination=destination,
                        airline=airline, flight_number=flight_number,
                        date_from=date_from, date_to=date_to, delayed=delayed)
    except HistoricalParquetUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


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
    airport: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
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
            airport=airport,
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
