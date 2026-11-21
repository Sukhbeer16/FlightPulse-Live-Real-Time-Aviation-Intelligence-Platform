"""Versioned Kafka payload. Kafka keys use the same ICAO24 as the observation."""

import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.schemas.live import LiveStateVector


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    source: Literal["opensky", "SIMULATION"]
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
