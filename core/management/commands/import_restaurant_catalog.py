import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Restaurant


DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "restaurant_catalog.csv"
CATALOG_USERNAME = "restaurant_catalog_import"


class Command(BaseCommand):
    help = "Import user-supplied restaurant listings from the restaurant catalog CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=Path,
            default=DEFAULT_CATALOG_PATH,
            help="CSV file to import (defaults to core/data/restaurant_catalog.csv).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Import every CSV row instead of the default verified catalog subset.",
        )

    def handle(self, *args, **options):
        path = options["file"]
        try:
            with path.open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
        except OSError as error:
            raise CommandError(f"Could not read restaurant catalog {path}: {error}") from error

        required_columns = {
            "name",
            "address",
            "region",
            "external_rating",
            "external_review_count",
        }
        if not rows or not required_columns.issubset(rows[0]):
            raise CommandError(
                "The CSV must contain rows and these columns: "
                + ", ".join(sorted(required_columns))
            )

        if not options["all"] and len(rows) > 67:
            rows = rows[:67]

        prepared_rows = []
        for line_number, row in enumerate(rows, start=2):
            name = row["name"].strip()
            address = row["address"].strip()
            region = row["region"].strip()
            if not name or not address or not region:
                raise CommandError(
                    f"CSV line {line_number} must include name, address, and region."
                )

            try:
                rating = Decimal(row["external_rating"]) if row["external_rating"].strip() else None
                review_count = (
                    int(row["external_review_count"])
                    if row["external_review_count"].strip()
                    else None
                )
            except (InvalidOperation, ValueError) as error:
                raise CommandError(
                    f"CSV line {line_number} has an invalid rating or review count."
                ) from error

            if rating is not None and not Decimal("0") <= rating <= Decimal("5"):
                raise CommandError(f"CSV line {line_number} rating must be between 0 and 5.")
            if review_count is not None and review_count < 0:
                raise CommandError(f"CSV line {line_number} review count cannot be negative.")

            prepared_rows.append(
                {
                    "name": name,
                    "address": address,
                    "region": region,
                    "external_rating": rating,
                    "external_review_count": review_count,
                }
            )

        with transaction.atomic():
            catalog_owner, created = User.objects.get_or_create(
                username=CATALOG_USERNAME,
                defaults={"email": "", "is_active": False},
            )
            if created:
                catalog_owner.set_unusable_password()
                catalog_owner.save(update_fields=["password"])

            created_count = 0
            updated_count = 0
            for row in prepared_rows:
                _, created = Restaurant.objects.update_or_create(
                    owner=catalog_owner,
                    name=row["name"],
                    address=row["address"],
                    defaults={
                        "description": "",
                        "region": row["region"],
                        "cuisine_type": "",
                        "status": "pending",
                        "is_demo": False,
                        "external_rating": row["external_rating"],
                        "external_review_count": row["external_review_count"],
                        "listing_source": "User-provided screenshot; unverified",
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(prepared_rows)} catalog listings "
                f"({created_count} created, {updated_count} refreshed)."
            )
        )
