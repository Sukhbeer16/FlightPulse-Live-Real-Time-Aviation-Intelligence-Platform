"""Pydantic v2 schemas for airline and airport catalog responses."""

from datetime import datetime

from pydantic import BaseModel

from backend.app.schemas.flight import AirlineSummary, AirportSummary, PaginationMetadata


class AirlineRead(AirlineSummary):
    """Airline catalog representation."""

    created_at: datetime


class AirportRead(AirportSummary):
    """Airport catalog representation, including its available location."""

    created_at: datetime


class AirlineListResponse(BaseModel):
    """Paginated airline response envelope."""

    data: list[AirlineRead]
    pagination: PaginationMetadata


class AirlineDetailResponse(BaseModel):
    """Single-airline response envelope."""

    data: AirlineRead


class AirportListResponse(BaseModel):
    """Paginated airport response envelope."""

    data: list[AirportRead]
    pagination: PaginationMetadata


class AirportDetailResponse(BaseModel):
    """Single-airport response envelope."""

    data: AirportRead
