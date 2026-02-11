# planner/views.py

import time
from decimal import Decimal

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.service import RoutingService

from .utils import find_optimal_fuel_stops


class RouteOptimizeView(APIView):

    def post(self, request):
        start_time = time.time()

        # Get request parameters
        start_location = request.data.get("start")
        end_location = request.data.get("end")

        if not start_location or not end_location:
            return Response(
                {"error": "Both start and end locations are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            routing_service = RoutingService()
            route_result = routing_service.get_route(start_location, end_location)

            route_geometry = route_result["geometry"]
            total_distance = route_result["total_distance"]
            cache_hit = route_result["cache_hit"]

            optimal_stops = find_optimal_fuel_stops(
                route_linestring=route_geometry,
                waypoint_interval=50,
                station_radius=25,
            )

            # Check for errors from optimization
            if optimal_stops and isinstance(optimal_stops[0], dict) and "error" in optimal_stops[0]:
                return Response(
                    {"error": optimal_stops[0]["error"]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Step 3: Format response
            formatted_stops = []
            total_cost = Decimal("0.00")
            total_gallons = 0.0

            for idx, stop in enumerate(optimal_stops, start=1):
                formatted_stops.append(
                    {
                        "order": idx,
                        "station": {
                            "station_id": stop["station_id"],
                            "station_name": stop["station_name"],
                            "address": stop["station_address"],
                            "city": stop["station_city"],
                            "state": stop["station_state"],
                            "price_per_gallon": stop["price_per_gallon"],
                            "latitude": stop["latitude"],
                            "longitude": stop["longitude"],
                        },
                        "distance_from_start_miles": round(stop["mile_marker"], 2),
                        "gallons_bought": stop["gallons_bought"],
                        "cost": Decimal(str(stop["cost"])),
                        "decision": stop["decision"],
                    }
                )

                total_cost += Decimal(str(stop["cost"]))
                total_gallons += stop["gallons_bought"]

            # Calculate summary
            avg_price = (total_cost / Decimal(str(total_gallons))) if total_gallons > 0 else Decimal("0.00")

            summary = {
                "total_distance_miles": round(total_distance, 2),
                "total_fuel_gallons": round(total_gallons, 2),
                "total_fuel_cost": round(total_cost, 2),
                "number_of_stops": len(optimal_stops),
                "average_price_per_gallon": round(avg_price, 5),
            }

            # Build response
            response_data = {
                "route": {
                    "start": start_location,
                    "end": end_location,
                    "total_distance_miles": round(total_distance, 2),
                    "geometry": route_geometry,
                },
                "fuel_stops": formatted_stops,
                "summary": summary,
                "computation_time_ms": int((time.time() - start_time) * 1000),
                "cache_hit": cache_hit,
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"Internal server error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
