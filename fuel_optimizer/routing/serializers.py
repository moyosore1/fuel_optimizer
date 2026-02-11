from rest_framework import serializers


class RouteOptimizeRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=255,
        help_text="Start location (e.g., 'San Francisco, CA' or '37.7749,-122.4194')",
    )
    end = serializers.CharField(
        max_length=255,
        help_text="End location (e.g., 'New York, NY' or '40.7128,-74.0060')",
    )
    # max_range = serializers.IntegerField(
    #     default=500,
    #     min_value=100,
    #     max_value=1000,
    #     help_text="Vehicle's maximum range in miles (default: 500)"
    # )
    # mpg = serializers.FloatField(
    #     default=10.0,
    #     min_value=1.0,
    #     max_value=100.0,
    #     help_text="Miles per gallon (default: 10)"
    # )
    # start_fuel_gallons = serializers.FloatField(
    #     default=0.0,
    #     min_value=0.0,
    #     help_text="Starting fuel in tank (default: 0 = empty, needs immediate fill)"
    # )


class StationSerializer(serializers.Serializer):
    station_id = serializers.IntegerField()
    station_name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    price_per_gallon = serializers.DecimalField(max_digits=6, decimal_places=5)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)


class FuelStopSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    station = StationSerializer()
    distance_from_start_miles = serializers.FloatField()
    gallons_bought = serializers.FloatField()
    cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    decision = serializers.CharField()


class RouteSummarySerializer(serializers.Serializer):
    total_distance_miles = serializers.FloatField()
    total_fuel_gallons = serializers.FloatField()
    total_fuel_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    number_of_stops = serializers.IntegerField()
    average_price_per_gallon = serializers.DecimalField(max_digits=6, decimal_places=5)


class RouteOptimizeResponseSerializer(serializers.Serializer):
    route = serializers.DictField(help_text="Route details including geometry")
    fuel_stops = FuelStopSerializer(many=True)
    summary = RouteSummarySerializer()
    computation_time_ms = serializers.IntegerField(help_text="Time taken to compute the route in milliseconds")
    cache_hit = serializers.BooleanField(help_text="Whether this route was retrieved from cache")
