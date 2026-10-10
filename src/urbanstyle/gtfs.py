"""Public transport stops from a GTFS feed (any operator's static timetable, e.g. TransLink's): for each stop near a unit, its routes
and how many departures it has on a typical weekday, in all and in its busiest hour. A stop is tied to OSM's by its number (OSM `ref`
= GTFS `stop_code`), else by its position (parts.py). The feed is cached in data/gtfs/; the result is one json file per unit."""
import datetime
import json
import os
import tempfile
import time
import urllib.request
import zipfile

CACHE_DAYS = 7      # a feed fetched within this many days is used again


def fetch(url, path):
    """The feed at `url`, kept at `path` (downloaded again when older than CACHE_DAYS)."""
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > CACHE_DAYS * 86400:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return path


def weekday(cal):
    """A typical weekday the feed runs: the first Wednesday from today inside a calendar period, as YYYYMMDD."""
    d = datetime.date.today()
    for _ in range(60):
        if d.weekday() == 2 and any(s <= d.strftime("%Y%m%d") <= e for s, e in cal):
            return d.strftime("%Y%m%d")
        d += datetime.timedelta(days=1)
    return datetime.date.today().strftime("%Y%m%d")


def stops_near(feed, lon, lat, radius, out):
    """The stops within `radius` m of (lon, lat) with their routes and weekday departures, written to the json file `out`:
    {stop_code or stop_id: {stop_id, stop_code, name, lon, lat, wheelchair, routes, day, departures, peak_per_hour, peak_hour}}."""
    import duckdb
    dlat, dlon = radius / 111320, radius / (111320 * max(0.1, __import__("math").cos(__import__("math").radians(lat))))
    with tempfile.TemporaryDirectory() as d:
        z = zipfile.ZipFile(feed)
        names = [n for n in ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt") if n in z.namelist()]
        z.extractall(d, names)
        con = duckdb.connect()
        rd = lambda n: f"read_csv('{d}/{n}', header = true, all_varchar = true)"
        con.execute(f"""CREATE TABLE s AS SELECT * FROM {rd('stops.txt')} WHERE stop_lat::DOUBLE BETWEEN {lat - dlat} AND {lat + dlat}
                        AND stop_lon::DOUBLE BETWEEN {lon - dlon} AND {lon + dlon} AND coalesce(location_type, '0') IN ('0', '')""")
        cal = con.execute(f"SELECT start_date, end_date FROM {rd('calendar.txt')}").fetchall() if "calendar.txt" in names else []
        day = weekday(cal)
        dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][datetime.datetime.strptime(day, "%Y%m%d").weekday()]
        on = [f"SELECT service_id FROM {rd('calendar.txt')} WHERE {dow} = '1' AND '{day}' BETWEEN start_date AND end_date"] if cal else []
        if "calendar_dates.txt" in names:       # exceptions: 1 a service added that day, 2 removed
            on.append(f"SELECT service_id FROM {rd('calendar_dates.txt')} WHERE date = '{day}' AND exception_type = '1'")
            svc = f"(({' UNION '.join(on)}) EXCEPT SELECT service_id FROM {rd('calendar_dates.txt')} WHERE date = '{day}' AND exception_type = '2')"
        else:
            svc = f"({' UNION '.join(on)})"
        rows = con.execute(f"""
            WITH st AS (SELECT stop_id, trip_id, split_part(trim(departure_time), ':', 1)::INT AS h FROM {rd('stop_times.txt')}
                        WHERE stop_id IN (SELECT stop_id FROM s)),
                 tr AS (SELECT trip_id, route_id FROM {rd('trips.txt')} WHERE service_id IN {svc}),
                 dep AS (SELECT st.stop_id, st.h, r.route_short_name AS route FROM st JOIN tr USING (trip_id)
                         JOIN {rd('routes.txt')} r USING (route_id)),
                 per_h AS (SELECT stop_id, h, count(*) AS n FROM dep GROUP BY ALL)
            SELECT s.stop_id, s.stop_code, s.stop_name, s.stop_lon::DOUBLE, s.stop_lat::DOUBLE, s.wheelchair_boarding,
                   (SELECT list(DISTINCT route ORDER BY route) FROM dep WHERE dep.stop_id = s.stop_id),
                   (SELECT count(*) FROM dep WHERE dep.stop_id = s.stop_id),
                   (SELECT max(n) FROM per_h WHERE per_h.stop_id = s.stop_id),
                   (SELECT arg_max(h, n) FROM per_h WHERE per_h.stop_id = s.stop_id) FROM s""").fetchall()
    stops = {(code or sid): dict(stop_id=sid, stop_code=code, name=name, lon=x, lat=y, wheelchair={"1": "yes", "2": "no"}.get(wc),
                                 routes=routes or [], day=day, departures=n, peak_per_hour=peak, peak_hour=ph)
             for sid, code, name, x, y, wc, routes, n, peak, ph in rows}
    with open(out, "w") as f:
        json.dump(stops, f)
    return len(stops)


def describe(stop):
    """A stop's timetable in words: "routes 9, 99, 14; 410 departures on 2026-10-14, 32 in the busiest hour (8:00)"."""
    if not stop:
        return None
    day = f"{stop['day'][:4]}-{stop['day'][4:6]}-{stop['day'][6:]}" if stop.get("day") else "a weekday"
    names = [r.lstrip("0") or r for r in stop.get("routes") or []]        # TransLink pads its numbers: 009 is route 9
    rs = f"route{'s' if len(names) != 1 else ''} {', '.join(names)}" if names else "no routes that day"
    busy = f", {stop['peak_per_hour']} in the busiest hour ({stop['peak_hour']}:00)" if stop.get("peak_per_hour") else ""
    return f"{rs}; {stop.get('departures') or 0} departures on {day}{busy}"
