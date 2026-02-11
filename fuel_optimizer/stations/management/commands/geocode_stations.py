# stations/management/commands/geocode_stations.py

import csv
import io
import re
import sys
from time import sleep

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

import requests
from stations.models import FuelStation


class Command(BaseCommand):
    help = "Geocode fuel station addresses using US Census Geocoder (batch) and fallback strategies"  # noqa: A003

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of stations to geocode in one Census API batch (max 10,000)",
        )
        parser.add_argument(
            "--state",
            type=str,
            help="Only geocode stations in specific state (e.g., CA, NY)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit total number of stations to process (for testing)",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Retry stations that previously failed geocoding",
        )
        parser.add_argument(
            "--max-attempts",
            type=int,
            default=3,
            help="Maximum geocoding attempts per station (default: 3)",
        )
        parser.add_argument(
            "--fallback-only",
            action="store_true",
            help="Skip batch processing, only use fallback strategies for failed stations",
        )

    def handle(self, *args, **options):
        batch_size = min(options["batch_size"], 10000)  # Census API limit
        state_filter = options["state"]
        limit = options["limit"]
        retry_failed = options["retry_failed"]
        max_attempts = options["max_attempts"]
        fallback_only = options["fallback_only"]

        # Build queryset
        queryset = FuelStation.objects.all()

        # Filter by geocode status
        if retry_failed:
            queryset = queryset.filter(geocode_status="failed", geocode_attempts__lt=max_attempts)
        else:
            queryset = queryset.filter(geocode_status="pending")

        if state_filter:
            state_filter = state_filter.upper()
            queryset = queryset.filter(state=state_filter)

        if limit:
            queryset = queryset[:limit]

        total_to_geocode = queryset.count()

        if total_to_geocode == 0:
            self.stdout.write(self.style.SUCCESS("✓ No stations to geocode"))
            return

        self.stdout.write(self.style.WARNING(f"Found {total_to_geocode} stations to geocode"))

        if not fallback_only:
            # Phase 1: Batch geocoding with US Census
            self.stdout.write(self.style.SUCCESS("\n📍 Phase 1: US Census Batch Geocoding\n"))
            self._batch_geocode_census(queryset, batch_size)

        # Phase 2: Fallback strategies for failed stations
        failed_stations = queryset.filter(geocode_status="failed", geocode_attempts__lt=max_attempts)
        failed_count = failed_stations.count()

        if failed_count > 0:
            self.stdout.write(self.style.WARNING(f"\n🔄 Phase 2: Fallback Geocoding ({failed_count} stations)\n"))
            self._fallback_geocode(failed_stations, max_attempts)

        # Final summary
        self._print_summary()

    def _batch_geocode_census(self, queryset, batch_size):
        """
        Geocode stations using US Census Geocoder batch API
        https://geocoding.geo.census.gov/geocoder/
        """
        stations = list(queryset)
        total = len(stations)

        self.stdout.write(f"Processing {total} stations in batches of {batch_size}...\n")

        for batch_num, i in enumerate(range(0, total, batch_size), start=1):
            batch = stations[i : i + batch_size]  # noqa: E203

            self.stdout.write(f"Batch {batch_num}: Processing {len(batch)} stations...")

            try:
                # Prepare batch CSV data
                csv_data = self._prepare_census_batch(batch)

                # Call Census API
                results = self._call_census_batch_api(csv_data)

                # Update stations with results
                success_count, failed_count = self._process_census_results(batch, results)

                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Success: {success_count}")
                    + " | "
                    + self.style.ERROR(f"✗ Failed: {failed_count}")
                )

                # Rate limiting - be nice to Census API
                if i + batch_size < total:
                    sleep(1)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Batch failed: {str(e)}"))
                # Mark all as failed with error
                self._mark_batch_failed(batch, str(e))

    def _prepare_census_batch(self, batch):
        """
        Prepare CSV data for Census batch geocoding
        Format: Unique ID, Street address, City, State, ZIP
        """
        output = io.StringIO()
        writer = csv.writer(output)

        for station in batch:
            # Use station ID as unique identifier
            # Census wants: ID, Street, City, State, ZIP
            writer.writerow(
                [
                    station.id,
                    station.address,
                    station.city,
                    station.state,
                    "",  # We don't have ZIP codes
                ]
            )

        return output.getvalue()

    def _call_census_batch_api(self, csv_data):
        """
        Call US Census Batch Geocoding API
        Returns dict mapping station_id -> (lat, lng)
        """
        url = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"

        files = {"addressFile": ("addresses.csv", csv_data, "text/csv")}

        data = {"benchmark": "Public_AR_Current", "vintage": "Current_Current"}

        response = requests.post(url, files=files, data=data, timeout=60)
        response.raise_for_status()

        # Parse results
        results = {}
        reader = csv.reader(io.StringIO(response.text))

        for row in reader:
            if len(row) >= 6:
                station_id = int(row[0])
                match_status = row[2]  # "Match", "No_Match", or "Tie"

                if match_status == "Match" and len(row) >= 6:
                    # Coordinates are in columns 5 (lng) and 6 (lat)
                    try:
                        lng = float(row[5])
                        lat = float(row[6])
                        results[station_id] = (lat, lng)
                    except (ValueError, IndexError):
                        pass

        return results

    def _process_census_results(self, batch, results):
        """Update stations with Census geocoding results"""
        success_count = 0
        failed_count = 0
        stations_to_update = []

        for station in batch:
            station.geocode_attempts += 1

            if station.id in results:
                lat, lng = results[station.id]
                station.location = Point(lng, lat, srid=4326)
                station.geocode_status = "success"
                station.geocode_last_error = None
                station.geocoded_at = timezone.now()
                success_count += 1
            else:
                station.geocode_status = "failed"
                station.geocode_last_error = "No match from Census Geocoder"
                failed_count += 1

            stations_to_update.append(station)

        # Bulk update
        with transaction.atomic():
            FuelStation.objects.bulk_update(
                stations_to_update,
                [
                    "location",
                    "geocode_status",
                    "geocode_attempts",
                    "geocode_last_error",
                    "geocoded_at",
                ],
                batch_size=100,
            )

        return success_count, failed_count

    def _mark_batch_failed(self, batch, error_message):
        """Mark entire batch as failed due to API error"""
        for station in batch:
            station.geocode_attempts += 1
            station.geocode_status = "failed"
            station.geocode_last_error = f"Batch API error: {error_message}"

        with transaction.atomic():
            FuelStation.objects.bulk_update(
                batch,
                ["geocode_attempts", "geocode_status", "geocode_last_error"],
                batch_size=100,
            )

    def _fallback_geocode(self, queryset, max_attempts):
        """
        Fallback geocoding strategies for failed stations
        Uses Nominatim with improved address cleaning
        """
        # from geopy.exc import GeocoderServiceError, GeocoderTimedOut
        from geopy.geocoders import Nominatim

        geolocator = Nominatim(user_agent="fuel_optimizer_fallback", timeout=10)

        total = queryset.count()
        success_count = 0
        failed_count = 0

        for idx, station in enumerate(queryset.iterator(), start=1):
            if station.geocode_attempts >= max_attempts:
                continue

            # Progress indicator
            if idx % 10 == 0:
                self.stdout.write(f"Progress: {idx}/{total} (✓ {success_count} | ✗ {failed_count})")

            try:
                lat, lng, strategy = self._geocode_with_strategies(geolocator, station)

                station.geocode_attempts += 1

                if lat and lng:
                    station.location = Point(lng, lat, srid=4326)
                    station.geocode_status = "success"
                    station.geocode_last_error = None
                    station.geocoded_at = timezone.now()
                    success_count += 1

                    if success_count <= 5:
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✓ {station.name}, {station.city}, {station.state} " f"({strategy})")
                        )
                else:
                    station.geocode_status = "failed"
                    station.geocode_last_error = "All fallback strategies failed"
                    failed_count += 1

                station.save()

                # Rate limiting for Nominatim
                sleep(1.1)

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\n\nInterrupted by user"))
                self._print_summary()
                sys.exit(0)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error: {str(e)}"))
                station.geocode_attempts += 1
                station.geocode_status = "failed"
                station.geocode_last_error = str(e)
                station.save()
                continue

        self.stdout.write(f"\nFallback complete: ✓ {success_count} | ✗ {failed_count}")

    def _geocode_with_strategies(self, geolocator, station):
        """
        Try multiple geocoding strategies in order
        Returns: (lat, lng, strategy_name) or (None, None, None)
        """
        from geopy.exc import GeocoderServiceError, GeocoderTimedOut

        # Strategy 1: Cleaned address (remove highway/exit markers)
        cleaned_address = self._clean_address(station.address)
        if cleaned_address != station.address:
            try:
                full_address = f"{cleaned_address}, {station.city}, {station.state}, USA"
                location = geolocator.geocode(full_address)
                if location:
                    return location.latitude, location.longitude, "cleaned_address"
            except (GeocoderTimedOut, GeocoderServiceError):
                pass

        # Strategy 2: City + State only
        try:
            city_state = f"{station.city}, {station.state}, USA"
            location = geolocator.geocode(city_state)
            if location:
                return location.latitude, location.longitude, "city_state"
        except (GeocoderTimedOut, GeocoderServiceError):
            pass

        return None, None, None

    def _clean_address(self, address):
        """
        Clean address by removing highway/exit markers

        Examples:
        "I-80, EXIT 123 & US-50" -> ""
        "EXIT 283 & US-69" -> ""
        "1234 Main St, EXIT 45" -> "1234 Main St"
        "I-95, MM 34" -> ""
        """
        # Patterns to remove
        patterns = [
            r"\bI-\d+\b",  # Interstate: I-80, I-95
            r"\bUS-\d+\b",  # US Highway: US-50, US-69
            r"\bSR-\d+\b",  # State Route: SR-85, SR-703
            r"\bCR-\d+\b",  # County Road: CR-138
            r"\bEXIT\s+\d+[A-Z]?\b",  # Exit: EXIT 123, EXIT 45A
            r"\bMM\s+\d+\b",  # Mile Marker: MM 34
            r"[,&\s]+",  # Multiple delimiters
        ]

        cleaned = address
        for pattern in patterns:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

        # Clean up whitespace and delimiters
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^[,&\s]+|[,&\s]+$", "", cleaned)

        # If nothing left after cleaning, return empty
        if len(cleaned) < 3:
            return ""

        return cleaned

    def _print_summary(self):
        """Print final summary statistics"""
        total = FuelStation.objects.count()
        success = FuelStation.objects.filter(geocode_status="success").count()
        failed = FuelStation.objects.filter(geocode_status="failed").count()
        pending = FuelStation.objects.filter(geocode_status="pending").count()

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("GEOCODING STATUS SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total stations: {total}")
        self.stdout.write(self.style.SUCCESS(f"✓ Success: {success} ({success / total * 100:.1f}%)"))

        if failed > 0:
            self.stdout.write(self.style.ERROR(f"✗ Failed: {failed} ({failed / total * 100:.1f}%)"))

            # Show attempt distribution for failed stations
            attempts_dist = {}
            for station in FuelStation.objects.filter(geocode_status="failed"):
                attempts_dist[station.geocode_attempts] = attempts_dist.get(station.geocode_attempts, 0) + 1

            if attempts_dist:
                self.stdout.write("\n  Failed stations by attempts:")
                for attempts, count in sorted(attempts_dist.items()):
                    self.stdout.write(f"    {attempts} attempts: {count} stations")

        if pending > 0:
            self.stdout.write(self.style.WARNING(f"⏳ Pending: {pending} ({pending / total * 100:.1f}%)"))

        # Common errors
        failed_stations = FuelStation.objects.filter(geocode_status="failed").exclude(geocode_last_error__isnull=True)
        if failed_stations.exists():
            self.stdout.write("\n  Common errors:")
            error_counts = {}
            for station in failed_stations[:100]:  # Sample first 100
                error = station.geocode_last_error[:50]  # First 50 chars
                error_counts[error] = error_counts.get(error, 0) + 1

            for error, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                self.stdout.write(f'    "{error}..." ({count}x)')
