"""Airport catalog HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.schemas.catalog import AirportDetailResponse, AirportListResponse
from backend.app.schemas.flight import PaginationMetadata
from backend.app.services.airports import get_airport, search_airports


router = APIRouter(prefix="/airports", tags=["airports"])


@router.get(
    "",
    response_model=AirportListResponse,
    summary="Search airports",
    description=(
        "List airports with optional case-insensitive name, IATA or ICAO search "
        "and country-code filtering."
    ),
)
def list_airports(
    page: Annotated[int, Query(ge=1, le=1_000_000, description="1-based page number.")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Results per page (maximum 100).")
    ] = 20,
    search: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Match airport name, IATA code or ICAO code.",
        ),
    ] = None,
    country_code: Annotated[
        str | None,
        Query(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 code."),
    ] = None,
    session: Session = Depends(get_db),
) -> AirportListResponse:
    """Return a page of airports matching the supplied filters."""
    airports, total = search_airports(
        session=session,
        page=page,
        page_size=page_size,
        search=search,
        country_code=country_code,
    )
    total_pages = (total + page_size - 1) // page_size
    return AirportListResponse(
        data=airports,
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
    "/{iata_code}",
    response_model=AirportDetailResponse,
    summary="Get an airport",
    description="Return an airport by its three-character IATA code.",
)
def airport_detail(
    iata_code: Annotated[
        str,
        Path(
            min_length=3,
            max_length=3,
            pattern="^[A-Za-z0-9]{3}$",
            description="Three-character IATA airport code.",
        ),
    ],
    session: Session = Depends(get_db),
) -> AirportDetailResponse:
    """Return an airport by IATA code or a 404 response when it is absent."""
    airport = get_airport(session, iata_code)
    if airport is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Airport not found.",
        )
    return AirportDetailResponse(data=airport)
