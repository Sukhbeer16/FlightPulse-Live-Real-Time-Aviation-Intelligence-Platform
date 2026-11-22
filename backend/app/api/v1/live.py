"""Live OpenSky state-vector and identity-matching routes."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.schemas.live import FlightIdentityMatchResponse, LiveFlightStatesResponse
from backend.app.services.opensky import OpenSkyUnavailable, get_live_states, cached_response, provider_status
from backend.app.services.flight_identity import match_historical_callsign
from backend.app.services.airspace import get_airspace, REGIONS


router = APIRouter(prefix="/live", tags=["live tracking"])


@router.get("/stream-states")
def stream_states():
    from backend.app.streaming.store import latest_states
    return latest_states()


@router.get("/airspace/{region}")
def regional_airspace(region: Literal["new-york", "london", "delhi", "amsterdam"]):
    return airspace_at(*REGIONS[region])


@router.get("/airspace")
def airspace_at(lat: Annotated[float, Query(ge=-90, le=90)], lon: Annotated[float, Query(ge=-180, le=180)]):
    try:
        return get_airspace(lat, lon)
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="ADS-B feed temporarily unavailable.") from None


def _live_states(
    lamin: float,
    lomin: float,
    lamax: float,
    lomax: float,
) -> LiveFlightStatesResponse:
    if lamin >= lamax or lomin >= lomax:
        raise HTTPException(status_code=422, detail="Bounding-box minimums must be below their maximums.")
    if (lamax - lamin) * (lomax - lomin) > 400:
        raise HTTPException(status_code=422, detail="Bounding-box area must not exceed 400 square degrees.")
    try:
        source_time, states = get_live_states(
            lamin=lamin, lomin=lomin, lamax=lamax, lomax=lomax
        )
    except OpenSkyUnavailable as error:
        headers = {"Retry-After": error.retry_after} if error.retry_after else None
        raise HTTPException(
            status_code=503,
            detail=f"OpenSky request failed ({provider_status['state']}).",
            headers=headers,
        ) from None
    return LiveFlightStatesResponse(
        cached=cached_response.get(),
        source_time=source_time,
        count=len(states),
        states=states,
    )


@router.get(
    "/states",
    response_model=LiveFlightStatesResponse,
    summary="Get live aircraft state vectors",
    description=(
        "Fetch a bounded region from OpenSky. State vectors are ADS-B/Mode S "
        "observations and are not commercial schedules or delay labels."
    ),
    responses={503: {"description": "OpenSky is unavailable or rate-limited."}},
)
def live_states(
    lamin: Annotated[float, Query(ge=-90, le=90)],
    lomin: Annotated[float, Query(ge=-180, le=180)],
    lamax: Annotated[float, Query(ge=-90, le=90)],
    lomax: Annotated[float, Query(ge=-180, le=180)],
) -> LiveFlightStatesResponse:
    """Return normalized current state vectors for a regional bounding box."""
    return _live_states(lamin, lomin, lamax, lomax)


@router.get(
    "/flights",
    response_model=LiveFlightStatesResponse,
    summary="Frontend-ready live flight state aliases",
)
def live_flights(
    lamin: Annotated[float, Query(ge=-90, le=90)],
    lomin: Annotated[float, Query(ge=-180, le=180)],
    lamax: Annotated[float, Query(ge=-90, le=90)],
    lomax: Annotated[float, Query(ge=-180, le=180)],
) -> LiveFlightStatesResponse:
    return _live_states(lamin, lomin, lamax, lomax)


@router.get(
    "/identity-match",
    response_model=FlightIdentityMatchResponse,
    summary="Safely match callsign/flight number against historical BTS records",
)
def live_identity_match(
    callsign: Annotated[str, Query(min_length=1, max_length=16)],
    flight_date: date,
) -> FlightIdentityMatchResponse:
    return FlightIdentityMatchResponse(**match_historical_callsign(callsign, flight_date))

@router.get("/stream-summary")
def stream_summary(source: Literal["opensky", "adsb_lol", "SIMULATION"] = "opensky"):
    """Latest aircraft-level five-minute event-time windows, separated by source."""
    from backend.app.streaming.store import summary
    return summary(source)



@router.get("/provider-status")
def live_provider_status():
    from backend.app.config.settings import get_settings
    settings = get_settings()
    return {**provider_status, "oauth_configured": bool(settings.opensky_client_id and settings.opensky_client_secret)}
