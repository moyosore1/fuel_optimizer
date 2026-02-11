# stations/management/commands/load_us_states.py
import json

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand

from fuel_optimizer.stations.models import USState


class Command(BaseCommand):
    help = "Load US states from us.json into PostGIS"  # noqa: A003

    def add_arguments(self, parser):
        parser.add_argument("path", type=str)
        parser.add_argument("--clear", action="store_true")

    def handle(self, *args, **opts):
        path = opts["path"]
        clear = opts["clear"]

        if clear:
            USState.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared existing USState rows."))

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("features", [])
        if not features:
            self.stdout.write(self.style.ERROR("No features found in GeoJSON."))
            return

        created = updated = skipped = 0

        for feat in features:
            props = feat.get("properties") or {}
            geom_json = feat.get("geometry")

            code = (props.get("state_code") or "").strip().upper()
            name = (props.get("name") or "").strip()

            if not code or len(code) != 2 or not name or not geom_json:
                skipped += 1
                continue

            geos = GEOSGeometry(json.dumps(geom_json), srid=4326)

            if geos.geom_type == "Polygon":
                geos = MultiPolygon(geos)
            elif geos.geom_type != "MultiPolygon":
                skipped += 1
                continue

            obj, is_created = USState.objects.update_or_create(
                code=code,
                defaults={"name": name, "geom": geos},
            )

            created += int(is_created)
            updated += int(not is_created)

        self.stdout.write(self.style.SUCCESS(f"Done. created={created}, updated={updated}, skipped={skipped}"))
