from __future__ import annotations

from django.contrib.gis.geos import LineString
from django.db.models import Count

from fuel_optimizer.stations.models import FuelStation, USState


def get_states_for_route(route_geometry: dict) -> list[str]:

    coords = route_geometry.get("coordinates") or []
    if len(coords) < 2:
        return []

    line = LineString(coords, srid=4326)

    return list(USState.objects.filter(geom__intersects=line).values_list("code", flat=True).order_by("code"))


def get_cheapest_stations_by_states(states: list[str]) -> dict[str, FuelStation]:

    if not states:
        return {}

    states = [s.upper() for s in states]

    qs = FuelStation.objects.filter(state__in=states).order_by("state", "retail_price").distinct("state")

    return {s.state.upper(): s for s in qs}


def get_station_count_by_state():
    return FuelStation.objects.values("state").annotate(count=Count("id")).order_by("-count")
