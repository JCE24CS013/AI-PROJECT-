import json
import logging
import math
import re
from urllib.parse import quote_plus

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .ai import AIServiceError, stream_chat_completion
from .forms import (
    OwnerSignUpForm,
    ProfileUpdateForm,
    RestaurantForm,
    ReviewForm,
    RouteSearchForm,
    SignatureDishForm,
    TouristSignUpForm,
)
from .models import (
    ChatConversation,
    ChatMessage,
    Destination,
    GooglePlaceReference,
    Restaurant,
    RestaurantOwnerProfile,
    RegionalDishSuggestion,
    SavedTrip,
    SignatureDish,
    TouristProfile,
    TripStop,
)
from .places import (
    INDIAN_STATES_AND_TERRITORIES,
    resolve_place_location,
    search_restaurants_for_query,
)

logger = logging.getLogger(__name__)


def home(request):
    if request.user.is_authenticated:
        if hasattr(request.user, "owner_profile"):
            return redirect("owner_dashboard")
        if request.user.is_staff:
            return redirect("admin_dashboard")
        if not _is_tourist(request.user):
            messages.error(request, "This account does not have a tourist or restaurant profile.")
            return redirect("login")
        destinations = Destination.objects.all()[:8]
        restaurants = Restaurant.objects.filter(status="approved", is_demo=True).order_by("region", "name")[:6]
        return render(
            request,
            "core/home.html",
            {"destinations": destinations, "restaurants": restaurants},
        )
    return redirect("login")


def _is_tourist(user):
    return TouristProfile.objects.filter(user=user).exists()


def _destination_for_location(location):
    return (
        Destination.objects.filter(Q(name__iexact=location) | Q(region__iexact=location))
        .order_by("name")
        .first()
    )


