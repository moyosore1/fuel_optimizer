from django.urls import path

from .views import RouteOptimizeView

urlpatterns = [path("route/optimize", RouteOptimizeView.as_view(), name="optimize_route")]
