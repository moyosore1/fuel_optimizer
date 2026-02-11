import hashlib
import json
import os
from datetime import timedelta
from typing import Dict

from django.utils import timezone

import requests

from .models import RouteCache


class RoutingService:

    def __init__(self):
        self.api_key = os.getenv("OPEN_ROUTE_API_KEY")
        self.base_url = os.getenv("OPEN_ROUTE_BASE_URL")
        self.cache_ttl_days = 7

    def get_route(self, start: str, end: str):
        cache_key = self._generate_cache_key(start, end)
        cached_route = self._get_cached_route(cache_key)

        if cached_route:
            return {
                "geometry": cached_route.route_geometry,
                "total_distance": cached_route.total_distance,
                "cache_hit": True,
            }

        route_data = self._fetch_route_from_api(start, end)

        self._save_to_cache(cache_key, start, end, route_data)

        return {
            "geometry": route_data["geometry"],
            "total_distance": route_data["total_distance"],
            "cache_hit": False,
        }

    def _fetch_route_from_api(self, start: str, end: str):
        start_coords = self._geocode(start)
        end_coords = self._geocode(end)

        url = f"{self.base_url}/v2/directions/driving-car"

        headers = {"Authorization": self.api_key, "Content-Type": "application/json"}

        payload = {
            "coordinates": [start_coords, end_coords],
            "format": "geojson",
            "instructions": False,
            "geometry": True,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        route_feature = data["features"][0]
        geometry = route_feature["geometry"]  # GeoJSON LineString
        distance_meters = route_feature["properties"]["segments"][0]["distance"]
        distance_miles = distance_meters * 0.000621371

        return {"geometry": geometry, "total_distance": distance_miles}

    def _geocode(self, location: str):
        if "," in location and self._is_coordinate_pair(location):
            lat, lng = map(float, location.split(","))
            return [lng, lat]

        url = f"{self.base_url}/geocode/search"

        params = {
            "api_key": self.api_key,
            "text": location,
            "boundary.country": "US",
            "size": 1,
        }

        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()

        if not data["features"]:
            raise ValueError(f"Could not geocode location: {location}")

        coords = data["features"][0]["geometry"]["coordinates"]
        return coords

    def _generate_cache_key(self, start: str, end: str):
        route_data = json.dumps({"start": start.strip().lower(), "end": end.strip().lower()}, sort_keys=True)
        return hashlib.sha256(route_data.encode()).hexdigest()

    def _get_cached_route(self, cache_key: str):
        try:
            cached_route = RouteCache.objects.get(route_hash=cache_key)
            if (timezone.now() - cached_route.created_at) < timedelta(days=self.cache_ttl_days):
                return cached_route
            else:
                cached_route.delete()
                return None
        except RouteCache.DoesNotExist:
            return None

    def _is_coordinate_pair(self, text: str) -> bool:
        try:
            parts = text.split(",")
            if len(parts) != 2:
                return False
            lat, lng = map(float, parts)
            return -90 <= lat <= 90 and -180 <= lng <= 180
        except (ValueError, AttributeError):
            return False

    def _save_to_cache(self, cache_key: str, start: str, end: str, route_data: Dict):
        """Save route to cache"""
        RouteCache.objects.create(
            route_hash=cache_key,
            start_location=start,
            end_location=end,
            route_geometry=route_data["geometry"],
            total_distance=route_data["total_distance"],
        )
