"""Airline catalog HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.schemas.catalog import AirlineDetailResponse, AirlineListResponse
from backend.app.schemas.flight import PaginationMetadata
from backend.app.services.airlines import get_airline, search_airlines


router = APIRouter(prefix="/airlines", tags=["airlines"])


@router.get(
    "",
    response_model=AirlineListResponse,
    summary="Search airlines",
    description="List airlines with optional case-insensitive code or name search.",
)
def list_airlines(
    page: Annotated[int, Query(ge=1, le=1_000_000, description="1-based page number.")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Results per page (maximum 100).")
    ] = 20,
    search: Annotated[
        str | None,
        Query(min_length=1, max_length=160, description="Match airline code or name."),
    ] = None,
    session: Session = Depends(get_db),
) -> AirlineListResponse:
    """Return a page of airlines matching an optional search term."""
    airlines, total = search_airlines(
        session=session,
        page=page,
        page_size=page_size,
        search=search,
    )
    total_pages = (total + page_size - 1) // page_size
    return AirlineListResponse(
        data=airlines,
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
    "/{airline_code}",
    response_model=AirlineDetailResponse,
    summary="Get an airline",
    description="Return an airline by its carrier code.",
)
def airline_detail(
    airline_code: Annotated[
        str,
        Path(
            min_length=1,
            max_length=3,
            pattern="^[A-Za-z0-9]+$",
            description="Airline carrier code.",
        ),
    ],
    session: Session = Depends(get_db),
) -> AirlineDetailResponse:
    """Return an airline by code or a 404 response when it is absent."""
    airline = get_airline(session, airline_code)
    if airline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Airline not found.",
        )
    return AirlineDetailResponse(data=airline)
