"""Pydantic v2 schemas for flight discovery responses."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AirlineSummary(BaseModel):
    """Public airline fields included with a flight."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str


class GeoPoint(BaseModel):
    """GeoJSON point in longitude, latitude order."""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class AirportSummary(BaseModel):
    """Public airport details included with a flight."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    iata_code: str | None
    icao_code: str | None
    name: str
    city: str | None
    country_code: str | None
    location: GeoPoint | None


class FlightRead(BaseModel):
    """Available flight occurrence fields and related reference data."""

    id: UUID
    source: str
    source_flight_id: str | None
    flight_number: str | None
    callsign: str | None
    airline_code: str | None
    origin_airport_id: int | None
    destination_airport_id: int | None
    scheduled_departure_at: datetime
    scheduled_arrival_at: datetime | None
    actual_departure_at: datetime | None
    actual_arrival_at: datetime | None
    status: str | None
    updated_at: datetime
    airline: AirlineSummary | None
    origin_airport: AirportSummary | None
    destination_airport: AirportSummary | None


class PaginationMetadata(BaseModel):
    """Page counts and navigation flags for a flight search."""

    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class FlightListResponse(BaseModel):
    """Standard list response envelope."""

    data: list[FlightRead]
    pagination: PaginationMetadata


class FlightDetailResponse(BaseModel):
    """Standard single-flight response envelope."""

    data: FlightRead
