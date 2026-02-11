from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from django.contrib.gis.geos import Point
from django.contrib.gis.geos.prepared import PreparedGeometry

from fuel_optimizer.stations.models import USState
from fuel_optimizer.stations.queries import get_cheapest_stations_by_states, get_states_for_route

MAX_RANGE_MILES = 500.0
MPG = 10.0
START_FUEL_GALLONS = 50.0

TANK_CAPACITY_GALLONS = MAX_RANGE_MILES / MPG


@dataclass(frozen=True)
class Waypoint:
    lat: float
    lng: float
    cumulative_miles: float


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.7613
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def build_waypoints_from_linestring(linestring_geojson: dict, interval_miles: float) -> list[Waypoint]:

    coords = linestring_geojson.get("coordinates") or []
    if len(coords) < 2:
        return []

    waypoints: list[Waypoint] = []
    cum = 0.0
    last_kept = 0.0

    lng0, lat0 = coords[0]
    waypoints.append(Waypoint(lat=lat0, lng=lng0, cumulative_miles=0.0))

    prev_lng, prev_lat = lng0, lat0

    for lng, lat in coords[1:]:
        seg = haversine_miles(prev_lat, prev_lng, lat, lng)
        cum += seg

        if (cum - last_kept) >= interval_miles:
            waypoints.append(Waypoint(lat=lat, lng=lng, cumulative_miles=cum))
            last_kept = cum

        prev_lng, prev_lat = lng, lat

    lng_last, lat_last = coords[-1]
    if waypoints[-1].lat != lat_last or waypoints[-1].lng != lng_last:
        waypoints.append(Waypoint(lat=lat_last, lng=lng_last, cumulative_miles=cum))

    return waypoints


def _load_prepared_states() -> list[tuple[str, PreparedGeometry]]:
    prepared: list[tuple[str, PreparedGeometry]] = []
    for st in USState.objects.all().only("code", "geom"):
        prepared.append((st.code.upper(), st.geom.prepared))
    return prepared


def _state_for_point(prepared_states: list[tuple[str, PreparedGeometry]], lat: float, lng: float) -> str | None:
    pt = Point(lng, lat, srid=4326)
    for code, prep in prepared_states:
        if prep.contains(pt):
            return code
    return None


