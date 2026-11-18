"""SQLAlchemy model registry used by Alembic and application code."""

from backend.app.database.models.airline import Airline
from backend.app.database.models.airport import Airport
from backend.app.database.models.bts_reference import (
    BTSAirportReference,
    BTSCarrierReference,
    BTSReferenceRelease,
)
from backend.app.database.models.flight import Flight
from backend.app.database.models.historical import BTSRelease, HistoricalBTSFlight

__all__ = [
    "Airline",
    "Airport",
    "Flight",
    "BTSRelease",
    "HistoricalBTSFlight",
    "BTSReferenceRelease",
    "BTSCarrierReference",
    "BTSAirportReference",
]
