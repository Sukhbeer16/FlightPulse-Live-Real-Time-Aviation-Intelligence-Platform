"""Version 1 API route collection."""

from fastapi import APIRouter

from backend.app.api.v1.airlines import router as airlines_router
from backend.app.api.v1.airports import router as airports_router
from backend.app.api.v1.flights import router as flights_router

router = APIRouter()
router.include_router(airlines_router)
router.include_router(airports_router)
router.include_router(flights_router)

__all__ = ["router"]
