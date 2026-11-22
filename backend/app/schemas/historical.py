"""Response schemas for source-faithful historical BTS flight records."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.flight import PaginationMetadata


class HistoricalReleaseSummary(BaseModel):
    """Source provenance for the imported historical row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_name: str
    reporting_period: date
    source_file_sha256: str


class HistoricalFlightRead(BaseModel):
    """Historical BTS facts with original local-clock values unchanged."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    data_kind: Literal["historical_bts"] = "historical_bts"
    release: HistoricalReleaseSummary
    flight_date: date
    reporting_airline_code: str
    reporting_dot_carrier_id: int | None
    reporting_flight_number: str | None
    origin_bts_code: str
    destination_bts_code: str
    origin_dot_airport_id: int | None
    destination_dot_airport_id: int | None
    origin_dot_airport_seq_id: int | None
    destination_dot_airport_seq_id: int | None
    scheduled_departure_hhmm: int | None
    actual_departure_hhmm: int | None
    scheduled_arrival_hhmm: int | None
    actual_arrival_hhmm: int | None
    departure_delay_minutes: int | None
    arrival_delay_minutes: int | None
    cancelled: int | None
    diverted: int | None
    cancellation_code: str | None


class HistoricalFlightListResponse(BaseModel):
    data_kind: Literal["historical_bts"] = "historical_bts"
    data: list[HistoricalFlightRead]
    pagination: PaginationMetadata


class HistoricalFlightDetailResponse(BaseModel):
    data_kind: Literal["historical_bts"] = "historical_bts"
    data: HistoricalFlightRead


class ProcessedParquetFlightRead(BaseModel):
    """One source row read directly from a processed monthly BTS Parquet file."""

    data_kind: Literal["historical_bts"] = "historical_bts"
    distance_miles: float | None = None
    scheduled_elapsed_time_minutes: float | None = None
    source_file: str
    source_row_number: int
    flight_date: date
    reporting_airline: str | None
    flight_number: str | None
    origin_bts_code: str | None
    destination_bts_code: str | None
    scheduled_departure_local_hhmm: int | None
    actual_departure_local_hhmm: int | None
    scheduled_arrival_local_hhmm: int | None
    actual_arrival_local_hhmm: int | None
    departure_delay_minutes: float | None
    arrival_delay_minutes: float | None
    cancelled: int | None
    diverted: int | None
    cancellation_code: str | None
    reporting_airline_id: str | None = None
    origin_airport_seq_id: str | None = None
    destination_airport_seq_id: str | None = None
    airline_name: str | None = None
    origin_name: str | None = None
    destination_name: str | None = None
    origin_coordinates: tuple[float, float] | None = None
    destination_coordinates: tuple[float, float] | None = None
    carrier_delay_minutes: float | None = None
    weather_delay_minutes: float | None = None
    airspace_delay_minutes: float | None = None
    security_delay_minutes: float | None = None
    late_aircraft_delay_minutes: float | None = None
    delay_reasons: list[dict] = Field(default_factory=list)


class ProcessedParquetFlightListResponse(BaseModel):
    data_kind: Literal["historical_bts"] = "historical_bts"
    source_period: str
    data: list[ProcessedParquetFlightRead]
    pagination: PaginationMetadata
