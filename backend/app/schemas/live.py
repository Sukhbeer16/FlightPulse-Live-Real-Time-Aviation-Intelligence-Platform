"""Normalized responses for upstream live ADS-B state observations."""

from typing import Literal

from pydantic import BaseModel, Field


class LiveStateVector(BaseModel):
    icao24: str = Field(pattern="^[0-9a-f]{6}$")
    callsign: str | None
    origin_country: str
    time_position: int | None = Field(gt=0)
    last_contact: int = Field(gt=0)
    longitude: float | None = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float | None = Field(ge=-90, le=90, allow_inf_nan=False)
    barometric_altitude_m: float | None = Field(allow_inf_nan=False)
    on_ground: bool
    velocity_mps: float | None = Field(ge=0, allow_inf_nan=False)
    true_track_degrees: float | None = Field(ge=0, le=360, allow_inf_nan=False)
    vertical_rate_mps: float | None = Field(allow_inf_nan=False)
    geometric_altitude_m: float | None = Field(allow_inf_nan=False)
    squawk: str | None
    spi: bool
    position_source: int = Field(ge=0)
    category: int | None = Field(default=None, ge=0)


class LiveFlightStatesResponse(BaseModel):
    data_kind: Literal["live_state_vectors"] = "live_state_vectors"
    source: Literal["opensky"] = "opensky"
    source_time: int = Field(gt=0)
    count: int
    states: list[LiveStateVector]
    limitations: list[str] = Field(
        default_factory=lambda: [
            "ADS-B/Mode S state vectors are observations, not commercial schedules or confirmed delay labels."
        ]
    )


class FlightIdentityMatchResponse(BaseModel):
    data_kind: Literal["flight_identity_match"] = "flight_identity_match"
    callsign: str
    flight_date: str
    confidence: Literal["none", "low", "medium", "uncertain"]
    matched: bool
    airline_code: str | None = None
    flight_number: str | None = None
    origin: str | None = None
    destination: str | None = None
    candidate_count: int
    explanation: str
