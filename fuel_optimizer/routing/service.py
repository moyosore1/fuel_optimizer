from __future__ import annotations

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
        self.api_key = os.getenv("OPEN_ROUTE_API_KEY", "").strip()
        self.base_url = os.getenv("OPEN_ROUTE_BASE_URL", "https://api.openrouteservice.org").rstrip("/")
        self.cache_ttl_days = 7

        if not self.api_key:
            raise RuntimeError("OPEN_ROUTE_API_KEY is missing")

    def get_route(self, start: str, end: str) -> dict:
        cache_key = self._generate_cache_key(start, end)
        cached = self._get_cached_route(cache_key)

        if cached:
            return {
                "geometry": cached.route_geometry,
                "total_distance": float(cached.total_distance),
                "cache_hit": True,
            }

        route_data = self._fetch_route_from_api(start, end)
        self._save_to_cache(cache_key, start, end, route_data)

        return {
            "geometry": route_data["geometry"],
            "total_distance": route_data["total_distance"],
            "cache_hit": False,
        }

    def _fetch_route_from_api(self, start: str, end: str) -> dict:
        start_coords = self._resolve_to_coords(start)  # [lng, lat]
        end_coords = self._resolve_to_coords(end)

        def call_directions(sc, ec):
            url = f"{self.base_url}/v2/directions/driving-car"
            params = {
                "api_key": self.api_key,
                "start": f"{sc[0]},{sc[1]}",
                "end": f"{ec[0]},{ec[1]}",
            }
            return requests.get(url, params=params, timeout=30)

        resp = call_directions(start_coords, end_coords)

        if resp.status_code >= 400:
            try:
                err = resp.json()
                msg = (err.get("error") or {}).get("message") or err.get("message") or ""
            except Exception:
                msg = resp.text or ""

            if "Could not find routable point" in msg:
                snapped = self._snap_to_network([start_coords, end_coords], radius_m=2000)
                if snapped and snapped[0]:
                    start_coords = snapped[0]
                if snapped and len(snapped) > 1 and snapped[1]:
                    end_coords = snapped[1]

                resp = call_directions(start_coords, end_coords)

        resp.raise_for_status()
        data = resp.json()

        feature = data["features"][0]
        geometry = feature["geometry"]

        props = feature.get("properties") or {}
        distance_meters = (props.get("summary") or {}).get("distance")
        if distance_meters is None and props.get("segments"):
            distance_meters = props["segments"][0].get("distance")
        if distance_meters is None:
            raise ValueError("Could not extract distance from ORS response")

        distance_miles = float(distance_meters) * 0.000621371
        return {"geometry": geometry, "total_distance": distance_miles}

    def _resolve_to_coords(self, location: str) -> list[float]:

        location = (location or "").strip()

        if self._is_coordinate_pair(location):
            lat, lng = map(float, location.split(","))
            return [lng, lat]

        return self._geocode(location)

    def _geocode(self, text: str) -> list[float]:
        url = f"{self.base_url}/geocode/search"
        params = {
            "api_key": self.api_key,
            "text": text,
            "boundary.country": "US",
            "size": 1,
        }

        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        feats = data.get("features") or []
        if not feats:
            raise ValueError(f"Could not geocode location: {text}")

        return feats[0]["geometry"]["coordinates"]

    def _generate_cache_key(self, start: str, end: str) -> str:
        route_data = json.dumps(
            {"start": start.strip().lower(), "end": end.strip().lower()},
            sort_keys=True,
        )
        return hashlib.sha256(route_data.encode()).hexdigest()

    def _get_cached_route(self, cache_key: str):
        try:
            cached = RouteCache.objects.get(route_hash=cache_key)
            if (timezone.now() - cached.created_at) < timedelta(days=self.cache_ttl_days):
                return cached
            cached.delete()
            return None
        except RouteCache.DoesNotExist:
            return None

    def _save_to_cache(self, cache_key: str, start: str, end: str, route_data: Dict):
        RouteCache.objects.create(
            route_hash=cache_key,
            start_location=start,
            end_location=end,
            route_geometry=route_data["geometry"],
            total_distance=route_data["total_distance"],
        )

    def _is_coordinate_pair(self, text: str) -> bool:
        try:
            parts = text.split(",")
            if len(parts) != 2:
                return False
            lat, lng = map(float, parts)
            return -90 <= lat <= 90 and -180 <= lng <= 180
        except (ValueError, AttributeError):
            return False

    def _snap_to_network(self, coords_list, radius_m=1000, profile="driving-car"):

        url = f"{self.base_url}/v2/snap/{profile}/json"

        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "locations": coords_list,
            "radius": radius_m,
            "id": "snap_request",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=30)

        if resp.status_code >= 400:
            raise ValueError(f"Snap failed: {resp.status_code} {resp.text}")

        data = resp.json()

        out = []
        for item in data.get("locations", []):
            if not item:
                out.append(None)
            else:
                out.append(item.get("location"))  # [lng, lat]
        return out
