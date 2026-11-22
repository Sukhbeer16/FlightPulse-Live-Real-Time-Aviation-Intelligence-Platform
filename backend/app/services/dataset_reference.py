"""Local BTS reference enrichment using stable DOT IDs, never a callsign guess."""
import csv
import io
import math
from functools import lru_cache
from zipfile import ZipFile, BadZipFile

from backend.app.config.settings import get_settings


def references():
    root = get_settings().data_directory / "reference"
    paths = [root / name for name in ("Master_Coordinate.zip", "Carrier_Decode.zip")]
    return _read(tuple((str(p), p.stat().st_mtime_ns if p.exists() else 0) for p in paths))


@lru_cache(maxsize=4)
def _read(paths):
    airports, airlines = {}, {}
    for (path, stamp), member in zip(paths, ("T_MASTER_CORD.csv", "T_CARRIER_DECODE.csv")):
        if not stamp:
            continue
        try:
            with ZipFile(path) as archive:
                if archive.getinfo(member).file_size > 50_000_000:
                    continue
                with archive.open(member) as stream:
                    for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")):
                        if member == "T_CARRIER_DECODE.csv":
                            airlines[row["AIRLINE_ID"]] = row["UNIQUE_CARRIER_NAME"] or row["CARRIER_NAME"]
                        else:
                            try:
                                lon, lat = float(row["LONGITUDE"]), float(row["LATITUDE"])
                                if not (math.isfinite(lon) and math.isfinite(lat) and abs(lon) <= 180 and abs(lat) <= 90):
                                    continue
                            except (ValueError, TypeError):
                                continue
                            airports[row["AIRPORT_SEQ_ID"]] = {
                                "name": row["DISPLAY_AIRPORT_NAME"],
                                "city": row["DISPLAY_AIRPORT_CITY_NAME_FULL"] or None,
                                "city_market": row["DISPLAY_CITY_MARKET_NAME_FULL"] or None,
                                "coordinates": (lon, lat),
                            }
        except (OSError, BadZipFile, KeyError, UnicodeError):
            continue
    return airports, airlines
