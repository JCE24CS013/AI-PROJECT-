import json
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .ai import AIServiceError
from .forms import RouteSearchForm
from .models import (
    ChatConversation,
    ChatMessage,
    Destination,
    GooglePlaceReference,
    RegionalDishSuggestion,
    Restaurant,
    RestaurantOwnerProfile,
    RestaurantReview,
    SavedTrip,
    SignatureDish,
    TouristProfile,
)
from .places import (
    INDIAN_STATES_AND_TERRITORIES,
    search_restaurants_for_query,
)


class PortalAndTravelFlowTests(TestCase):
    def setUp(self):
        self.tourist = User.objects.create_user(
            username="tourist",
            email="tourist@example.com",
            password="Tourist-password-123",
        )
        TouristProfile.objects.create(user=self.tourist)
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="Owner-password-123",
        )
        RestaurantOwnerProfile.objects.create(user=self.owner)
        self.start = Destination.objects.create(
            name="Fort Kochi",
            category="culture",
            region="Kochi",
            latitude=9.9659,
            longitude=76.2413,
        )
        self.end = Destination.objects.create(
            name="Munnar",
            category="nature",
            region="Idukki",
            latitude=10.0889,
            longitude=77.0595,
        )
        self.restaurant = Restaurant.objects.create(
            owner=self.owner,
            name="Munnar Kitchen",
            address="Munnar",
            latitude=10.0889,
            longitude=77.0595,
            cuisine_type="Kerala",
            price_range="₹₹",
            status="approved",
        )
        SignatureDish.objects.create(
            restaurant=self.restaurant,
            name="Vegetable stew",
            description="Coconut milk and seasonal vegetables",
            price="180.00",
            vegetarian=True,
            specialty=True,
        )
        RestaurantReview.objects.create(
            restaurant=self.restaurant,
            reviewer=self.tourist,
            rating=5,
            comment="Great food",
            approved=True,
        )

    def test_tourist_registration_creates_user_and_redirects_to_login(self):
        response = self.client.post(
            reverse("tourist_register"),
            {
                "username": "newtraveler",
                "email": "newtraveler@example.com",
                "password1": "Long-passphrase-582!",
                "password2": "Long-passphrase-582!",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('login')}?role=tourist",
            fetch_redirect_response=False,
        )
        new_user = User.objects.get(username="newtraveler")
        self.assertTrue(new_user.check_password("Long-passphrase-582!"))
        self.assertEqual(new_user.tourist_profile.home_city, "")
        self.assertEqual(new_user.tourist_profile.preferred_interests, "")
        self.assertNotIn("_auth_user_id", self.client.session)
        login_response = self.client.get(response.url)
        self.assertContains(login_response, "Tourist sign in")
        self.assertContains(login_response, "Your account was created")

    def test_owner_registration_creates_owner_profile_and_logs_in(self):
        response = self.client.post(
            reverse("owner_register"),
            {
                "username": "newrestaurant",
                "email": "newrestaurant@example.com",
                "password1": "Long-passphrase-825!",
                "password2": "Long-passphrase-825!",
                "restaurant_name": "New Restaurant",
                "contact_number": "555-0142",
            },
        )

        self.assertRedirects(response, reverse("owner_dashboard"), fetch_redirect_response=False)
        new_user = User.objects.get(username="newrestaurant")
        self.assertEqual(new_user.owner_profile.restaurant_name, "New Restaurant")
        self.assertEqual(new_user.owner_profile.contact_number, "555-0142")
        self.assertEqual(int(self.client.session["_auth_user_id"]), new_user.pk)

    def test_saved_tourist_profile_displays_after_refresh_with_update_action(self):
        self.client.force_login(self.tourist)

        settings_response = self.client.get(reverse("profile_settings"))
        self.assertContains(settings_response, "Home city")
        self.assertNotContains(settings_response, "Restaurant name")

        response = self.client.post(
            reverse("profile_settings"),
            {
                "first_name": "Amrithdev",
                "last_name": "S",
                "email": "amrithdev@example.com",
                "home_city": "Palakkad",
                "preferred_interests": "Nature, food",
                "bio": "I enjoy exploring new places.",
            },
        )

        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amrithdev")
        self.assertContains(response, "amrithdev@example.com")
        self.assertContains(response, "Palakkad")
        self.assertContains(response, "Nature, food")
        self.assertContains(response, "I enjoy exploring new places.")
        self.assertContains(response, "Update Profile")
        self.assertContains(response, f'href="{reverse("profile")}"')

    def test_owner_profile_settings_only_show_owner_fields(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("profile_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Restaurant name")
        self.assertContains(response, "Contact number")
        self.assertNotContains(response, "Home city")
        self.assertNotContains(response, "Preferred interests")

    def test_registration_shows_password_errors_and_does_not_create_partial_user(self):
        response = self.client.post(
            reverse("tourist_register"),
            {
                "username": "weakpassword",
                "email": "weakpassword@example.com",
                "password1": "123",
                "password2": "123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "password")
        self.assertFalse(User.objects.filter(username="weakpassword").exists())

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.search_restaurants_for_query")
    def test_restaurant_search_uses_one_name_cuisine_or_city_query(self, mock_search):
        self.client.force_login(self.tourist)
        for query in ("Munnar Kitchen", "Kerala", "Munnar"):
            with self.subTest(query=query):
                response = self.client.get(reverse("restaurant_list"), {"q": query})
                self.assertEqual(response.status_code, 200)
                mock_search.assert_called_with(query, "test-google-key")

        self.assertContains(response, 'name="q"')
        self.assertContains(response, "Search by name, cuisine, or city")
        self.assertNotContains(response, 'name="cuisine"')
        self.assertNotContains(response, 'name="region"')
        self.assertNotContains(response, 'name="state"')
        self.assertEqual(mock_search.call_count, 3)

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.places.requests.post")
    def test_live_chat_restaurant_search_uses_one_places_request(self, mock_post):
        mock_post.return_value.json.return_value = {
            "places": [
                {
                    "id": "live-place-id",
                    "displayName": {"text": "Live restaurant"},
                    "formattedAddress": "Chennai, Tamil Nadu",
                    "rating": 4.5,
                }
            ]
        }

        results = search_restaurants_for_query(
            "restaurants in Chennai",
            "test-google-key",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Live restaurant")
        self.assertEqual(
            mock_post.call_args.kwargs["headers"]["X-Goog-Api-Key"],
            "test-google-key",
        )
        self.assertEqual(mock_post.call_args.kwargs["json"]["pageSize"], 10)

    def test_root_shows_tourist_login_only(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

        response = self.client.get(reverse("login"))
        self.assertContains(response, "Welcome, traveler")
        self.assertContains(response, "Plan a trip")
        self.assertContains(response, "Start your journey")
        self.assertNotContains(response, "Restaurant login")

        response = self.client.post(
            reverse("login"),
            {"role": "owner", "username": "tourist", "password": "Tourist-password-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "Restaurant login is no longer available")

        response = self.client.post(
            reverse("login"),
            {"role": "tourist", "username": "tourist", "password": "Tourist-password-123"},
        )
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome")
        self.assertContains(response, "Plan a trip")
        self.assertContains(response, "Explore destinations")
        self.assertContains(response, "Open travel assistant")

    def test_tourist_dashboard_shows_saved_trips_without_restaurant_recommendations(self):
        self.client.force_login(self.tourist)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saved Trips")
        self.assertContains(response, "Plan a Trip")
        self.assertNotContains(response, "Recommended Restaurants")
        self.assertNotIn("restaurants", response.context)

    def test_route_plan_can_be_saved_to_dashboard_and_cleared(self):
        self.client.force_login(self.tourist)

        route_response = self.client.post(
            reverse("route_planner"),
            {
                "start_location": self.start.name,
                "end_location": self.end.name,
                "days": 2,
                "interests": "nature",
            },
        )

        self.assertEqual(route_response.status_code, 200)
        self.assertContains(route_response, "Save this plan to dashboard")

        save_response = self.client.post(
            reverse("save_trip"),
            {
                "start_location": self.start.name,
                "end_location": self.end.name,
                "days": "2",
                "interests": "nature",
            },
        )

        self.assertRedirects(save_response, reverse("dashboard"), fetch_redirect_response=False)
        trip = SavedTrip.objects.get(tourist=self.tourist)
        self.assertEqual(trip.title, "Fort Kochi → Munnar")
        self.assertEqual(trip.notes, "2 days | Interests: nature")
        self.assertEqual(
            list(trip.stops.order_by("sequence").values_list("name", flat=True)),
            ["Fort Kochi", "Munnar"],
        )

        dashboard_response = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard_response, "Fort Kochi")
        self.assertContains(dashboard_response, "Munnar")
        self.assertContains(dashboard_response, "2 days | Interests: nature")
        self.assertContains(dashboard_response, "Clear plans")
        self.assertContains(
            dashboard_response,
            f'href="{reverse("route_planner")}?saved_trip={trip.pk}"',
        )

        saved_plan_response = self.client.get(
            reverse("route_planner"),
            {"saved_trip": trip.pk},
        )
        self.assertEqual(saved_plan_response.status_code, 200)
        self.assertEqual(saved_plan_response.context["route_info"]["start_location"], "Fort Kochi")
        self.assertEqual(saved_plan_response.context["route_info"]["end_location"], "Munnar")
        self.assertEqual(saved_plan_response.context["route_info"]["days"], 2)
        self.assertContains(saved_plan_response, "2-day plan: Fort Kochi to Munnar")

        other_tourist = User.objects.create_user(username="other_tourist")
        TouristProfile.objects.create(user=other_tourist)
        other_user_trip = SavedTrip.objects.create(tourist=other_tourist, title="Other user's trip")
        self.assertEqual(
            self.client.get(
                reverse("route_planner"),
                {"saved_trip": other_user_trip.pk},
            ).status_code,
            404,
        )
        clear_response = self.client.post(reverse("clear_saved_trips"))

        self.assertRedirects(clear_response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFalse(SavedTrip.objects.filter(tourist=self.tourist).exists())
        self.assertTrue(SavedTrip.objects.filter(pk=other_user_trip.pk).exists())

    def test_chatbot_save_trip_command_creates_dashboard_trip(self):
        self.client.force_login(self.tourist)

        response = self.client.post(
            reverse("chatbot"),
            {"prompt": "save the trip Fort Kochi to Munnar to dashboard"},
        )
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in response.streaming_content
        ]
        reply = "".join(event.get("text", "") for event in events if event["type"] == "token")
        trip = SavedTrip.objects.get(tourist=self.tourist)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Saved your 1-day trip", reply)
        self.assertEqual(trip.title, "Fort Kochi â†’ Munnar")
        self.assertEqual(
            list(trip.stops.order_by("sequence").values_list("name", flat=True)),
            ["Fort Kochi", "Munnar"],
        )

    def test_route_planner_compares_modes_and_finds_approved_nearby_food(self):
        self.client.force_login(self.tourist)
        self.assertNotIn("start_latitude", RouteSearchForm().fields)
        response = self.client.post(
            reverse("route_planner"),
            {
                "start_location": self.start.name,
                "end_location": self.end.name,
                "days": 2,
                "interests": "nature",
            },
        )

        self.assertEqual(response.status_code, 200)
        route_info = response.context["route_info"]
        self.assertEqual(route_info["recommended_mode"], "car")
        self.assertEqual(
            {option["mode"] for option in route_info["transport_options"]},
            {"bus", "car", "train", "plane"},
        )
        self.assertEqual(len(response.context["day_plan"]), 2)
        self.assertEqual(response.context["day_plan"][0]["destination"], self.start)
        self.assertEqual(response.context["day_plan"][-1]["destination"], self.end)
        self.assertEqual(
            [activity["time"] for activity in response.context["day_plan"][0]["activities"]],
            [
                "08:30 AM",
                "09:30 AM",
                "11:30 AM",
                "12:30 PM",
                "02:00 PM",
                "04:30 PM",
                "05:30 PM",
                "07:30 PM",
                "09:00 PM",
            ],
        )
        self.assertIn(self.restaurant, response.context["restaurants"])
        self.assertContains(response, "straight-line distance")
        self.assertContains(response, "Open route in Google Maps")
        self.assertContains(response, "origin=Fort%20Kochi")
        self.assertContains(response, "destination=Munnar")
        self.assertContains(response, "destination-pin-icon")
        self.assertContains(response, "server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map")
        self.assertContains(response, "Tiles &copy; Esri")
        self.assertNotContains(response, "tile.openstreetmap.org")
        self.assertNotContains(response, "World_Imagery")
        self.assertContains(response, "22.9734, 78.6569")
        self.assertContains(response, "Vegetable stew")

    def test_route_planner_page_loads_before_a_route_is_submitted(self):
        self.client.force_login(self.tourist)
        Restaurant.objects.create(
            owner=self.owner,
            name="Pending Kitchen",
            address="Munnar",
            status="pending",
        )
        Restaurant.objects.create(
            owner=self.owner,
            name="Demo Kitchen",
            address="Munnar",
            status="approved",
            is_demo=True,
        )

        response = self.client.get(reverse("route_planner"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["restaurants"]), [self.restaurant])

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.search_restaurants_for_query")
    def test_restaurant_search_shows_live_results_without_saving_listing_details(
        self,
        mock_search,
    ):
        mock_search.return_value = [
            {
                "id": "live-place-id",
                "name": "Live restaurant",
                "formattedAddress": "Kochi, Kerala",
                "rating": 4.7,
                "userRatingCount": 123,
                "googleMapsUri": "https://maps.google.com/?cid=123",
                "primaryTypeDisplayName": {"text": "Restaurant"},
            }
        ]
        self.client.force_login(self.tourist)

        response = self.client.get(
            reverse("restaurant_list"),
            {"q": "Kerala food in Kochi"},
        )

        self.assertEqual(response.status_code, 200)
        mock_search.assert_called_once_with(
            "Kerala food in Kochi",
            "test-google-key",
        )
        self.assertEqual(response.context["restaurants"][0]["name"], "Live restaurant")
        self.assertContains(response, "Google Maps")
        self.assertContains(response, "Open location in Google Maps")
        self.assertContains(response, 'class="alert alert-info mb-0"')
        self.assertContains(response, 'class="btn btn-outline-primary"')
        self.assertFalse(GooglePlaceReference.objects.exists())

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.search_restaurants_for_query")
    def test_restaurant_search_generates_google_maps_link_when_places_response_has_no_url(
        self,
        mock_search,
    ):
        mock_search.return_value = [
            {
                "id": "live-place-id",
                "name": "Live restaurant",
                "formattedAddress": "Kochi, Kerala",
                "rating": 4.7,
                "userRatingCount": 123,
                "primaryTypeDisplayName": {"text": "Restaurant"},
            }
        ]
        self.client.force_login(self.tourist)

        response = self.client.get(
            reverse("restaurant_list"),
            {"q": "Kerala food in Kochi"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.google.com/maps/search/")
        self.assertContains(response, "query=")
        self.assertContains(response, "Live restaurant")

    @override_settings(GOOGLE_PLACES_API_KEY="")
    def test_restaurant_search_explains_when_live_search_is_unconfigured(self):
        self.client.force_login(self.tourist)

        response = self.client.get(
            reverse("restaurant_list"),
            {"q": "restaurants in Kochi"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Live restaurant search is not configured")
        self.assertEqual(response.context["restaurants"], [])

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.search_restaurants_for_query")
    def test_restaurant_search_shows_local_catalog_matches_when_google_rejects_request(
        self,
        mock_search,
    ):
        catalog_owner = User.objects.create_user(
            username="restaurant_catalog_import",
            is_active=False,
        )
        catalog_restaurant = Restaurant.objects.create(
            owner=catalog_owner,
            name="Delhi Kitchen",
            address="Connaught Place, New Delhi, Delhi",
            region="Delhi",
            external_rating="4.80",
            status="pending",
        )
        response = requests.Response()
        response.status_code = 403
        mock_search.side_effect = requests.HTTPError(
            "403 Client Error",
            response=response,
        )
        self.client.force_login(self.tourist)

        result = self.client.get(reverse("restaurant_list"), {"q": "Delhi"})

        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "Google Places rejected the request (HTTP 403)")
        self.assertContains(result, "Imported matches for")
        self.assertContains(result, "Delhi Kitchen")
        self.assertContains(result, "Unverified listing")
        self.assertEqual(
            list(result.context["catalog_restaurants"]),
            [catalog_restaurant],
        )

    def test_route_planner_creates_one_day_plan_entry_per_requested_day(self):
        self.client.force_login(self.tourist)
        response = self.client.post(
            reverse("route_planner"),
            {
                "start_location": self.start.name,
                "end_location": self.end.name,
                "days": 8,
                "interests": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["day_plan"]), 8)
        self.assertEqual(response.context["day_plan"][0]["location"], self.start.name)
        self.assertEqual(response.context["day_plan"][-1]["location"], self.end.name)
        self.assertContains(response, "8-day plan")
        self.assertTrue(all(len(day["activities"]) == 9 for day in response.context["day_plan"]))

    def test_seed_data_adds_india_wide_places_idempotently(self):
        call_command("seed_data", verbosity=0)
        first_count = Destination.objects.count()
        dish_count = RegionalDishSuggestion.objects.count()
        call_command("seed_data", verbosity=0)

        self.assertEqual(Destination.objects.count(), first_count)
        self.assertEqual(RegionalDishSuggestion.objects.count(), dish_count)
        self.assertGreater(first_count, 100)
        self.assertGreaterEqual(dish_count, 100)
        self.assertGreaterEqual(
            Destination.objects.values("region").distinct().count(),
            36,
        )
        self.assertTrue(Destination.objects.filter(name="Taj Mahal").exists())
        self.assertTrue(Destination.objects.filter(name="Radhanagar Beach").exists())
        self.assertTrue(
            RegionalDishSuggestion.objects.filter(
                region="Kerala",
                name="Kerala sadya",
            ).exists()
        )

    def test_demo_restaurants_cover_every_state_and_are_browseable_idempotently(self):
        call_command("seed_demo_restaurants", verbosity=0)
        first_count = Restaurant.objects.filter(is_demo=True).count()
        call_command("seed_demo_restaurants", verbosity=0)

        self.assertEqual(first_count, len(INDIAN_STATES_AND_TERRITORIES))
        self.assertEqual(Restaurant.objects.filter(is_demo=True).count(), first_count)
        self.assertEqual(
            Restaurant.objects.filter(
                is_demo=True,
                signature_dishes__isnull=True,
            ).count(),
            0,
        )
        self.assertEqual(
            SignatureDish.objects.filter(
                restaurant__is_demo=True,
                price="199.00",
            ).count(),
            len(INDIAN_STATES_AND_TERRITORIES),
        )
        self.assertEqual(
            set(
                Restaurant.objects.filter(is_demo=True).values_list(
                    "address",
                    flat=True,
                )
            ),
            {
                f"Demo listing — {region}, India (not a real location)"
                for region in INDIAN_STATES_AND_TERRITORIES
            },
        )
        self.assertFalse(
            User.objects.get(username="demo_restaurant_examples").is_active
        )

        response = self.client.get(
            reverse("restaurant_list"),
            {"q": "Demo Kitchen — Kerala"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["restaurants"].values_list("name", flat=True)),
            ["Demo Kitchen — Kerala"],
        )
        self.assertContains(response, "Demo example — not a real restaurant")
        self.assertContains(response, "Kerala sadya")
        self.assertContains(response, "Example price only: ₹199.00")
        demo_restaurant = response.context["restaurants"].get()
        response = self.client.get(
            reverse("restaurant_detail", args=[demo_restaurant.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Example price only: ₹199.00")
        self.assertContains(response, "not a real restaurant")

        self.client.force_login(self.tourist)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["restaurants"]), 6)
        self.assertTrue(all(restaurant.is_demo for restaurant in response.context["restaurants"]))
        self.assertContains(response, "Search restaurants")
        self.assertContains(response, "View on Google Maps")

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.management.commands.sync_place_ids.search_state_restaurants")
    def test_place_id_sync_stores_only_place_ids(self, mock_search):
        mock_search.return_value = [
            {
                "id": "google-place-kerala-1",
                "name": "Live-only Restaurant Name",
                "rating": 4.8,
                "formattedAddress": "Live-only address",
            }
        ]

        call_command("sync_place_ids", state="Kerala", verbosity=0)

        reference = GooglePlaceReference.objects.get()
        self.assertEqual(reference.place_id, "google-place-kerala-1")
        self.assertEqual(reference.region, "Kerala")
        field_names = {field.name for field in GooglePlaceReference._meta.fields}
        self.assertNotIn("name", field_names)
        self.assertNotIn("address", field_names)
        self.assertNotIn("rating", field_names)

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.resolve_place_location")
    def test_route_planner_looks_up_locations_not_in_the_destination_catalog(self, mock_resolve):
        mock_resolve.side_effect = [
            {"latitude": 28.6139, "longitude": 77.2090},
        ]
        self.client.force_login(self.tourist)

        response = self.client.post(
            reverse("route_planner"),
            {
                "start_location": self.start.name,
                "end_location": "Delhi",
                "days": 8,
                "interests": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["day_plan"]), 8)
        self.assertEqual(response.context["route_info"]["transport_options"][0]["mode"], "bus")
        self.assertGreater(response.context["route_info"]["distance_km"], 1000)
        self.assertEqual(mock_resolve.call_count, 1)

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.resolve_place_location")
    def test_route_planner_explains_when_google_places_lookup_is_rejected(self, mock_resolve):
        mock_resolve.side_effect = requests.HTTPError("403 Client Error")
        self.client.force_login(self.tourist)

        response = self.client.post(
            reverse("route_planner"),
            {
                "start_location": self.start.name,
                "end_location": "Delhi",
                "days": 2,
                "interests": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Places API (New)")
        self.assertContains(response, "API key restrictions and billing")
        self.assertNotContains(response, "configure GOOGLE_PLACES_API_KEY")

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.search_restaurants_for_query")
    def test_chatbot_reads_restaurants_from_database_without_live_search(
        self,
        mock_places_search,
    ):
        RegionalDishSuggestion.objects.create(
            region="Kerala",
            name="Kerala sadya",
            description="A regional meal suggestion.",
        )
        self.client.force_login(self.tourist)

        response = self.client.post(
            reverse("chatbot"),
            {"prompt": "Find restaurants in Kerala"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in response.streaming_content
        ]
        mock_places_search.assert_not_called()
        reply = "".join(event.get("text", "") for event in events if event["type"] == "token")
        self.assertIn("Munnar Kitchen", reply)
        self.assertIn("Vegetable stew", reply)
        self.assertIn("Kerala sadya", reply)
        self.assertIn("not verified menu items", reply)
        self.assertIn("Would you like options in a specific city in Kerala", reply)

    @override_settings(GOOGLE_PLACES_API_KEY="")
    @patch("core.views.search_restaurants_for_query")
    def test_chatbot_offers_regional_food_when_database_has_no_restaurant_match(
        self,
        mock_places_search,
    ):
        call_command("seed_data", verbosity=0)
        self.client.force_login(self.tourist)

        response = self.client.post(
            reverse("chatbot"),
            {"prompt": "restaurant from rajasthan"},
        )

        self.assertEqual(response.status_code, 200)
        mock_places_search.assert_not_called()
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in response.streaming_content
        ]
        reply = "".join(event.get("text", "") for event in events if event["type"] == "token")
        self.assertIn("I could not find an approved restaurant", reply)
        self.assertIn("Dal baati churma", reply)
        self.assertIn("not verified menu items", reply)
        self.assertIn("Would you like options in a specific city in Rajasthan", reply)

    @override_settings(GOOGLE_PLACES_API_KEY="")
    @patch("core.views.search_restaurants_for_query")
    def test_chatbot_reads_approved_restaurant_details_from_database(
        self,
        mock_places_search,
    ):
        self.restaurant.opening_hours = "10:00 AM - 10:00 PM"
        self.restaurant.contact_number = "555-0100"
        self.restaurant.save(update_fields=["opening_hours", "contact_number"])
        self.client.force_login(self.tourist)

        response = self.client.post(
            reverse("chatbot"),
            {"prompt": "Tell me about Munnar Kitchen restaurant"},
        )

        self.assertEqual(response.status_code, 200)
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in response.streaming_content
        ]
        reply = "".join(event.get("text", "") for event in events if event["type"] == "token")
        self.assertIn("Munnar Kitchen", reply)
        self.assertIn("Vegetable stew", reply)
        self.assertIn("10:00 AM - 10:00 PM", reply)
        self.assertIn("555-0100", reply)
        completion = next(event for event in events if event["type"] == "done")
        self.assertEqual(
            completion["database_restaurants"][0]["map_url"],
            "https://www.google.com/maps/search/?api=1&query=Munnar+Kitchen%2C+Munnar",
        )
        self.assertNotIn("Google Maps link", reply)
        mock_places_search.assert_not_called()

    @override_settings(GOOGLE_PLACES_API_KEY="test-google-key")
    @patch("core.views.search_restaurants_for_query")
    def test_chatbot_uses_previous_restaurant_intent_for_city_follow_up(
        self,
        mock_places_search,
    ):
        Restaurant.objects.create(
            owner=self.owner,
            name="Delhi Garden Restaurant",
            address="Connaught Place, Delhi",
            region="Delhi",
            cuisine_type="North Indian",
            status="pending",
        )
        self.client.force_login(self.tourist)

        first_response = self.client.post(reverse("chatbot"), {"prompt": "suggest restaurants"})
        list(first_response.streaming_content)
        second_response = self.client.post(reverse("chatbot"), {"prompt": "Delhi"})
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in second_response.streaming_content
        ]
        reply = "".join(event.get("text", "") for event in events if event["type"] == "token")

        self.assertIn("Delhi Garden Restaurant", reply)
        self.assertIn("pending approval", reply)
        mock_places_search.assert_not_called()

    @override_settings(OPENROUTER_API_KEY="test-key", OPENROUTER_MODEL="test/model")
    @patch("core.views.stream_chat_completion")
    def test_chatbot_does_not_reuse_old_restaurant_intent_for_route_follow_up(
        self,
        mock_stream,
    ):
        mock_stream.side_effect = [
            iter(["I can help plan that route. Which places interest you?"]),
            iter(["Kerala has beaches, hill stations, and backwaters."]),
        ]
        self.client.force_login(self.tourist)

        first_response = self.client.post(
            reverse("chatbot"),
            {"prompt": "Plan a trip from Karnataka to Kerala"},
        )
        list(first_response.streaming_content)
        second_response = self.client.post(reverse("chatbot"), {"prompt": "Kerala"})
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in second_response.streaming_content
        ]

        self.assertEqual(mock_stream.call_count, 2)
        second_context = json.loads(
            mock_stream.call_args_list[1].args[0][1]["content"].removeprefix("Application data: ")
        )
        self.assertEqual(second_context["approved_restaurants"], [])
        self.assertNotIn("Approved restaurants from the app database", "".join(
            event.get("text", "") for event in events if event["type"] == "token"
        ))

    @override_settings(GROQ_API_KEY="test-key", GROQ_MODEL="test/model")
    @patch("core.views.stream_chat_completion")
    def test_chatbot_answers_short_follow_up_when_provider_fails(
        self,
        mock_stream,
    ):
        mock_stream.side_effect = [
            iter(["Which places in Kerala interest you?"]),
            AIServiceError("Temporary provider failure"),
        ]
        self.client.force_login(self.tourist)

        first_response = self.client.post(
            reverse("chatbot"),
            {"prompt": "Plan a trip to Kerala"},
        )
        list(first_response.streaming_content)
        second_response = self.client.post(reverse("chatbot"), {"prompt": "Kerala"})
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in second_response.streaming_content
        ]
        reply = "".join(event.get("text", "") for event in events if event["type"] == "token")

        self.assertTrue(any(event["type"] == "done" for event in events))
        self.assertFalse(any(event["type"] == "error" for event in events))
        self.assertIn("continue planning your trip in Kerala", reply)


    @override_settings(OPENROUTER_API_KEY="test-key", OPENROUTER_MODEL="test/model")
    @patch(
        "core.views.stream_chat_completion",
        side_effect=AIServiceError("OpenRouter rejected the API key. Check OPENROUTER_API_KEY in the backend environment."),
    )
    def test_chatbot_explains_openrouter_authentication_failure(self, _mock_stream):
        self.client.force_login(self.tourist)

        response = self.client.post(
            reverse("chatbot"),
            {"prompt": "How should I travel from Kochi to Delhi?"},
        )

        self.assertEqual(response.status_code, 200)
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in response.streaming_content
        ]
        self.assertIn("OpenRouter rejected the API key", next(event["message"] for event in events if event["type"] == "error"))
        self.assertTrue(
            ChatMessage.objects.filter(
                conversation__user=self.tourist,
                sender="bot",
                content__contains="OPENROUTER_API_KEY",
            ).exists()
        )

    @override_settings(OPENROUTER_API_KEY="test-key", OPENROUTER_MODEL="test/model")
    @patch("core.views.stream_chat_completion")
    def test_chatbot_uses_only_approved_restaurant_and_signature_dish_context(self, mock_stream):
        pending = Restaurant.objects.create(
            owner=self.owner,
            name="Not approved",
            address="Munnar",
            status="pending",
        )
        mock_stream.return_value = iter(["Try the vegetable stew."])

        self.client.force_login(self.tourist)
        response = self.client.post(reverse("chatbot"), {"prompt": "What local food can I try?"})

        self.assertEqual(response.status_code, 200)
        events = [
            json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
            for chunk in response.streaming_content
        ]
        reply = "".join(event.get("text", "") for event in events if event["type"] == "token")
        self.assertTrue(reply.startswith("Try the vegetable stew."))
        self.assertTrue(reply.endswith("Which region or dietary preference should I tailor the food suggestions to?"))
        payload = mock_stream.call_args.args[0]
        self.assertIn("exactly one useful, specific follow-up question", payload[0]["content"])
        data_message = payload[1]["content"]
        context = json.loads(data_message.removeprefix("Application data: "))
        restaurants = context["approved_restaurants"]
        self.assertEqual([restaurant["name"] for restaurant in restaurants], [self.restaurant.name])
        self.assertNotIn(pending.name, data_message)
        self.assertEqual(restaurants[0]["signature_dishes"][0]["name"], "Vegetable stew")
        self.assertEqual(restaurants[0]["rating"], 5)
        self.assertNotIn("api_key", payload)

    def test_owner_portal_does_not_show_or_allow_tourist_tools(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("owner_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Open AI chatbot")
        self.assertRedirects(
            self.client.get(reverse("route_planner")),
            reverse("home"),
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get(reverse("chatbot")),
            reverse("home"),
            fetch_redirect_response=False,
        )

    def test_tourist_chatbot_can_load_history_for_floating_widget(self):
        conversation = ChatConversation.objects.create(user=self.tourist, title="Trip chat")
        ChatMessage.objects.create(
            conversation=conversation,
            sender="user",
            content="Suggest a route",
        )
        ChatMessage.objects.create(
            conversation=conversation,
            sender="bot",
            content="What city are you visiting?",
        )
        self.client.force_login(self.tourist)
        session = self.client.session
        session["chat_conversation_id"] = conversation.pk
        session.save()

        response = self.client.get(reverse("chatbot"), {"floating": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["messages"],
            [
                {"sender": "user", "content": "Suggest a route"},
                {"sender": "bot", "content": "What city are you visiting?"},
            ],
        )
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, 'id="chatbot-panel"')
        self.assertContains(dashboard, 'aria-controls="chatbot-panel"')


class RestaurantCatalogImportTests(TestCase):
    def test_catalog_import_is_idempotent_and_keeps_external_ratings_separate(self):
        call_command("import_restaurant_catalog", verbosity=0)
        call_command("import_restaurant_catalog", verbosity=0)

        catalog = Restaurant.objects.filter(owner__username="restaurant_catalog_import")
        self.assertEqual(catalog.count(), 67)
        self.assertEqual(catalog.filter(status="pending").count(), 67)
        self.assertEqual(catalog.values("region").distinct().count(), 9)
        self.assertEqual(catalog.filter(external_rating__isnull=False).count(), 65)
        self.assertEqual(
            RestaurantReview.objects.filter(restaurant__in=catalog).count(),
            0,
        )
        self.assertTrue(
            catalog.filter(
                name="Rasnai Kochi",
                region="Kerala",
                external_rating="4.70",
            ).exists()
        )
