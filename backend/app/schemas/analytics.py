"""Typed envelopes for precomputed historical analytics."""

from typing import Any, Literal

from pydantic import BaseModel


class AnalyticsReportResponse(BaseModel):
    data_kind: Literal["historical_aggregate"] = "historical_aggregate"
    report: str
    source_period: str
    data: list[dict[str, Any]]


class OverviewStatistics(BaseModel):
    total_flights: int
    eligible_arrival_records: int
    delayed_flights: int
    cancelled_flights: int
    diverted_flights: int
    delay_rate: float | None
    cancellation_rate: float | None
    average_arrival_delay_minutes: float | None


class OverviewResponse(BaseModel):
    data_kind: Literal["historical_aggregate"] = "historical_aggregate"
    source_period: str
    statistics: OverviewStatistics
