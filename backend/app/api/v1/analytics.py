"""Read-only endpoints for the existing compact BTS analytics outputs."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, status

from backend.app.schemas.analytics import (
    AnalyticsReportResponse,
    OverviewResponse,
    OverviewStatistics,
)
from backend.app.services.historical_analytics import (
    AnalyticsUnavailable,
    SOURCE_PERIOD,
    get_historical_overview,
    get_historical_report,
)


router = APIRouter(prefix="/analytics", tags=["historical analytics"])
ReportName = Literal[
    "airlines",
    "origin-airports",
    "destination-airports",
    "routes",
    "hourly",
    "day-of-week",
    "delay-distribution",
]


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Get historical overview statistics",
    description="Aggregate BTS statistics for January 2024; this is not live data.",
)
def historical_overview() -> OverviewResponse:
    try:
        statistics = get_historical_overview()
    except AnalyticsUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Historical analytics are unavailable.",
        ) from None
    return OverviewResponse(
        source_period=SOURCE_PERIOD,
        statistics=OverviewStatistics(**statistics),
    )


@router.get(
    "/{report}",
    response_model=AnalyticsReportResponse,
    summary="Get a historical analytics report",
    description=(
        "Return one compact precomputed Parquet aggregate. Supported reports: "
        "airlines, origin-airports, destination-airports, routes, hourly, "
        "day-of-week, and delay-distribution."
    ),
)
def historical_report(
    report: Annotated[ReportName, Path(description="A supported aggregate name.")],
) -> AnalyticsReportResponse:
    try:
        rows = get_historical_report(report)
    except AnalyticsUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Historical analytics are unavailable.",
        ) from None
    return AnalyticsReportResponse(
        report=report,
        source_period=SOURCE_PERIOD,
        data=rows,
    )
