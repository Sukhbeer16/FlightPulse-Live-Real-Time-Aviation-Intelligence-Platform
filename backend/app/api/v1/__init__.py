"""Version 1 API route collection."""

from fastapi import APIRouter

from backend.app.api.v1.analytics import router as analytics_router
from backend.app.api.v1.airlines import router as airlines_router
from backend.app.api.v1.airports import router as airports_router
from backend.app.api.v1.flights import router as flights_router
from backend.app.api.v1.historical import router as historical_router
from backend.app.api.v1.live import router as live_router
from backend.app.api.v1.intelligence import router as intelligence_router
from backend.app.api.v1.processed_historical import router as processed_historical_router

router = APIRouter()
router.include_router(analytics_router)
router.include_router(airlines_router)
router.include_router(airports_router)
router.include_router(flights_router)
router.include_router(historical_router)
router.include_router(live_router)
router.include_router(intelligence_router)
router.include_router(processed_historical_router)

__all__ = ["router"]
