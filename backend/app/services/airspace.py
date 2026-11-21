"""Regional ADS-B observations from the public adsb.lol service."""
import json
import math
import time
from threading import Lock
from urllib.request import Request, urlopen

REGIONS = {
    "new-york": (40.75, -73.8),
    "london": (51.47, -0.45),
    "delhi": (28.56, 77.10),
    "amsterdam": (52.31, 4.76),
}
_cache = {}
_lock = Lock()


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def get_airspace(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        lat, lon = key
        url = f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/80"
        request = Request(url, headers={"User-Agent": "FlightPulse/1.0", "Accept": "application/json"})
        with urlopen(request, timeout=7) as response:
            payload = json.loads(response.read(4_000_000))
        stamp = number(payload.get("now"))
        if not stamp or not isinstance(payload.get("ac"), list):
            raise ValueError("Invalid aircraft feed")
        aircraft = {}
        for row in payload["ac"]:
            x, y = number(row.get("lon")), number(row.get("lat"))
            age = number(row.get("seen_pos"))
            ident = row.get("hex")
            if not ident or x is None or y is None or abs(y) > 90 or abs(x) > 180:
                continue
            if age is None or age < 0 or age > 120:
                continue
            ground = row.get("alt_baro") == "ground"
            aircraft[ident] = dict(
                id=ident, callsign=(row.get("flight") or "").strip() or ident.upper(),
                registration=row.get("r"), type=row.get("t"), lon=x, lat=y,
                ground=ground, altitude=0 if ground else number(row.get("alt_baro")),
                speed=number(row.get("gs")), heading=number(row.get("track")),
                verticalRate=number(row.get("baro_rate")), squawk=row.get("squawk"),
                observed=round(stamp - age * 1000),
            )
        snapshot = {"time": stamp, "aircraft": list(aircraft.values())}
        if len(_cache) >= 16 and key not in _cache:
            del _cache[min(_cache, key=lambda item: _cache[item][0])]
        _cache[key] = (time.monotonic() + 20, snapshot)
        return snapshot
