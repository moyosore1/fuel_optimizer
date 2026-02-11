from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any

from stations.models import FuelStation
from stations.queries import find_stations_along_route


@dataclass(frozen=True)
class Waypoint:
    lat: float
    lng: float
    cumulative_miles: float


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two lat/lng points in miles."""
    R = 3958.7613  # Earth radius in miles
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def build_waypoints_from_linestring(linestring_geojson: dict, interval_miles: float = 50) -> list[Waypoint]:

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

    # Ensure destination included
    lng_last, lat_last = coords[-1]
    if waypoints[-1].lat != lat_last or waypoints[-1].lng != lng_last:
        waypoints.append(Waypoint(lat=lat_last, lng=lng_last, cumulative_miles=cum))

    return waypoints


def _stations_within_radius(
    lat: float, lng: float, radius_miles: float, stations: list[FuelStation]
) -> list[FuelStation]:

    out: list[FuelStation] = []
    for s in stations:
        if not s.location:
            continue
        d = haversine_miles(lat, lng, s.location.y, s.location.x)
        if d <= radius_miles:
            out.append(s)
    return out


def find_optimal_fuel_stops(
    route_linestring: dict,
    waypoint_interval: float = 50,
    station_radius: float = 25,
    corridor_width_miles: float = 8,
) -> dict[str, Any]:
    MAX_RANGE = 500
    MPG = 10

    waypoints = build_waypoints_from_linestring(route_linestring, interval_miles=waypoint_interval)
    if not waypoints:
        return {"stops": [], "totals": {"total_cost": 0.0, "total_gallons_bought": 0.0}}

    corridor_qs = find_stations_along_route(route_linestring, corridor_width_miles=corridor_width_miles)

    corridor_stations = list(corridor_qs)
    if not corridor_stations:
        return {
            "error": f"No stations found within {corridor_width_miles} miles of route. "
            "Try increasing corridor_width_miles or ensure stations are geocoded."
        }

    stations_near_waypoint: list[list[FuelStation]] = []
    for wp in waypoints:
        stations_near_waypoint.append(_stations_within_radius(wp.lat, wp.lng, station_radius, corridor_stations))

    tank_capacity_gallons = MAX_RANGE / MPG
    fuel_in_tank = tank_capacity_gallons

    total_miles = waypoints[-1].cumulative_miles
    prev_miles = 0.0

    stops: list[dict[str, Any]] = []
    total_cost = 0.0
    total_gallons_bought = 0.0

    def range_left_miles() -> float:
        return fuel_in_tank * MPG

    for i, wp in enumerate(waypoints):
        # Drive from previous waypoint -> this waypoint
        delta_miles = wp.cumulative_miles - prev_miles
        fuel_in_tank -= delta_miles / MPG
        prev_miles = wp.cumulative_miles

        if fuel_in_tank < -1e-6:
            return {"error": "Trip not feasible: ran out of fuel between waypoints / insufficient station coverage."}

        # If we can reach destination from here, done
        if (total_miles - wp.cumulative_miles) <= range_left_miles():
            break

        if range_left_miles() < 120:
            nearby = stations_near_waypoint[i]
            if not nearby:
                return {"error": f"No stations within {station_radius} miles near mile {wp.cumulative_miles:.1f}."}

            current_station = min(nearby, key=lambda s: s.retail_price)

            cheaper_miles_ahead = None
            lookahead_limit = wp.cumulative_miles + MAX_RANGE

            for j in range(i + 1, len(waypoints)):
                future_wp = waypoints[j]
                if future_wp.cumulative_miles > lookahead_limit:
                    break

                future_nearby = stations_near_waypoint[j]
                if not future_nearby:
                    continue

                future_best = min(future_nearby, key=lambda s: s.retail_price)
                if future_best.retail_price < current_station.retail_price:
                    cheaper_miles_ahead = future_wp.cumulative_miles - wp.cumulative_miles
                    break

            if cheaper_miles_ahead is not None:
                target_miles = cheaper_miles_ahead
                decision = "buy_to_reach_cheaper_ahead"
            else:
                target_miles = min(MAX_RANGE, total_miles - wp.cumulative_miles)
                decision = "fill_to_max_or_destination"

            gallons_needed_total = target_miles / MPG
            gallons_to_buy = max(0.0, gallons_needed_total - fuel_in_tank)
            gallons_to_buy = min(gallons_to_buy, tank_capacity_gallons - fuel_in_tank)

            if gallons_to_buy <= 1e-9:
                continue

            price = float(current_station.retail_price)
            cost = gallons_to_buy * price

            fuel_in_tank += gallons_to_buy
            total_cost += cost
            total_gallons_bought += gallons_to_buy

            stops.append(
                {
                    "station_id": current_station.id,
                    "station_name": current_station.name,
                    "station_address": current_station.address,
                    "station_city": current_station.city,
                    "station_state": current_station.state,
                    "price_per_gallon": price,
                    "decision_point_mile": round(wp.cumulative_miles, 2),
                    "gallons_bought": round(gallons_to_buy, 4),
                    "cost": round(cost, 2),
                    "decision": decision,
                    "latitude": current_station.lat,
                    "longitude": current_station.lng,
                }
            )

    return {
        "stops": stops,
        "totals": {
            "total_cost": round(total_cost, 2),
            "total_gallons_bought": round(total_gallons_bought, 4),
            "tank_capacity_gallons": round(tank_capacity_gallons, 4),
            "assumptions": {
                "max_range_miles": MAX_RANGE,
                "mpg": MPG,
                "waypoint_interval_miles": waypoint_interval,
                "station_radius_miles": station_radius,
                "corridor_width_miles": corridor_width_miles,
            },
        },
    }
