"""Versioned Kafka payloads for live observations and real-time ML predictions.

Kafka keys:
- flight-states: ICAO24 string (UTF-8)
- flight-predictions: flight_id / ICAO24 string (UTF-8)
"""

from __future__ import annotations

import time
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.schemas.live import LiveStateVector


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    source: Literal["opensky", "adsb_lol", "SIMULATION"]
    source_time: int = Field(gt=0)
    state: LiveStateVector

    @model_validator(mode="after")
    def validate_clock(self):
        if (
            self.source_time > time.time() + 60
            or max(self.state.last_contact, self.state.time_position or 0)
            > self.source_time + 60
        ):
            raise ValueError("Observation timestamp exceeds provider clock tolerance")
        return self


class FlightPredictionEvent(BaseModel):
    """Stable JSON schema for the flight-predictions Kafka topic."""
    model_config = ConfigDict(extra="ignore", strict=False)

    flight_id: str = Field(description="Aircraft ICAO24 or flight identifier")
    timestamp: int = Field(gt=0, description="Source observation timestamp in UTC epoch seconds")
    prediction: int = Field(ge=0, le=1, description="Binary classification (1=delayed, 0=not_delayed)")
    predicted_class: Literal["delayed", "not_delayed"]
    delay_probability: float = Field(ge=0.0, le=1.0, description="Estimated delay probability P(ArrDelay > 15)")
    threshold: float = Field(ge=0.0, le=1.0, description="Decision threshold applied")
    model_id: str = Field(description="Algorithm and configuration identifier")
    model_version: str = Field(description="Model artifact version or timestamp")
    prediction_timestamp: str = Field(description="ISO-8601 UTC timestamp of inference")
    latency_ms: float = Field(ge=0.0, description="Model inference latency in milliseconds")
    callsign: str | None = None
    source: str = Field(default="live_stream", description="Observation source (opensky, adsb_lol, SIMULATION)")
    features: dict[str, Any] = Field(default_factory=dict, description="Summary of features evaluated")
