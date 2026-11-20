"""Tests for bounded live-state response caching."""

import io
import json

import pytest

from backend.app.services import opensky


def test_live_state_response_is_cached_per_region(monkeypatch) -> None:
    payload = {"time": 1_700_000_000, "states": []}
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def urlopen(request, timeout):
        calls.append(request.full_url)
        return Response(json.dumps(payload).encode())

    opensky.clear_state_cache()
    monkeypatch.setattr(opensky, "_access_token", lambda: None)
    monkeypatch.setattr(opensky, "urlopen", urlopen)

    first = opensky.get_live_states(lamin=40, lomin=-75, lamax=42, lomax=-72)
    second = opensky.get_live_states(lamin=40, lomin=-75, lamax=42, lomax=-72)

    assert first == second == (1_700_000_000, [])
    assert len(calls) == 1


def test_live_state_validation_deduplicates_aircraft_and_rejects_bad_coordinates(
    monkeypatch,
) -> None:
    state = [
        "abc123",
        " UA123  ",
        "United States",
        1_700_000_000,
        1_700_000_001,
        -73.78,
        40.64,
        10_000.0,
        False,
        230.0,
        270.0,
        -1.0,
        None,
        10_300.0,
        "1200",
        False,
        0,
        2,
    ]
    newest = list(state)
    newest[4] += 1
    newest[5] = -73.7
    invalid_state = list(state)
    invalid_state[5] = 181
    payloads = iter(
        (
            {"time": 1_700_000_002, "states": [state, newest]},
            {"time": 1_700_000_002, "states": [invalid_state]},
        )
    )

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def urlopen(request, timeout):
        return Response(json.dumps(next(payloads)).encode())

    opensky.clear_state_cache()
    monkeypatch.setattr(opensky, "_access_token", lambda: None)
    monkeypatch.setattr(opensky, "urlopen", urlopen)

    _, states = opensky.get_live_states(lamin=40, lomin=-75, lamax=42, lomax=-72)
    assert len(states) == 1
    assert states[0].callsign == "UA123"
    assert states[0].longitude == -73.7

    opensky.clear_state_cache()
    with pytest.raises(opensky.OpenSkyUnavailable):
        opensky.get_live_states(lamin=41, lomin=-74, lamax=43, lomax=-71)