def _distance_km(start_latitude, start_longitude, end_latitude, end_longitude):
    earth_radius_km = 6371
    start_latitude, start_longitude, end_latitude, end_longitude = map(
        math.radians, (start_latitude, start_longitude, end_latitude, end_longitude)
    )
    latitude_delta = end_latitude - start_latitude
    longitude_delta = end_longitude - start_longitude
    arc = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(start_latitude)
        * math.cos(end_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    arc = min(1.0, max(0.0, arc))
    return earth_radius_km * 2 * math.atan2(math.sqrt(arc), math.sqrt(1 - arc))


def _build_day_plan(days, start_location, end_location, start_place, end_place, suggestions):
    middle_places = [
        place
        for place in suggestions
        if place.pk not in {getattr(start_place, "pk", None), getattr(end_place, "pk", None)}
    ]
    if start_place and end_place:
        route_distance = _distance_km(
            start_place.latitude,
            start_place.longitude,
            end_place.latitude,
            end_place.longitude,
        )
        corridor_places = []
        for place in middle_places:
            detour = (
                _distance_km(
                    start_place.latitude,
                    start_place.longitude,
                    place.latitude,
                    place.longitude,
                )
                + _distance_km(
                    place.latitude,
                    place.longitude,
                    end_place.latitude,
                    end_place.longitude,
                )
                - route_distance
            )
            if detour <= max(125, route_distance * 0.4):
                progress = _distance_km(
                    start_place.latitude,
                    start_place.longitude,
                    place.latitude,
                    place.longitude,
                )
                corridor_places.append((progress, place))
        middle_places = [
            place for _, place in sorted(corridor_places, key=lambda item: item[0])
        ]

    plan = []

    for day_number in range(1, days + 1):
        if days == 1:
            place = start_place or end_place
            location = f"{start_location} → {end_location}"
        elif day_number == 1:
            place = start_place
            location = start_location
        elif day_number == days:
            place = end_place
            location = end_location
        else:
            place_index = int(
                (day_number - 2) * len(middle_places) / max(1, days - 2)
            )
            place = middle_places[place_index] if place_index < len(middle_places) else None
            location = place.region if place else "Flexible day"

        nearby_place = None
        if place:
            nearby_place = next(
                (
                    candidate
                    for candidate in middle_places
                    if candidate.pk != place.pk
                    and _distance_km(
                        place.latitude,
                        place.longitude,
                        candidate.latitude,
                        candidate.longitude,
                    ) <= 35
                ),
                None,
            )
            main_activity = place.description or f"Explore {place.name} in {place.region}."
            hours_note = (
                f" Listed visiting hours: {place.visit_hours}; confirm before travel."
                if place.visit_hours
                else " Check current opening hours and access before setting out."
            )
        else:
            main_activity = (
                f"Travel onward from {start_location} toward {end_location}, "
                "or choose a nearby destination from the suggestions."
            )
            hours_note = " Confirm current opening hours, travel time, and access locally."

        second_activity = (
            f"Visit {nearby_place.name}; {nearby_place.description}"
            if nearby_place
            else f"Explore more of {place.region if place else 'the area'} at a nearby "
            "attraction that matches your interests."
        )
        activities = [
            {
                "time": "08:30 AM",
                "title": "Coffee & breakfast",
                "details": "Start at a nearby cafe and try a regional breakfast.",
                "tip": "Check the cafe's current hours before you go.",
            },
            {
                "time": "09:30 AM",
                "title": place.name if place else "Main attraction",
                "details": f"{main_activity}{hours_note} Allow about two hours where appropriate.",
                "tip": "Carry water and check local conditions, especially for outdoor sites.",
            },
            {
                "time": "11:30 AM",
                "title": "Walk or local transit",
                "details": (
                    f"Continue toward {nearby_place.name}."
                    if nearby_place
                    else "Head to a second stop in the same area; check local transit or walking routes."
                ),
                "tip": "Allow extra time for traffic and site entry.",
            },
            {
                "time": "12:30 PM",
                "title": "Lunch break",
                "details": "Choose a restaurant near your afternoon stop; review its menu and opening hours.",
                "tip": "App-listed dishes are provided by restaurant owners and may change.",
            },
            {
                "time": "02:00 PM",
                "title": "Afternoon activity",
                "details": second_activity,
                "tip": "Keep a shaded or indoor alternative in mind in warm or wet weather.",
            },
            {
                "time": "04:30 PM",
                "title": "Leisure & coffee break",
                "details": "Take a rest at a nearby cafe or tea house and leave time to recharge.",
                "tip": "Confirm the venue is open before walking over.",
            },
            {
                "time": "05:30 PM",
                "title": "Shopping or neighborhood stroll",
                "details": "Browse local craft shops or take a relaxed walk if nearby venues are open.",
                "tip": "Check market hours and local guidance.",
            },
            {
                "time": "07:30 PM",
                "title": "Dinner",
                "details": "Pick an approved restaurant nearby and try a regional dish listed on its profile.",
                "tip": "Confirm today's opening hours and transport back.",
            },
            {
                "time": "09:00 PM",
                "title": "Evening walk & return",
                "details": "Take a short, well-lit walk if appropriate, then return to your accommodation.",
                "tip": "Follow current local safety advice and arrange your return transport.",
            },
        ]
        plan.append(
            {
                "number": day_number,
                "location": location,
                "destination": place,
                "activities": activities,
            }
        )
    return plan


def login_view(request):
    role = request.POST.get("role", request.GET.get("role", ""))
    if role not in {"", "tourist", "owner"}:
        role = ""
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        if role == "owner":
            messages.error(request, "Restaurant login is no longer available. Please sign in as a tourist.")
            return render(request, "core/login.html", {"role": "tourist"})

        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_staff:
                login(request, user)
                return redirect("admin_dashboard")
            if not hasattr(user, "tourist_profile"):
                messages.error(request, "This account is not registered as a tourist.")
                return render(request, "core/login.html", {"role": role})
            login(request, user)
            return redirect("home")
        messages.error(request, "Invalid username or password.")
    return render(request, "core/login.html", {"role": role})


@login_required
def logout_view(request):
    logout(request)
    return redirect("home")


def tourist_register(request):
    if request.method == "POST":
        form = TouristSignUpForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
                TouristProfile.objects.create(user=user)
            messages.success(request, "Your account was created. Please sign in to continue.")
            return redirect(f"{reverse('login')}?role=tourist")
    else:
        form = TouristSignUpForm()
    return render(request, "core/register_tourist.html", {"form": form})


def owner_register(request):
    if request.method == "POST":
        form = OwnerSignUpForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
                RestaurantOwnerProfile.objects.create(
                    user=user,
                    restaurant_name=form.cleaned_data["restaurant_name"],
                    contact_number=form.cleaned_data["contact_number"],
                )
            login(request, user)
            return redirect("owner_dashboard")
    else:
        form = OwnerSignUpForm()
    return render(request, "core/register_owner.html", {"form": form})


@login_required
def profile_view(request):
    if getattr(request.user, "owner_profile", None):
        profile = request.user.owner_profile
        context = {"profile": profile}
        return render(request, "core/owner_profile.html", context)
    if getattr(request.user, "tourist_profile", None):
        profile = request.user.tourist_profile
        context = {"profile": profile}
        return render(request, "core/tourist_profile.html", context)
    return redirect("home")


@login_required
def profile_settings(request):
    user = request.user
    tourist_profile = getattr(user, "tourist_profile", None)
    owner_profile = getattr(user, "owner_profile", None)

    initial = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "bio": (owner_profile.bio if owner_profile else tourist_profile.bio) if (owner_profile or tourist_profile) else "",
    }
    if tourist_profile:
        initial.update({
            "home_city": tourist_profile.home_city,
            "preferred_interests": tourist_profile.preferred_interests,
        })
    if owner_profile:
        initial.update({
            "restaurant_name": owner_profile.restaurant_name,
            "contact_number": owner_profile.contact_number,
        })

    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, initial=initial)
        if form.is_valid():
            user.first_name = form.cleaned_data.get("first_name", "")
            user.last_name = form.cleaned_data.get("last_name", "")
            user.email = form.cleaned_data.get("email", user.email)
            user.save()

            if tourist_profile:
                tourist_profile.home_city = form.cleaned_data.get("home_city", "")
                tourist_profile.preferred_interests = form.cleaned_data.get("preferred_interests", "")
                tourist_profile.bio = form.cleaned_data.get("bio", "")
                tourist_profile.save()
            if owner_profile:
                owner_profile.restaurant_name = form.cleaned_data.get("restaurant_name", owner_profile.restaurant_name)
                owner_profile.contact_number = form.cleaned_data.get("contact_number", owner_profile.contact_number)
                owner_profile.bio = form.cleaned_data.get("bio", "")
                owner_profile.save()

            messages.success(request, "Profile updated successfully.")
            return redirect("profile")
    else:
        form = ProfileUpdateForm(initial=initial)

    return render(
        request,
        "core/profile_settings.html",
        {
            "form": form,
            "profile": owner_profile or tourist_profile,
            "is_tourist": bool(tourist_profile),
            "is_owner": bool(owner_profile),
        },
    )


@login_required
def change_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, "Password changed successfully.")
            return redirect("profile")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, "core/change_password.html", {"form": form})


def password_reset_request(request):
    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            User.objects.filter(email=email).exists()
            messages.success(request, "If an account exists for that email, a password reset link has been sent.")
            return redirect("password_reset_done")
    else:
        form = PasswordResetForm()
    return render(request, "core/password_reset_request.html", {"form": form})


def password_reset_done(request):
    return render(request, "core/password_reset_done.html")


@login_required
def dashboard(request):
    if not _is_tourist(request.user):
        return redirect("owner_dashboard" if hasattr(request.user, "owner_profile") else "home")
    trips = (
        SavedTrip.objects.filter(tourist=request.user)
        .prefetch_related("stops")
        .order_by("-created_at")
    )
    context = {"trips": trips}
    return render(request, "core/tourist_dashboard.html", context)


@login_required
def owner_dashboard(request):
    if not getattr(request.user, "owner_profile", None):
        messages.error(request, "Access denied.")
        return redirect("home")
    restaurants = Restaurant.objects.filter(owner=request.user).order_by("-created_at")
    return render(request, "core/owner_dashboard.html", {"restaurants": restaurants})


