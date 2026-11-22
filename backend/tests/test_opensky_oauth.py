from types import SimpleNamespace

from backend.app.services import opensky


def test_oauth_reuses_and_reacquires_token_before_expiry(monkeypatch):
    clock = [100.0]
    requests = []
    monkeypatch.setattr(opensky, "_cached_token", None)
    monkeypatch.setattr(opensky.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        opensky,
        "get_settings",
        lambda: SimpleNamespace(
            opensky_client_id="fixture", opensky_client_secret="fixture"
        ),
    )

    def issue(request):
        requests.append(request)
        return {"access_token": str(len(requests)), "expires_in": 60}

    monkeypatch.setattr(opensky, "_read_json", issue)
    assert opensky._access_token() == opensky._access_token() == "1"
    clock[0] += 31
    assert opensky._access_token() == "2"
    assert all(r.full_url == opensky.TOKEN_URL and r.method == "POST" for r in requests)
    assert b"grant_type=client_credentials" in requests[0].data
