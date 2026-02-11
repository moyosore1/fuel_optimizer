from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import LineString
from django.contrib.gis.measure import D

from stations.models import FuelStation


def find_stations_along_route(route_linestring, corridor_width_miles=25):

    coords = route_linestring["coordinates"]
    line = LineString(coords, srid=4326)

    nearby_stations = (
        FuelStation.objects.filter(
            location__isnull=False,
            geocode_status="success",
            location__distance_lte=(line, D(mi=corridor_width_miles)),
        )
        .annotate(distance_from_route=Distance("location", line))
        .order_by("distance_from_route")
    )

    return nearby_stations
