import logging
import math
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

INDIAN_STATES_AND_TERRITORIES = (
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
)

STATE_SEARCH_QUERIES = (
    "restaurants in {state}, India",
    "top rated restaurants in {state}, India",
    "local cuisine restaurants in {state}, India",
    "popular dining in {state}, India",
    "Indian food restaurants in {state}, India",
)

GOOGLE_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.rating,places.userRatingCount,places.priceLevel,"
    "places.googleMapsUri,places.primaryTypeDisplayName"
)
GOOGLE_LOCATION_FIELD_MASK = "places.location"


def resolve_place_location(location, api_key):
    response = requests.post(
        GOOGLE_PLACES_SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": GOOGLE_LOCATION_FIELD_MASK,
        },
        json={
            "textQuery": location,
            "pageSize": 1,
            "languageCode": "en",
            "regionCode": "IN",
        },
        timeout=12,
    )
    response.raise_for_status()
    places = response.json().get("places", [])
    if not places:
        return None
    return places[0].get("location")


def _maps_search_url(name, address=None):
    query = name or "restaurant"
    if address:
        query = f"{query} {address}"
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def search_restaurants_for_query(query, api_key, page_size=10):
    """Fetch live Google restaurant results; callers may persist place IDs only."""
    response = requests.post(
        GOOGLE_PLACES_SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
        },
        json={
            "textQuery": query,
            "pageSize": page_size,
            "languageCode": "en",
            "regionCode": "IN",
            "includedType": "restaurant",
            "strictTypeFiltering": True,
        },
        timeout=12,
    )
    response.raise_for_status()
    places = []
    for place in response.json().get("places") or []:
        if not isinstance(place, dict):
            continue
        place_id = place.get("id")
        display_name = (place.get("displayName") or {}).get("text")
        if not place_id or not display_name:
            continue
        place["name"] = display_name
        place["googleMapsUri"] = place.get("googleMapsUri") or _maps_search_url(
            display_name,
            place.get("formattedAddress"),
        )
        places.append(place)
    return sorted(
        places,
        key=lambda place: (
            place.get("rating") or 0,
            math.log1p(place.get("userRatingCount") or 0),
        ),
        reverse=True,
    )


def search_state_restaurants(state, api_key):
    """Fetch live Google Places candidates; only place IDs may be persisted."""
    places_by_id = {}

    for query_template in STATE_SEARCH_QUERIES:
        response = requests.post(
            GOOGLE_PLACES_SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
            },
            json={
                "textQuery": query_template.format(state=state),
                "pageSize": 20,
                "languageCode": "en",
                "regionCode": "IN",
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        for place in payload.get("places") or []:
            if not isinstance(place, dict):
                continue
            place_id = place.get("id")
            display_name = (place.get("displayName") or {}).get("text")
            if not place_id or not display_name:
                continue
            place["name"] = display_name
            places_by_id[place_id] = place

    return sorted(
        places_by_id.values(),
        key=lambda place: (
            place.get("rating") or 0,
            math.log1p(place.get("userRatingCount") or 0),
        ),
        reverse=True,
    )[:100]