@login_required
def owner_restaurant_form(request, pk=None):
    if not getattr(request.user, "owner_profile", None):
        return redirect("home")
    restaurant = Restaurant.objects.filter(pk=pk, owner=request.user).first() if pk else None
    if request.method == "POST":
        form = RestaurantForm(request.POST, request.FILES, instance=restaurant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.owner = request.user
            if obj.pk is None:
                obj.status = "pending"
                messages.success(request, "Restaurant saved and sent for review.")
            else:
                messages.success(request, "Restaurant updated successfully.")
            obj.save()
            return redirect("owner_dashboard")
    else:
        form = RestaurantForm(instance=restaurant)
    return render(request, "core/owner_restaurant_form.html", {"form": form, "restaurant": restaurant})


@login_required
def owner_dish_form(request, restaurant_id, pk=None):
    restaurant = Restaurant.objects.filter(pk=restaurant_id, owner=request.user).first()
    if not restaurant:
        return redirect("owner_dashboard")
    dish = SignatureDish.objects.filter(pk=pk, restaurant=restaurant).first() if pk else None
    if request.method == "POST":
        form = SignatureDishForm(request.POST, request.FILES, instance=dish)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.restaurant = restaurant
            obj.save()
            messages.success(request, "Signature dish saved.")
            return redirect("owner_dashboard")
    else:
        form = SignatureDishForm(instance=dish)
    return render(request, "core/owner_dish_form.html", {"form": form, "restaurant": restaurant, "dish": dish})


@require_POST
@login_required
def delete_dish(request, restaurant_id, pk):
    restaurant = Restaurant.objects.filter(pk=restaurant_id, owner=request.user).first()
    if not restaurant:
        return redirect("owner_dashboard")
    dish = SignatureDish.objects.filter(pk=pk, restaurant=restaurant).first()
    if dish:
        dish.delete()
        messages.success(request, "Dish deleted.")
    return redirect("owner_dashboard")


@login_required
def route_planner(request):
    if not _is_tourist(request.user):
        messages.error(request, "The route planner is available to tourist accounts.")
        return redirect("home")
    if request.method == "POST":
        form = RouteSearchForm(request.POST)
    elif request.GET.get("saved_trip"):
        saved_trip_id = request.GET["saved_trip"]
        if not saved_trip_id.isdecimal():
            raise Http404
        trip = get_object_or_404(
            SavedTrip.objects.prefetch_related("stops"),
            pk=saved_trip_id,
            tourist=request.user,
        )
        stops = list(trip.stops.order_by("sequence"))
        notes_parts = trip.notes.split(" | Interests: ", 1)
        days_match = re.match(r"^(\d+)\s+days?$", notes_parts[0])
        form_data = {
            "start_location": stops[0].name if stops else "",
            "end_location": stops[-1].name if len(stops) > 1 else "",
            "days": days_match.group(1) if days_match else "",
            "interests": notes_parts[1] if len(notes_parts) > 1 else "",
        }
        form = RouteSearchForm(form_data)
    else:
        form = RouteSearchForm()
    destinations = Destination.objects.all()
    restaurants = Restaurant.objects.filter(status="approved", is_demo=False)

    if form.is_bound and form.is_valid():
        interests = [item.strip() for item in form.cleaned_data.get("interests", "").split(",") if item.strip()]
        if not interests:
            interests = ["culture", "nature", "history"]
        interest_query = Q(category__in=interests)
        for interest in interests:
            interest_query |= Q(best_for__icontains=interest)
        for location_term in (form.cleaned_data["start_location"], form.cleaned_data["end_location"]):
            if len(location_term) >= 3:
                interest_query |= (
                    Q(name__icontains=location_term)
                    | Q(region__icontains=location_term)
                )
        matches = list(Destination.objects.filter(interest_query).distinct())
        if not matches:
            matches = list(Destination.objects.all())

        start_location = form.cleaned_data["start_location"]
        end_location = form.cleaned_data["end_location"]
        start_place = _destination_for_location(start_location)
        end_place = _destination_for_location(end_location)
        start_latitude = start_place.latitude if start_place else None
        start_longitude = start_place.longitude if start_place else None
        end_latitude = end_place.latitude if end_place else None
        end_longitude = end_place.longitude if end_place else None
        location_lookup_failed = False
        if settings.GOOGLE_PLACES_API_KEY:
            try:
                if start_place is None:
                    start_coordinates = resolve_place_location(
                        start_location, settings.GOOGLE_PLACES_API_KEY
                    )
                    if start_coordinates:
                        start_latitude = start_coordinates.get("latitude")
                        start_longitude = start_coordinates.get("longitude")
                if end_place is None:
                    end_coordinates = resolve_place_location(
                        end_location, settings.GOOGLE_PLACES_API_KEY
                    )
                    if end_coordinates:
                        end_latitude = end_coordinates.get("latitude")
                        end_longitude = end_coordinates.get("longitude")
            except requests.RequestException:
                location_lookup_failed = True
                logger.exception("Google Places location lookup failed for route request")
                messages.warning(
                    request,
                    "Google Places could not look up the locations. Check that Places API (New) is enabled "
                    "for your Google Cloud project and that the API key restrictions and billing are configured.",
                )
        route_destinations = list(matches)
        for endpoint in (start_place, end_place):
            if endpoint and endpoint not in route_destinations:
                route_destinations.append(endpoint)
        day_plan = _build_day_plan(
            form.cleaned_data["days"],
            start_location,
            end_location,
            start_place,
            end_place,
            route_destinations,
        )
        route_destinations = route_destinations[:40]

        route_info = {
            "start_location": start_location,
            "end_location": end_location,
            "days": form.cleaned_data["days"],
            "start_coordinates": [start_latitude, start_longitude] if start_latitude is not None else None,
            "end_coordinates": [end_latitude, end_longitude] if end_latitude is not None else None,
            "transport_options": [],
        }
        if start_latitude is not None and end_latitude is not None:
            distance = _distance_km(start_latitude, start_longitude, end_latitude, end_longitude)
            recommended_mode = "car" if distance < 150 else "train" if distance <= 600 else "plane"
            route_info["distance_km"] = round(distance)
            route_info["recommended_mode"] = recommended_mode
            mode_data = [
                ("bus", distance / 40, "Indicative estimate; actual service and stops vary."),
                ("car", distance / 55, "Indicative road travel estimate; traffic and road distance vary."),
                ("train", distance / 65 + 0.5, "Indicative only; check routes and timetables."),
                ("plane", distance / 700 + 2.5, "Includes an approximate airport-time allowance; flights may not serve this route."),
            ]
            route_info["transport_options"] = [
                {"mode": mode, "hours": round(hours, 1), "note": note}
                for mode, hours, note in mode_data
            ]
        else:
            if not settings.GOOGLE_PLACES_API_KEY:
                route_info["location_notice"] = (
                    "We couldn't find coordinates for one or both places. Choose a listed destination, "
                    "or configure GOOGLE_PLACES_API_KEY to look up other locations."
                )
            elif location_lookup_failed:
                route_info["location_notice"] = (
                    "Google Places couldn't look up coordinates. Enable Places API (New) for your "
                    "Google Cloud project and check its API key restrictions and billing, or choose "
                    "destinations listed in the app."
                )
            else:
                route_info["location_notice"] = (
                    "We couldn't find coordinates for one or both places. Check the spelling or choose "
                    "a listed destination."
                )
        request.session["last_route_info"] = {
            "from": start_location,
            "to": end_location,
            "days": form.cleaned_data["days"],
            "distance_km": route_info.get("distance_km"),
            "recommended_mode": route_info.get("recommended_mode"),
            "transport_options": route_info["transport_options"],
        }

        if start_latitude is not None and end_latitude is not None:
            nearby_restaurants = []
            for restaurant in restaurants:
                if restaurant.latitude is not None and restaurant.longitude is not None:
                    restaurant.distance_from_destination_km = _distance_km(
                        end_latitude, end_longitude, restaurant.latitude, restaurant.longitude
                    )
                    if restaurant.distance_from_destination_km <= 50:
                        nearby_restaurants.append(restaurant)
            restaurants = sorted(
                nearby_restaurants,
                key=lambda restaurant: (
                    restaurant.distance_from_destination_km,
                    -restaurant.average_rating,
                    -restaurant.review_count,
                ),
            )[:8]
        else:
            restaurants = restaurants[:8]

        map_points = [
            {
                "name": destination.name,
                "latitude": destination.latitude,
                "longitude": destination.longitude,
                "kind": "Destination",
            }
            for destination in matches
        ]
        map_points.extend(
            {
                "name": restaurant.name,
                "latitude": restaurant.latitude,
                "longitude": restaurant.longitude,
                "kind": "Restaurant",
            }
            for restaurant in restaurants
            if restaurant.latitude is not None and restaurant.longitude is not None
        )
        context = {
            "form": form,
            "destinations": route_destinations,
            "restaurants": restaurants,
            "route_info": route_info,
            "day_plan": day_plan,
            "map_points": map_points,
            "locations": Destination.objects.order_by("name").values_list("name", flat=True),
        }
        return render(request, "core/route_planner.html", context)

    map_points = [
        {
            "name": destination.name,
            "latitude": destination.latitude,
            "longitude": destination.longitude,
            "kind": "Destination",
        }
        for destination in destinations
    ]
    return render(
        request,
        "core/route_planner.html",
        {
            "form": form,
            "destinations": destinations,
            "restaurants": restaurants,
            "map_points": map_points,
            "locations": Destination.objects.order_by("name").values_list("name", flat=True),
        },
    )


def _create_saved_trip(user, start_location, end_location, days, interests=""):
    trip = SavedTrip.objects.create(
        tourist=user,
        title=f"{start_location} â†’ {end_location}"[:150],
        notes=f"{days} day{'s' if days != 1 else ''}"
        + (f" | Interests: {interests}" if interests else ""),
    )
    for sequence, location in enumerate((start_location, end_location)):
        destination = _destination_for_location(location)
        TripStop.objects.create(
            trip=trip,
            stop_type="destination",
            destination=destination,
            name=location,
            latitude=destination.latitude if destination else None,
            longitude=destination.longitude if destination else None,
            sequence=sequence,
        )
    return trip


def _chat_save_trip_request(prompt, last_route_info):
    normalized_prompt = re.sub(r"\s+", " ", prompt.strip())
    if not re.match(r"^(?:save|store)\b", normalized_prompt, re.IGNORECASE):
        return None
    if not re.search(r"\btrip\b|\bdashboard\b", normalized_prompt, re.IGNORECASE):
        return None

    days_match = re.search(r"\bfor\s+(\d+)\s+days?\b", normalized_prompt, re.IGNORECASE)
    days = int(days_match.group(1)) if days_match else (last_route_info or {}).get("days", 1)
    without_dashboard = re.sub(
        r"\s+to\s+(?:my\s+)?dashboard\s*[.!?]*$",
        "",
        normalized_prompt,
        flags=re.IGNORECASE,
    )
    route_match = re.search(
        r"\btrip\s+(?:from\s+)?(.+?)\s+to\s+(.+?)(?:\s+for\s+\d+\s+days?)?\s*$",
        without_dashboard,
        re.IGNORECASE,
    )
    if route_match:
        start_location = route_match.group(1).strip(" .,!?")
        end_location = route_match.group(2).strip(" .,!?")
    elif last_route_info and last_route_info.get("from") and last_route_info.get("to"):
        start_location = last_route_info["from"]
        end_location = last_route_info["to"]
    else:
        return {"error": "Please provide the route, for example: save the trip Kerala to Karnataka to dashboard."}

    if not start_location or not end_location or not 1 <= days <= 14:
        return {"error": "Please provide valid places and a trip length from 1 to 14 days."}
    return {
        "start_location": start_location,
        "end_location": end_location,
        "days": days,
    }


@login_required
def save_trip(request):
    if not _is_tourist(request.user):
        messages.error(request, "Only tourist accounts can save trips.")
        return redirect("home")
    if request.method != "POST":
        return redirect("route_planner")

    start_location = request.POST.get("start_location", "").strip()[:200]
    end_location = request.POST.get("end_location", "").strip()[:200]
    try:
        days = int(request.POST.get("days", ""))
    except (TypeError, ValueError):
        days = 0
    interests = request.POST.get("interests", "").strip()[:200]

    if not start_location or not end_location or not 1 <= days <= 14:
        messages.error(request, "Choose valid starting and ending places and trip length before saving.")
        return redirect("route_planner")

    trip = SavedTrip.objects.create(
        tourist=request.user,
        title=f"{start_location} → {end_location}"[:150],
        notes=f"{days} day{'s' if days != 1 else ''}"
        + (f" | Interests: {interests}" if interests else ""),
    )
    for sequence, location in enumerate((start_location, end_location)):
        destination = _destination_for_location(location)
        TripStop.objects.create(
            trip=trip,
            stop_type="destination",
            destination=destination,
            name=location,
            latitude=destination.latitude if destination else None,
            longitude=destination.longitude if destination else None,
            sequence=sequence,
        )

    messages.success(request, "Trip plan saved to your dashboard.")
    return redirect("dashboard")


@require_POST
@login_required
def clear_saved_trips(request):
    if not _is_tourist(request.user):
        messages.error(request, "Only tourist accounts can clear saved trips.")
        return redirect("home")

    SavedTrip.objects.filter(tourist=request.user).delete()
    messages.success(request, "Your saved trip plans have been cleared.")
    return redirect("dashboard")


def restaurant_list(request):
    if request.user.is_authenticated and not _is_tourist(request.user):
        messages.error(request, "Restaurant search is available to tourist accounts.")
        return redirect("home")

    query = request.GET.get("q", "").strip()[:200]
    restaurants = []
    catalog_restaurants = []
    search_error = ""
    google_places_configured = bool(settings.GOOGLE_PLACES_API_KEY)

    if query:
        fallback_query = (
            Q(name__icontains=query)
            | Q(address__icontains=query)
            | Q(region__icontains=query)
            | Q(cuisine_type__icontains=query)
        )
        if google_places_configured:
            try:
                restaurants = search_restaurants_for_query(
                    query,
                    settings.GOOGLE_PLACES_API_KEY,
                )
            except requests.RequestException as error:
                logger.exception("Google Places restaurant search failed")
                status_code = getattr(getattr(error, "response", None), "status_code", None)
                if status_code == 403:
                    search_error = (
                        "Google Places rejected the request (HTTP 403). Check that Places API (New) "
                        "is enabled, billing is active, and the API key permits Places API requests."
                    )
                else:
                    search_error = (
                        "Google Places restaurant search is temporarily unavailable. "
                        "Check the API key and network connection, then try again."
                    )
        else:
            search_error = (
                "Live restaurant search is not configured. Add a Google Places API key "
                "to enable live results."
            )

        if search_error:
            catalog_restaurants = Restaurant.objects.filter(
                owner__username="restaurant_catalog_import",
                is_demo=False,
            ).filter(fallback_query).order_by("-external_rating", "name")[:20]
            demo_matches = Restaurant.objects.filter(is_demo=True).filter(fallback_query).order_by("name")[:20]
            restaurants = demo_matches if demo_matches.exists() else []

    return render(
        request,
        "core/restaurant_list.html",
        {
            "query": query,
            "restaurants": restaurants,
            "catalog_restaurants": catalog_restaurants,
            "search_error": search_error,
            "google_places_configured": google_places_configured,
        },
    )


def restaurant_detail(request, pk):
    restaurant = get_object_or_404(Restaurant, pk=pk)
    reviews = restaurant.reviews.filter(approved=True).select_related("reviewer").order_by("-created_at")
    form = ReviewForm() if not restaurant.is_demo and request.user.is_authenticated else None
    return render(
        request,
        "core/restaurant_detail.html",
        {
            "restaurant": restaurant,
            "reviews": reviews,
            "form": form,
        },
    )


@require_POST
@login_required
def submit_review(request, restaurant_id):
    restaurant = get_object_or_404(Restaurant, pk=restaurant_id)
    if restaurant.is_demo:
        return redirect("restaurant_detail", pk=restaurant.pk)
    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.restaurant = restaurant
        review.reviewer = request.user
        review.approved = True
        review.save()
        messages.success(request, "Your review was posted.")
    return redirect("restaurant_detail", pk=restaurant.pk)


@require_POST
@login_required
def update_restaurant_status(request, restaurant_id):
    if not request.user.is_staff:
        return redirect("home")

    restaurant = Restaurant.objects.filter(pk=restaurant_id).first()
    if not restaurant:
        return redirect("admin_dashboard")

    status = request.POST.get("status")
    if status in {"approved", "rejected", "pending"}:
        restaurant.status = status
        restaurant.approved_at = None if status != "approved" else restaurant.approved_at or timezone.now()
        restaurant.save(update_fields=["status", "approved_at", "updated_at"])
        messages.success(request, f"Restaurant status updated to {status}.")
    return redirect("admin_dashboard")


@login_required
def admin_dashboard(request):
    if not request.user.is_staff:
        return redirect("home")
    pending = Restaurant.objects.filter(status="pending")
    restaurants = Restaurant.objects.all().order_by("-created_at")
    return render(request, "core/admin_dashboard.html", {"pending": pending, "restaurants": restaurants})


def _chatbot_sse_event(event_type, **data):
    payload = {"type": event_type, **data}
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _restaurant_search_failure_message(error):
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    if status_code == 403:
        return (
            "Google Places rejected the request. Check that Places API (New) is enabled, "
            "billing is active, and the API key permits Places API requests."
        )
    return "Live Google restaurant search is temporarily unavailable. Check the API key and network, then try again."


def _regional_dish_reply(region, dishes, live_search_unavailable=False):
    prefix = (
        "Live Google restaurant search is not configured. Add GOOGLE_PLACES_API_KEY to enable live listings. "
        if live_search_unavailable
        else ""
    )
    if dishes:
        suggestions = ", ".join(dish.name for dish in dishes)
        reply = (
            f"{prefix}Regional food ideas for {region or 'your destination'}: {suggestions}. "
            "These are regional suggestions, not verified menu items at any restaurant."
        )
    else:
        reply = f"{prefix}I do not have regional dish suggestions for {region or 'that area'} yet."
    return f"{reply} Would you like more ideas from {region or 'this region'}, or suggestions for somewhere else?"


def _chat_follow_up_question(prompt, mentioned_region, restaurant_lookup, food_question):
    if restaurant_lookup:
        if mentioned_region:
            return (
                f"Would you like restaurant options in a specific city in {mentioned_region}, "
                "or should I keep the search region-wide?"
            )
        return "Which city or area should I focus on for restaurant options?"
    if food_question:
        if mentioned_region:
            return f"Would you prefer a particular meal or dietary style for food in {mentioned_region}?"
        return "Which region or dietary preference should I tailor the food suggestions to?"
    if re.search(r"\b(route|travel|trip|itinerary|plan|journey|getting)\b", prompt, re.IGNORECASE):
        return "What dates, budget, or travel pace should I use to tailor the route?"
    if mentioned_region:
        return f"What do you enjoy most in {mentioned_region}: nature, culture, history, or food?"
    return "Which part of India and what kind of experience are you most interested in?"


def _simple_chat_reply(prompt, mentioned_region, regional_dishes):
    normalized_prompt = re.sub(r"[.!?,]+$", "", prompt.strip().lower())
    if re.fullmatch(r"(?:hi|hello|hey|good morning|good afternoon|good evening)(?: there)?", normalized_prompt):
        return (
            "Hi! I can help you plan routes, explore destinations, or find local food. "
            "What city or region would you like to explore?"
        )

    if normalized_prompt not in {"food", "local food", "local dishes", "food ideas", "dish ideas"}:
        return None
    if not mentioned_region:
        return (
            "I can suggest regional dishes or help find restaurants. Which city or region should I focus on, "
            "and do you have any dietary preferences?"
        )

    if regional_dishes:
        suggestions = ", ".join(dish.name for dish in regional_dishes[:4])
        reply = (
            f"Some regional food ideas for {mentioned_region} are {suggestions}. "
            "These are regional suggestions, not confirmed restaurant menu items."
        )
    else:
        reply = f"I don't have regional food suggestions for {mentioned_region} in the catalog yet."
    return f"{reply} Do you prefer vegetarian options or a particular meal?"


def _restaurant_database_context(restaurants):
    context = []
    for restaurant in restaurants:
        location = restaurant.address or restaurant.region
        map_url = ""
        if location:
            map_query = quote_plus(f"{restaurant.name}, {location}")
            map_url = f"https://www.google.com/maps/search/?api=1&query={map_query}"
        context.append(
            {
                "name": restaurant.name,
                "address": restaurant.address,
                "region": restaurant.region,
                "description": restaurant.description,
                "cuisine_type": restaurant.cuisine_type,
                "price_range": restaurant.price_range,
                "contact_number": restaurant.contact_number,
                "opening_hours": restaurant.opening_hours,
                "rating": round(restaurant.rating, 1) if restaurant.rating is not None else None,
                "review_count": restaurant.approved_review_count,
                "status": restaurant.status,
                "map_url": map_url,
                "signature_dishes": [
                    {
                        "name": dish.name,
                        "description": dish.description,
                        "price": str(dish.price),
                        "vegetarian": dish.vegetarian,
                    }
                    for dish in restaurant.signature_dishes.all()
                ],
            }
        )
    return context


def _restaurant_database_reply(restaurants):
    if not restaurants:
        return "I could not find an approved restaurant matching that request in the app database."

    details = []
    for restaurant in restaurants:
        detail = f"{restaurant['name']}"
        if restaurant["cuisine_type"]:
            detail += f" — {restaurant['cuisine_type']}"
        if restaurant["price_range"]:
            detail += f", {restaurant['price_range']}"
        if restaurant["rating"] is not None:
            detail += f", rated {restaurant['rating']}/5 ({restaurant['review_count']} reviews)"
        if restaurant["opening_hours"]:
            detail += f", hours: {restaurant['opening_hours']}"
        if restaurant["contact_number"]:
            detail += f", contact: {restaurant['contact_number']}"
        if restaurant["signature_dishes"]:
            dishes = ", ".join(
                f"{dish['name']} (₹{dish['price']})"
                for dish in restaurant["signature_dishes"][:3]
            )
            detail += f", signature dishes: {dishes}"
        if restaurant["status"] != "approved":
            detail += " (pending approval; verify details before visiting)"
        details.append(detail)
    return "Approved restaurants from the app database: " + "; ".join(details) + "."


def _follow_up_fallback_reply(mentioned_region, destinations, regional_dishes):
    if not mentioned_region:
        return None
    destination_names = [destination.name for destination in destinations[:5]]
    if destination_names:
        reply = f"For {mentioned_region}, you could visit {', '.join(destination_names)}."
    elif regional_dishes:
        dish_names = [dish.name for dish in regional_dishes[:5]]
        reply = f"For food in {mentioned_region}, you could try {', '.join(dish_names)}."
    else:
        reply = f"I can continue planning your trip in {mentioned_region}."
    return f"{reply} Which one would you like to include in your plan?"


@login_required
def chatbot_view(request):
    if not _is_tourist(request.user):
        messages.error(request, "The travel assistant is available to tourist accounts.")
        return redirect("home")

    if request.method == "POST":
        prompt = request.POST.get("prompt", "").strip()[:1000]
        if not prompt:
            return JsonResponse({"reply": "Please enter a question."}, status=400)

        conversation = None
        if request.session.get("chat_conversation_id"):
            conversation = ChatConversation.objects.filter(
                pk=request.session["chat_conversation_id"],
                user=request.user,
            ).first()
        if not conversation:
            conversation = ChatConversation.objects.create(
                user=request.user,
                title=prompt[:50] or "New travel chat",
            )
            request.session["chat_conversation_id"] = conversation.pk

        user_message = ChatMessage.objects.create(
            conversation=conversation,
            sender="user",
            content=prompt,
        )
        chat_save_request = _chat_save_trip_request(
            prompt,
            request.session.get("last_route_info"),
        )
        chat_save_reply = None
        if chat_save_request:
            if chat_save_request.get("error"):
                chat_save_reply = chat_save_request["error"]
            else:
                trip = _create_saved_trip(
                    request.user,
                    chat_save_request["start_location"],
                    chat_save_request["end_location"],
                    chat_save_request["days"],
                )
                chat_save_reply = (
                    f"Saved your {chat_save_request['days']}-day trip from "
                    f"{chat_save_request['start_location']} to {chat_save_request['end_location']} "
                    f"to your dashboard (trip #{trip.pk})."
                )

        previous_assistant_replies = list(
            conversation.messages.filter(sender="bot")
            .order_by("-created_at", "-pk")
            .values_list("content", flat=True)
            [:8]
        )
        previous_user_prompts = list(
            conversation.messages.filter(sender="user")
            .exclude(pk=user_message.pk)
            .order_by("-created_at", "-pk")
            .values_list("content", flat=True)
            [:8]
        )
        is_short_food_follow_up = prompt.strip().lower().rstrip(".!?,") in {
            "food",
            "local food",
            "local dishes",
            "food ideas",
            "dish ideas",
        }
        ignored_search_terms = {
            "a", "an", "and", "are", "can", "could", "do", "for", "from",
            "give", "help", "how", "i", "in", "is", "it", "me", "my", "of",
            "on", "plan", "please", "recommend", "show", "suggest", "the",
            "there", "this", "to", "trip", "want", "what", "where", "with",
            "eat", "food", "place", "places", "restaurant", "restaurants",
        }
        search_terms = {
            term.strip(".,?!:;()[]{}\"'").lower()
            for term in prompt.split()
            if len(term.strip(".,?!:;()[]{}\"'")) >= 3
            and term.strip(".,?!:;()[]{}\"'").lower() not in ignored_search_terms
        }
        mentioned_regions = [
            region
            for region in INDIAN_STATES_AND_TERRITORIES
            if re.search(rf"\b{re.escape(region)}\b", prompt, re.IGNORECASE)
        ]
        mentioned_region = mentioned_regions[0] if mentioned_regions else None
        if not mentioned_region and is_short_food_follow_up:
            mentioned_region = next(
                (
                    region
                    for previous_reply in previous_assistant_replies
                    for region in INDIAN_STATES_AND_TERRITORIES
                    if re.search(rf"\b{re.escape(region)}\b", previous_reply, re.IGNORECASE)
                ),
                None,
            )
        restaurant_lookup = bool(
            re.search(r"\brestaurants?\b|\bplaces to eat\b|\bwhere to eat\b", prompt, re.IGNORECASE)
        )
        previous_restaurant_context = any(
            re.search(r"\brestaurants?\b|\bplaces to eat\b|\bwhere to eat\b", previous_prompt, re.IGNORECASE)
            for previous_prompt in previous_user_prompts[:1]
        ) or bool(
            previous_assistant_replies
            and re.search(
                r"\brestaurant options?\b|\boptions? in a specific city\b|\bwhere to eat\b",
                previous_assistant_replies[0],
                re.IGNORECASE,
            )
        )
        if not restaurant_lookup and mentioned_region and len(prompt.split()) <= 4 and previous_restaurant_context:
            restaurant_lookup = True
        food_question = bool(
            re.search(r"\b(food|dish|dishes|menu|eat|cuisine|restaurant)\b", prompt, re.IGNORECASE)
        )

        destination_query = Q()
        for region in mentioned_regions:
            destination_query |= Q(region__iexact=region)
        for term in search_terms:
            destination_query |= (
                Q(name__icontains=term)
                | Q(category__iexact=term)
                | Q(best_for__icontains=term)
            )
        relevant_destinations = Destination.objects.filter(destination_query).distinct()[:8]

        regional_dish_query = Q()
        for term in search_terms:
            regional_dish_query |= Q(name__icontains=term)
        if mentioned_region:
            regional_dishes = list(
                RegionalDishSuggestion.objects.filter(region__iexact=mentioned_region)[:6]
            )
        else:
            regional_dishes = list(RegionalDishSuggestion.objects.filter(regional_dish_query)[:6])

        restaurant_base_query = Restaurant.objects.filter(status="approved", is_demo=False).annotate(
            rating=Avg("reviews__rating", filter=Q(reviews__approved=True)),
            approved_review_count=Count("reviews", filter=Q(reviews__approved=True)),
        ).prefetch_related("signature_dishes")
        pending_restaurant_query = Restaurant.objects.filter(status="pending", is_demo=False).annotate(
            rating=Avg("reviews__rating", filter=Q(reviews__approved=True)),
            approved_review_count=Count("reviews", filter=Q(reviews__approved=True)),
        ).prefetch_related("signature_dishes")
        restaurant_matches = Q()
        for region in mentioned_regions:
            restaurant_matches |= Q(region__iexact=region) | Q(address__icontains=region)
        for term in search_terms:
            restaurant_matches |= (
                Q(name__icontains=term)
                | Q(address__icontains=term)
                | Q(region__icontains=term)
                | Q(cuisine_type__icontains=term)
                | Q(description__icontains=term)
                | Q(signature_dishes__name__icontains=term)
            )
        if restaurant_lookup:
            restaurant_queryset = restaurant_base_query.filter(restaurant_matches).distinct()
            if not restaurant_queryset.exists():
                restaurant_queryset = pending_restaurant_query.filter(restaurant_matches).distinct()
            if not restaurant_queryset.exists() and not mentioned_regions and not search_terms:
                restaurant_queryset = restaurant_base_query
            restaurant_queryset = restaurant_queryset.order_by("-rating", "name")[:5]
        else:
            restaurant_queryset = restaurant_base_query.order_by("-rating", "name")[:5] if food_question else []
        approved_restaurants = _restaurant_database_context(restaurant_queryset)

        recent_trips = (
            SavedTrip.objects.filter(tourist=request.user)
            .order_by("-created_at")
            .prefetch_related(
                Prefetch(
                    "stops",
                    queryset=TripStop.objects.order_by("sequence").only("name", "trip_id"),
                )
            )[:3]
        )
        context = {
            "planned_route": request.session.get("last_route_info"),
            "trip_context": [
                {
                    "title": trip.title.replace("→", "to"),
                    "stops": [stop.name for stop in trip.stops.all()],
                }
                for trip in recent_trips
            ],
            "destinations": [
                {"name": destination.name, "region": destination.region, "category": destination.category}
                for destination in relevant_destinations
            ],
            "approved_restaurants": approved_restaurants,
            "regional_dish_suggestions": [
                {
                    "region": dish.region,
                    "name": dish.name,
                    "description": dish.description,
                    "menu_status": "Regional suggestion only; not confirmed by any restaurant.",
                }
                for dish in regional_dishes
            ],
        }
        simple_reply = _simple_chat_reply(prompt, mentioned_region, regional_dishes)
        system_message = (
            "You are an India-focused travel assistant. Answer the user's actual question first with concise, direct "
            "guidance about routes, destinations, and local food. When information is missing, ask one short, targeted "
            "clarifying question instead of guessing. End every substantive answer with exactly one useful, specific "
            "follow-up question that naturally advances the travel planning; avoid generic questions and do not ask "
            "for information the user already provided. If the user is answering your immediately previous question, "
            "treat that message as the answer and continue that topic instead of starting a new topic. "
            "Use approved_restaurants only for restaurant-confirmed details and signature dishes; "
            "regional_dish_suggestions are ideas, not restaurant-confirmed menu items. Never invent restaurant names, "
            "menus, prices, ratings, opening hours, bookings, or destinations. Use planned_route only for approximate "
            "comparisons, not live schedules, fares, or availability. If application context does not support a factual "
            "answer, say so."
        )
        history = [
            {
                "role": "assistant" if message.sender == "bot" else "user",
                "content": message.content,
            }
            for message in conversation.messages.order_by("-created_at")[:8][::-1]
        ]
        chat_messages = [
            {"role": "system", "content": system_message},
            {"role": "system", "content": f"Application data: {json.dumps(context, separators=(',', ':'))}"},
            *history,
        ]
        is_follow_up_reply = bool(
            len(prompt.split()) <= 8
            and previous_assistant_replies
            and "?" in previous_assistant_replies[0]
        )

        def stream_response():
            generated = []
            bot_reply = ""
            history_saved = False
            try:
                if chat_save_reply:
                    bot_reply = chat_save_reply
                    generated.append(bot_reply)
                    yield _chatbot_sse_event("token", text=bot_reply)
                elif simple_reply:
                    bot_reply = simple_reply
                    generated.append(bot_reply)
                    yield _chatbot_sse_event("token", text=bot_reply)
                elif restaurant_lookup:
                    bot_reply = _restaurant_database_reply(approved_restaurants)
                    if regional_dishes:
                        suggestions = ", ".join(dish.name for dish in regional_dishes)
                        bot_reply += (
                            f" Regional dish ideas for {mentioned_region or 'the area'}: {suggestions}; "
                            "these are not verified menu items."
                        )
                    if mentioned_region:
                        bot_reply += (
                            f" Would you like options in a specific city in {mentioned_region}, "
                            "or should I keep the search region-wide?"
                        )
                    else:
                        bot_reply += " Which city or area should I focus on?"
                    generated.append(bot_reply)
                    yield _chatbot_sse_event("token", text=bot_reply)
                else:
                    for token in stream_chat_completion(chat_messages):
                        generated.append(token)
                        yield _chatbot_sse_event("token", text=token)
                    bot_reply = "".join(generated).rstrip()
                    if not bot_reply.endswith("?"):
                        follow_up = _chat_follow_up_question(
                            prompt,
                            mentioned_region,
                            restaurant_lookup,
                            food_question,
                        )
                        follow_up = f"\n\n{follow_up}"
                        bot_reply += follow_up
                        yield _chatbot_sse_event("token", text=follow_up)

                ChatMessage.objects.create(
                    conversation=conversation,
                    sender="bot",
                    content=bot_reply,
                )
                history_saved = True
                completion_data = {}
                if restaurant_lookup:
                    completion_data["database_restaurants"] = approved_restaurants
                yield _chatbot_sse_event("done", **completion_data)
            except AIServiceError as error:
                logger.warning("Travel assistant provider error: %s", error)
                if is_follow_up_reply and not generated:
                    fallback_reply = _follow_up_fallback_reply(
                        mentioned_region,
                        list(relevant_destinations),
                        regional_dishes,
                    )
                    if fallback_reply:
                        bot_reply = fallback_reply
                        ChatMessage.objects.create(
                            conversation=conversation,
                            sender="bot",
                            content=bot_reply,
                        )
                        history_saved = True
                        yield _chatbot_sse_event("token", text=bot_reply)
                        yield _chatbot_sse_event("done")
                        return
                bot_reply = "".join(generated)
                if bot_reply:
                    bot_reply += f"\n\n{error}"
                else:
                    bot_reply = str(error)
                yield _chatbot_sse_event("error", message=str(error))
            finally:
                if not history_saved:
                    ChatMessage.objects.create(
                        conversation=conversation,
                        sender="bot",
                        content=bot_reply or "The response was interrupted. Please ask again.",
                    )

        response = StreamingHttpResponse(
            stream_response(),
            content_type="text/event-stream; charset=utf-8",
        )
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    conversation = None
    if request.session.get("chat_conversation_id"):
        conversation = ChatConversation.objects.filter(
            pk=request.session["chat_conversation_id"],
            user=request.user,
        ).first()
    messages_list = conversation.messages.all() if conversation else []
    if request.GET.get("floating") == "1":
        return JsonResponse(
            {
                "messages": [
                    {"sender": message.sender, "content": message.content}
                    for message in messages_list
                ]
            }
        )
    return render(request, "core/chatbot_panel.html", {"messages": messages_list})
