from django.contrib.gis.db import models as gis_models
from django.db import models


# Create your models here.
class FuelStation(models.Model):
    opis_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=2, db_index=True)

    retail_price = models.DecimalField(max_digits=6, decimal_places=5)

    location = gis_models.PointField(geography=True, null=True, blank=True, srid=4326)

    GEOCODE_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]
    geocode_status = models.CharField(max_length=10, choices=GEOCODE_STATUS_CHOICES, default="pending", db_index=True)
    geocode_attempts = models.IntegerField(default=0)
    geocode_last_error = models.TextField(null=True, blank=True)
    geocoded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["state", "city"]),
            models.Index(fields=["geocode_status"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state}"

    @property
    def lat(self):
        return float(self.location.y) if self.location else None

    @property
    def lng(self):
        return float(self.location.x) if self.location else None

    @property
    def latitude(self):
        return self.lat

    @property
    def longitude(self):
        return self.lng