def compute_fuel_plan(
    route_geometry: dict,
    *,
    waypoint_interval_miles: float = 50.0,
    reserve_miles: float = 120.0,
) -> dict:

    waypoints = build_waypoints_from_linestring(route_geometry, interval_miles=waypoint_interval_miles)
    if not waypoints:
        return {
            "states": [],
            "stops": [],
            "total_cost": 0.0,
            "total_gallons_bought": 0.0,
            "assumptions": _assumptions(waypoint_interval_miles, reserve_miles),
            "warnings": ["Route geometry had no coordinates."],
        }

    total_miles = waypoints[-1].cumulative_miles
    fuel_in_tank = min(START_FUEL_GALLONS, TANK_CAPACITY_GALLONS)

    states = get_states_for_route(route_geometry)

    cheapest_by_state = get_cheapest_stations_by_states(states)
    if not cheapest_by_state:
        return {
            "states": states,
            "stops": [],
            "total_cost": 0.0,
            "total_gallons_bought": 0.0,
            "assumptions": _assumptions(waypoint_interval_miles, reserve_miles),
            "warnings": ["No stations found for any state along the route."],
        }

    prepared_states = _load_prepared_states()
    wp_states: list[str | None] = [_state_for_point(prepared_states, wp.lat, wp.lng) for wp in waypoints]

    global_cheapest_station = min(cheapest_by_state.values(), key=lambda s: float(s.retail_price))

    def range_left_miles() -> float:
        return fuel_in_tank * MPG

    stops: list[dict] = []
    total_cost = 0.0
    total_gallons_bought = 0.0

    prev_miles = 0.0
    last_stop_station_id: int | None = None
    last_stop_mile: float | None = None

    for i, wp in enumerate(waypoints):
        delta = wp.cumulative_miles - prev_miles
        fuel_in_tank -= delta / MPG
        prev_miles = wp.cumulative_miles

        if fuel_in_tank < -1e-6:
            return {
                "states": states,
                "stops": stops,
                "total_cost": round(total_cost, 2),
                "total_gallons_bought": round(total_gallons_bought, 4),
                "assumptions": _assumptions(waypoint_interval_miles, reserve_miles),
                "warnings": ["Ran out of fuel before reaching destination (check station coverage / parameters)."],
            }

        remaining = total_miles - wp.cumulative_miles
        if remaining <= range_left_miles():
            break

        if range_left_miles() > reserve_miles:
            continue

        current_state = wp_states[i]
        current_station = cheapest_by_state.get(current_state) if current_state else None
        if current_station is None:
            current_station = global_cheapest_station
            current_state = current_station.state

        current_price = float(current_station.retail_price)

        if last_stop_mile is not None and (wp.cumulative_miles - last_stop_mile) < (waypoint_interval_miles * 0.5):
            continue

        lookahead_limit = wp.cumulative_miles + MAX_RANGE_MILES
        cheaper_found = None
        cheaper_miles_ahead = None

        for j in range(i + 1, len(waypoints)):
            future_wp = waypoints[j]
            if future_wp.cumulative_miles > lookahead_limit:
                break

            st = wp_states[j]
            if not st:
                continue

            st_station = cheapest_by_state.get(st)
            if not st_station:
                continue

            if float(st_station.retail_price) < current_price:
                cheaper_found = st_station
                cheaper_miles_ahead = future_wp.cumulative_miles - wp.cumulative_miles
                break

        if cheaper_found and cheaper_miles_ahead is not None:
            target_miles = cheaper_miles_ahead
            decision = "buy_to_reach_cheaper_state_ahead"
        else:
            target_miles = min(MAX_RANGE_MILES, remaining)
            decision = "fill_to_max_or_destination"

        gallons_needed_total = target_miles / MPG
        gallons_to_buy = max(0.0, gallons_needed_total - fuel_in_tank)
        gallons_to_buy = min(gallons_to_buy, TANK_CAPACITY_GALLONS - fuel_in_tank)

        if gallons_to_buy <= 1e-6:
            continue

        if last_stop_station_id is not None and current_station.id == last_stop_station_id:

            pass

        cost = gallons_to_buy * current_price
        fuel_in_tank += gallons_to_buy
        total_cost += cost
        total_gallons_bought += gallons_to_buy

        stops.append(
            {
                "mile_marker": round(wp.cumulative_miles, 2),
                "marker_latitude": wp.lat,
                "marker_longitude": wp.lng,
                "state_at_stop": current_state,
                "gallons_bought": round(gallons_to_buy, 4),
                "cost": round(cost, 2),
                "price_per_gallon": current_price,
                "decision": decision,
                "station": {
                    "id": current_station.id,
                    "opis_id": current_station.opis_id,
                    "name": current_station.name,
                    "address": current_station.address,
                    "city": current_station.city,
                    "state": current_station.state,
                },
                "note": "Stop marker is on route waypoint; station chosen as cheapest in that state.",
            }
        )

        last_stop_station_id = current_station.id
        last_stop_mile = wp.cumulative_miles

    return {
        "states": states,
        "stops": stops,
        "total_cost": round(total_cost, 2),
        "total_gallons_bought": round(total_gallons_bought, 4),
        "assumptions": _assumptions(waypoint_interval_miles, reserve_miles),
        "warnings": [
            "Many stations lack precise coordinates in source data; stop markers use route waypoint coordinates.",
        ],
    }


def _assumptions(waypoint_interval_miles: float, reserve_miles: float) -> dict:
    return {
        "max_range_miles": MAX_RANGE_MILES,
        "mpg": MPG,
        "start_fuel_gallons": START_FUEL_GALLONS,
        "tank_capacity_gallons": TANK_CAPACITY_GALLONS,
        "waypoint_interval_miles": waypoint_interval_miles,
        "reserve_miles": reserve_miles,
    }
