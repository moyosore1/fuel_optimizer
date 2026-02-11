import time
from decimal import Decimal

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel_optimizer.planner.utils import compute_fuel_plan
from fuel_optimizer.routing.service import RoutingService


class RouteOptimizeView(APIView):

    def post(self, request):
        start_time = time.time()

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
            total_distance = float(route_result["total_distance"])
            cache_hit = bool(route_result["cache_hit"])

            plan = compute_fuel_plan(route_geometry)

            stops = plan.get("stops", [])
            states = plan.get("states", [])
            total_cost = Decimal(str(plan.get("total_cost", 0.0)))
            total_gallons = float(plan.get("total_gallons_bought", 0.0))

            avg_price = (total_cost / Decimal(str(total_gallons))) if total_gallons > 0 else Decimal("0.00")

            summary = {
                "total_distance_miles": round(total_distance, 2),
                "total_fuel_gallons_bought": round(total_gallons, 2),
                "total_fuel_cost": round(total_cost, 2),
                "number_of_stops": len(stops),
                "average_price_per_gallon": float(round(avg_price, 5)),
            }

            response_data = {
                "route": {
                    "start": start_location,
                    "end": end_location,
                    "total_distance_miles": round(total_distance, 2),
                    # "geometry": route_geometry,
                    "states_along_route": states,
                    "approach": "state boundaries via PostGIS + cheapest station per state",
                },
                "fuel_stops": [
                    {
                        "order": idx,
                        "mile_marker": s["mile_marker"],
                        "marker": {
                            "lat": s["marker_latitude"],
                            "lng": s["marker_longitude"],
                        },
                        "state_at_stop": s.get("state_at_stop"),
                        "gallons_bought": s["gallons_bought"],
                        "price_per_gallon": s["price_per_gallon"],
                        "cost": Decimal(str(s["cost"])),
                        "decision": s["decision"],
                        "station": s["station"],
                        "note": s.get("note"),
                    }
                    for idx, s in enumerate(stops, start=1)
                ],
                "summary": summary,
                "assumptions": plan.get("assumptions", {}),
                "warnings": plan.get("warnings", []),
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
