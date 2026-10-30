"""HTTP endpoints for the FlightPulse Live API."""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.config.settings import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    """Health status returned by the service readiness endpoint."""

    status: str
    service: str
    version: str
    environment: str


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
