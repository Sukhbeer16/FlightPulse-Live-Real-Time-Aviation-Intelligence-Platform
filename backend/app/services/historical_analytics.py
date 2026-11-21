"""Read bounded, precomputed Parquet aggregates without copying them to SQL."""

from pathlib import Path
from typing import Any

from backend.app.config.settings import get_settings


SOURCE_PERIOD = "2024-01"
REPORT_FILES = {
    "airlines": "airline_analytics.parquet",
    "origin-airports": "origin_airport_analytics.parquet",
    "destination-airports": "destination_airport_analytics.parquet",
    "routes": "route_analytics.parquet",
    "hourly": "hourly_analytics.parquet",
    "day-of-week": "day_of_week_analytics.parquet",
    "delay-distribution": "delay_distribution.parquet",
}
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_REPORT_ROWS = 100_000


class AnalyticsUnavailable(RuntimeError):
    """An expected, bounded historical aggregate is missing or invalid."""


def _report_path(report: str) -> Path:
    try:
        filename = REPORT_FILES[report]
    except KeyError as error:
        raise ValueError("Unknown analytics report.") from error
    return get_settings().data_directory / "processed" / "analytics" / filename


def _read_report(report: str) -> list[dict[str, Any]]:
    path = _report_path(report)
    try:
        if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
            raise AnalyticsUnavailable(
                "The requested historical report is unavailable."
            )
        import pyarrow.parquet as parquet

        parquet_file = parquet.ParquetFile(path)
        if parquet_file.metadata.num_rows > MAX_REPORT_ROWS:
            raise AnalyticsUnavailable(
                "The report exceeds the configured bounded response size."
            )
        return parquet_file.read().to_pylist()
    except AnalyticsUnavailable:
        raise
    except Exception as error:
        raise AnalyticsUnavailable(
            "The requested historical report could not be read."
        ) from error


def get_historical_report(report: str) -> list[dict[str, Any]]:
    """Read one small generated aggregate; flight-level Parquet is not loaded."""
    return _read_report(report)


def get_historical_overview() -> dict[str, int | float | None]:
    """Calculate aggregate overview metrics from the compact airline report."""
    rows = _read_report("airlines")
    total_flights = sum(int(row["total_flights"] or 0) for row in rows)
    eligible = sum(int(row["eligible_delay_records"] or 0) for row in rows)
    delayed = sum(int(row["delayed_flights"] or 0) for row in rows)
    cancelled = sum(int(row["cancelled_flights"] or 0) for row in rows)
    diverted = sum(int(row["diverted_flights"] or 0) for row in rows)
    delay_numerator = sum(
        float(row["average_arrival_delay_minutes"] or 0)
        * int(row["eligible_delay_records"] or 0)
        for row in rows
    )
    return {
        "total_flights": total_flights,
        "eligible_arrival_records": eligible,
        "delayed_flights": delayed,
        "cancelled_flights": cancelled,
        "diverted_flights": diverted,
        "delay_rate": delayed / eligible if eligible else None,
        "cancellation_rate": cancelled / total_flights if total_flights else None,
        "average_arrival_delay_minutes": (
            delay_numerator / eligible if eligible else None
        ),
    }
