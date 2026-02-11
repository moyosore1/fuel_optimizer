from django.contrib import admin

from .models import FuelStation, USState

# Register your models here.
admin.site.register(FuelStation)
admin.site.register(USState)
