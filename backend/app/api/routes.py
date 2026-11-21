"""HTTP endpoints for the FlightPulse Live API."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config.settings import get_settings
from backend.app.database.session import get_engine

router = APIRouter()


class HealthResponse(BaseModel):
    """Health status returned by the service readiness endpoint."""

    status: str
    service: str
    version: str
    environment: str


class DatabaseHealthResponse(BaseModel):
    """Database connectivity without exposing connection details."""

    status: str
    database: str


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """Report that the API process is responsive."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
    tags=["health"],
    summary="Check database connectivity",
    responses={503: {"description": "The configured database is unavailable."}},
)
def database_health_check() -> DatabaseHealthResponse:
    """Run a lightweight SELECT 1 using the lazily initialized engine."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (RuntimeError, SQLAlchemyError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from None
    return DatabaseHealthResponse(status="ok", database="connected")
