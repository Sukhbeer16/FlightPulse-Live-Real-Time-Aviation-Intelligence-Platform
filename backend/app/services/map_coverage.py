"""Bounded route aggregation over the local BTS releases and exact airport keys."""

from collections import defaultdict
from datetime import date

import duckdb

from backend.app.config.settings import get_settings
from backend.app.services.dataset_reference import references
from backend.app.services.processed_historical import HistoricalParquetUnavailable, SOURCE_FILE


def coverage(*, page=1, page_size=100, city=None, airport=None, origin=None, destination=None, airline=None,
             flight_number=None, date_from: date | None = None, date_to: date | None = None,
             delayed=None):
    root = get_settings().data_directory / "processed"
    paths = [p for p in (root / "monthly" / SOURCE_FILE, root / "bts_ontime_2024_01.parquet") if p.is_file()]
    if not paths:
        raise HistoricalParquetUnavailable("No monthly BTS source is available")
    airports, _ = references()
    city_keys = [key for key, value in airports.items()
                 if city and (value.get("city") or "").casefold() == city.casefold()]
    if city and not city_keys:
        return {"flights": 0, "mapped_flights": 0, "airport_count": 0,
                "city_count": 0, "route_count": 0, "airports": [], "routes": [],
                "pagination": {"page": page, "page_size": page_size, "total": 0, "total_pages": 0}}
    parts = []
    params = []
    for path in paths:
        parts.append("""SELECT CAST(OriginAirportSeqID AS VARCHAR) origin_key,
            CAST(DestAirportSeqID AS VARCHAR) destination_key, Origin origin,
            Dest destination, Reporting_Airline airline,
            CAST(Flight_Number_Reporting_Airline AS VARCHAR) flight_number,
            FlightDate flight_date, ArrDelay arrival_delay
            FROM read_parquet(?)""")
        params.append(str(path))
    filters = []
    if airport:
        filters.append("(upper(origin)=upper(?) OR upper(destination)=upper(?))")
        params.extend((airport, airport))
    for clause, value in (("upper(origin)=upper(?)", origin),
                          ("upper(destination)=upper(?)", destination),
                          ("upper(airline)=upper(?)", airline),
                          ("flight_number=?", flight_number),
                          ("flight_date>=?", date_from), ("flight_date<=?", date_to),
                          ("(arrival_delay>15)=?", delayed)):
        if value is not None:
            filters.append(clause)
            params.append(value)
    if city_keys:
        placeholders = ",".join("?" for _ in city_keys)
        filters.append(f"(origin_key IN ({placeholders}) OR destination_key IN ({placeholders}))")
        params.extend(city_keys * 2)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    query = """SELECT origin_key, destination_key, origin, destination,
        count(*) flights, count(*) FILTER (WHERE arrival_delay>15) delayed,
        count(*) FILTER (WHERE arrival_delay IS NOT NULL) known_delay,
        avg(arrival_delay) FILTER (WHERE arrival_delay IS NOT NULL) mean_arrival_delay
        FROM (""" + " UNION ALL ".join(parts) + ") records" + where + " GROUP BY 1,2,3,4"
    try:
        with duckdb.connect(config={"threads": 2, "memory_limit": "256MB"}) as db:
            groups = db.execute(query, params).fetchall()
    except duckdb.Error as exc:
        raise HistoricalParquetUnavailable("Route coverage could not be queried") from exc
    airport_totals = defaultdict(lambda: [0, 0, 0])
    routes = []
    mapped_flights = 0
    for origin_key, destination_key, origin, destination, flights, delay_count, known, mean in groups:
        start, end = airports.get(origin_key), airports.get(destination_key)
        for key, code in ((origin_key, origin), (destination_key, destination)):
            airport_totals[(key, code)][0] += flights
            airport_totals[(key, code)][1] += delay_count
            airport_totals[(key, code)][2] += known
        if start and end:
            mapped_flights += flights
        routes.append({"origin": origin, "destination": destination,
                       "origin_name": start["name"] if start else None,
                       "destination_name": end["name"] if end else None,
                       "origin_city": start.get("city") if start else None,
                       "destination_city": end.get("city") if end else None,
                       "origin_coordinates": start["coordinates"] if start else None,
                       "destination_coordinates": end["coordinates"] if end else None,
                       "flights": flights, "delayed": delay_count, "known_delay": known,
                       "delay_percent": round(100 * delay_count / known, 2) if known else None,
                       "mean_arrival_delay": round(mean, 2) if mean is not None else None})
    routes.sort(key=lambda row: (-row["flights"], row["origin"] or "", row["destination"] or ""))
    airport_rows = []
    for (key, code), (flights, delay_count, known) in airport_totals.items():
        ref = airports.get(key)
        airport_rows.append({"code": code, "name": ref["name"] if ref else None,
                             "city": ref.get("city") if ref else None,
                             "coordinates": ref["coordinates"] if ref else None,
                             "flights": flights, "delay_percent": round(100 * delay_count / known, 2) if known else None})
    airport_rows.sort(key=lambda row: (-row["flights"], row["code"] or ""))
    cities = sorted({row["city"] for row in airport_rows if row["city"]})
    total_routes = len(routes)
    return {"flights": sum(row["flights"] for row in routes), "mapped_flights": mapped_flights,
            "airport_count": len(airport_rows), "city_count": len(cities), "route_count": total_routes,
            "cities": cities, "airports": airport_rows,
            "routes": routes[(page-1)*page_size:page*page_size],
            "pagination": {"page": page, "page_size": page_size, "total": total_routes,
                           "total_pages": (total_routes + page_size - 1) // page_size}}
