import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuel_optimizer.stations.models import FuelStation


class Command(BaseCommand):
    help = "Load fuel prices from CSV into the database"  # noqa: A003

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to the CSV file")

        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing fuel station data before importing",
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to insert at once (default:1000)",
        )

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        clear_existing = options["clear"]
        batch_size = options["batch_size"]

        try:
            with open(csv_file, "r") as f:
                pass
        except FileNotFoundError:
            raise CommandError("CSV file not found")

        if clear_existing:
            self.stdout.write(self.style.WARNING("Clearing existing fuel station data..."))
            deleted_count = FuelStation.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} existing fuel stations"))

        self.stdout.write(self.style.SUCCESS("Starting CSV import..."))

        stations_to_create = []
        stations_to_update = []
        total_processed = 0
        total_created = 0
        total_updated = 0
        skipped_count = 0
        error_count = 0

        existing_opis_ids = set(FuelStation.objects.values_list("opis_id", flat=True))

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            # Validate CSV headers
            required_headers = {
                "OPIS Truckstop ID",
                "Truckstop Name",
                "Address",
                "City",
                "State",
                "Retail Price",
            }
            if not required_headers.issubset(set(reader.fieldnames)):
                raise CommandError(f"CSV missing required headers. Expected: {required_headers}")

            for row_num, row in enumerate(reader, start=2):
                try:
                    opis_id = int(row["OPIS Truckstop ID"])
                    name = row["Truckstop Name"].strip()
                    address = row["Address"].strip()
                    city = row["City"].strip()
                    state = row["State"].strip().upper()
                    retail_price = Decimal(row["Retail Price"])

                    # Basic validation
                    if not name or not city or not state:
                        self.stdout.write(self.style.WARNING(f"Row {row_num}: Skipping - missing required fields"))
                        skipped_count += 1
                        continue

                    if len(state) != 2:
                        self.stdout.write(self.style.WARNING(f'Row {row_num}: Invalid state code "{state}"'))
                        skipped_count += 1
                        continue

                    # Create station object (lat/lng will be None until geocoded)
                    station = FuelStation(
                        opis_id=opis_id,
                        name=name,
                        address=address,
                        city=city,
                        state=state,
                        retail_price=retail_price,
                    )

                    if opis_id in existing_opis_ids:
                        stations_to_update.append(station)
                    else:
                        stations_to_create.append(station)

                    total_processed += 1

                    # Progress indicator every 1000 rows
                    if total_processed % 1000 == 0:
                        self.stdout.write(f"Processed {total_processed} rows...")

                    # Bulk insert/update when batch size is reached
                    if len(stations_to_create) >= batch_size:
                        with transaction.atomic():
                            FuelStation.objects.bulk_create(stations_to_create, ignore_conflicts=True)
                        total_created += len(stations_to_create)
                        self.stdout.write(f"✓ Created batch of {len(stations_to_create)} stations")
                        stations_to_create = []

                    if len(stations_to_update) >= batch_size:
                        with transaction.atomic():
                            for station in stations_to_update:
                                FuelStation.objects.update_or_create(
                                    opis_id=station.opis_id,
                                    defaults={
                                        "name": station.name,
                                        "address": station.address,
                                        "city": station.city,
                                        "state": station.state,
                                        "retail_price": station.retail_price,
                                    },
                                )
                        total_updated += len(stations_to_update)
                        self.stdout.write(f"✓ Updated batch of {len(stations_to_update)} stations")
                        stations_to_update = []

                except (ValueError, KeyError, InvalidOperation) as e:
                    self.stdout.write(self.style.ERROR(f"Row {row_num}: Error - {str(e)}"))
                    error_count += 1
                    continue

            if stations_to_create:
                with transaction.atomic():
                    FuelStation.objects.bulk_create(stations_to_create, ignore_conflicts=True)
                total_created += len(stations_to_create)
                self.stdout.write(f"✓ Created final batch of {len(stations_to_create)} stations")

            if stations_to_update:
                with transaction.atomic():
                    for station in stations_to_update:
                        FuelStation.objects.update_or_create(
                            opis_id=station.opis_id,
                            defaults={
                                "name": station.name,
                                "address": station.address,
                                "city": station.city,
                                "state": station.state,
                                "retail_price": station.retail_price,
                            },
                        )
                total_updated += len(stations_to_update)
                self.stdout.write(f"✓ Updated final batch of {len(stations_to_update)} stations")

            total_in_db = FuelStation.objects.count()
            stations_without_coords = FuelStation.objects.filter(location__isnull=True).count()

            self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
            self.stdout.write(self.style.SUCCESS("IMPORT COMPLETE"))
            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(f"Total rows processed: {total_processed}")
            self.stdout.write(self.style.SUCCESS(f"✓ Created: {total_created}"))
            self.stdout.write(self.style.SUCCESS(f"✓ Updated: {total_updated}"))
            if skipped_count > 0:
                self.stdout.write(self.style.WARNING(f"Skipped: {skipped_count}"))
            if error_count > 0:
                self.stdout.write(self.style.ERROR(f"Errors: {error_count}"))
            self.stdout.write(f"Total stations in database: {total_in_db}")
            self.stdout.write(self.style.WARNING(f"Stations without coordinates: {stations_without_coords}"))

            if stations_without_coords > 0:
                self.stdout.write(self.style.WARNING('\n⚠ Run "python manage.py geocode_stations" to add coordinates'))
