import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import GooglePlaceReference
from core.places import INDIAN_STATES_AND_TERRITORIES, search_state_restaurants


class Command(BaseCommand):
    help = "Discover Google Place IDs for one state or all Indian states and union territories"

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument(
            "--state",
            choices=INDIAN_STATES_AND_TERRITORIES,
            help="Search one Indian state or union territory.",
        )
        selection.add_argument(
            "--all-states",
            action="store_true",
            help="Search all Indian states and union territories (up to five billable requests each).",
        )

    def handle(self, **options):
        api_key = settings.GOOGLE_PLACES_API_KEY
        if not api_key:
            raise CommandError("Set GOOGLE_PLACES_API_KEY before syncing Google Place IDs.")

        regions = (
            INDIAN_STATES_AND_TERRITORIES
            if options["all_states"]
            else (options["state"],)
        )
        for region in regions:
            try:
                places = search_state_restaurants(region, api_key)
            except requests.RequestException as exc:
                raise CommandError(
                    f"Google Places lookup failed for {region}. Check the API key, billing, "
                    "Places API access, and network."
                ) from exc

            saved = 0
            for place in places:
                place_id = place.get("id")
                if not place_id:
                    continue
                GooglePlaceReference.objects.update_or_create(
                    place_id=place_id,
                    region=region,
                    defaults={},
                )
                saved += 1

            self.stdout.write(
                f"{region}: stored {saved} place IDs. "
                "Google listing details were not stored."
            )
            if saved < 100:
                self.stdout.write(
                    self.style.WARNING(
                        f"{region}: Google returned fewer than 100 unique places; "
                        "the API does not guarantee a minimum."
                    )
                )

        self.stdout.write(self.style.SUCCESS("Place ID sync complete."))
