from django.db import models


# Create your models here.
class RouteCache(models.Model):
    route_hash = models.CharField(max_length=64, unique=True, db_index=True)
    start_location = models.CharField(max_length=255)
    end_location = models.CharField(max_length=255)
    route_geometry = models.JSONField()
    total_distance = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["route_hash"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.start_location} → {self.end_location}"
