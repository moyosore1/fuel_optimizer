from django.contrib import admin
from django.urls import include, path

API_PREFIX = "api/v1"

urlpatterns = [
    path("admin/", admin.site.urls),
    path(f"{API_PREFIX}/", include("fuel_optimizer.planner.urls")),
]
