"""Small OpenSky state-vector client using the standard library only."""

from __future__ import annotations

import json
import time
import re
from collections import OrderedDict
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.app.config.settings import get_settings
from backend.app.schemas.live import LiveStateVector


API_URL = "https://opensky-network.org/api/states/all"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
REQUEST_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
STATE_CACHE_TTL_SECONDS = 10
MAX_CACHED_REGIONS = 8
MAX_CACHED_STATE_VECTORS = 2_000
_token_lock = Lock()
_cached_token: str | None = None
_token_expires_at = 0.0
_state_cache_lock = Lock()
_state_cache: OrderedDict[
    tuple[float, float, float, float],
    tuple[float, int, tuple[LiveStateVector, ...]],
] = OrderedDict()


class OpenSkyUnavailable(RuntimeError):
    """An upstream timeout, access denial, or rate limit with safe retry data."""

    def __init__(
        self, *, retry_after: str | None = None, status_code: int | None = None
    ) -> None:
        self.retry_after = retry_after
        self.status_code = status_code
        super().__init__("OpenSky is temporarily unavailable.")


def clear_state_cache() -> None:
    """Clear cached state vectors, primarily for deterministic tests."""
    with _state_cache_lock:
        _state_cache.clear()


def parse_callsign_flight_identity(
    callsign: str | None,
) -> tuple[str, str] | None:
    """Parse callsign only when it has an explicit airline prefix and numeric suffix."""
    if callsign is None:
        return None
    match = re.fullmatch(r"([A-Z]{2,3})([0-9]{1,4})", callsign.strip().upper())
    if match is None:
        return None
    return match.group(1), match.group(2)


def _read_json(request: Request, *, timeout: int = REQUEST_TIMEOUT_SECONDS) -> dict:
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        retry_after = error.headers.get("X-Rate-Limit-Retry-After-Seconds")
        if error.code == 429:
            retry_after = retry_after or error.headers.get("Retry-After") or "60"
        raise OpenSkyUnavailable(
            retry_after=retry_after, status_code=error.code
        ) from None
    except (URLError, TimeoutError, OSError):
        raise OpenSkyUnavailable() from None
    if len(payload) > MAX_RESPONSE_BYTES:
        raise OpenSkyUnavailable()
    try:
        result = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OpenSkyUnavailable() from None
    if not isinstance(result, dict):
        raise OpenSkyUnavailable()
    return result


def _access_token() -> str | None:
    global _cached_token, _token_expires_at
    settings = get_settings()
    client_id = settings.opensky_client_id
    client_secret = settings.opensky_client_secret
    if not client_id and not client_secret:
        return None
    if not client_id or not client_secret:
        raise OpenSkyUnavailable()
    with _token_lock:
        if _cached_token and time.monotonic() < _token_expires_at:
            return _cached_token
        body = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode("utf-8")
        request = Request(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        payload = _read_json(request)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise OpenSkyUnavailable()
        try:
            expires_in = max(60, int(payload.get("expires_in", 1800)))
        except (TypeError, ValueError):
            expires_in = 1800
        _cached_token = token
        _token_expires_at = time.monotonic() + expires_in - 30
        return token


def get_live_states(
    *, lamin: float, lomin: float, lamax: float, lomax: float
) -> tuple[int, list[LiveStateVector]]:
    """Fetch current state vectors for one bounded region; never infer schedules."""
    cache_key = (lamin, lomin, lamax, lomax)
    now = time.monotonic()
    with _state_cache_lock:
        cached = _state_cache.get(cache_key)
        if cached is not None:
            expires_at, source_time, cached_states = cached
            if now < expires_at:
                _state_cache.move_to_end(cache_key)
                return source_time, [
                    state.model_copy(deep=True) for state in cached_states
                ]
            del _state_cache[cache_key]

    query = urlencode(
        {"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax}
    )
    headers = {"Accept": "application/json", "User-Agent": "FlightPulseLive/0.1"}
    token = _access_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{API_URL}?{query}", headers=headers)
    try:
        payload = _read_json(request)
    except OpenSkyUnavailable as error:
        if error.status_code != 401 or token is None:
            raise
        global _cached_token, _token_expires_at
        with _token_lock:
            _cached_token = None
            _token_expires_at = 0.0
        refreshed_token = _access_token()
        if refreshed_token is None:
            raise
        headers["Authorization"] = f"Bearer {refreshed_token}"
        payload = _read_json(Request(f"{API_URL}?{query}", headers=headers))
    source_time = payload.get("time")
    states = payload.get("states")
    if (
        type(source_time) is not int
        or source_time <= 0
        or source_time > time.time() + 60
        or (
        states is not None and not isinstance(states, list)
        )
    ):
        raise OpenSkyUnavailable()
    normalized_states: dict[str, LiveStateVector] = {}
    for state in states or []:
        if not isinstance(state, list) or len(state) < 17:
            raise OpenSkyUnavailable()
        if any(
            timestamp is not None
            and (
                type(timestamp) is not int
                or timestamp <= 0
                or timestamp > source_time + 60
            )
            for timestamp in (state[3], state[4])
        ):
            raise OpenSkyUnavailable()
        try:
            icao24 = str(state[0]).strip().lower()
            raw_callsign = state[1]
            normalized = LiveStateVector(
                icao24=icao24,
                callsign=(
                    str(raw_callsign).strip() or None
                    if raw_callsign is not None
                    else None
                ),
                origin_country=state[2],
                time_position=state[3],
                last_contact=state[4],
                longitude=state[5],
                latitude=state[6],
                barometric_altitude_m=state[7],
                on_ground=state[8],
                velocity_mps=state[9],
                true_track_degrees=state[10],
                vertical_rate_mps=state[11],
                geometric_altitude_m=state[13],
                squawk=state[14],
                spi=state[15],
                position_source=state[16],
                category=state[17] if len(state) > 17 else None,
            )
        except (TypeError, ValueError):
            raise OpenSkyUnavailable() from None
        current = normalized_states.get(icao24)
        if current is None or normalized.last_contact > current.last_contact:
            normalized_states[icao24] = normalized
    result = list(normalized_states.values())
    if len(result) <= MAX_CACHED_STATE_VECTORS:
        with _state_cache_lock:
            _state_cache[cache_key] = (
                time.monotonic() + STATE_CACHE_TTL_SECONDS,
                source_time,
                tuple(state.model_copy(deep=True) for state in result),
            )
            _state_cache.move_to_end(cache_key)
            while len(_state_cache) > MAX_CACHED_REGIONS:
                _state_cache.popitem(last=False)
    return source_time, result
