from django.contrib import admin
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
    TripStop,
)


@admin.register(TouristProfile)
class TouristProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "preferred_interests", "home_city")


@admin.register(RestaurantOwnerProfile)
class RestaurantOwnerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "restaurant_name", "contact_number")


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "region")
    search_fields = ("name", "region")


@admin.register(RegionalDishSuggestion)
class RegionalDishSuggestionAdmin(admin.ModelAdmin):
    list_display = ("name", "region")
    list_filter = ("region",)
    search_fields = ("name", "region", "description")


@admin.register(GooglePlaceReference)
class GooglePlaceReferenceAdmin(admin.ModelAdmin):
    list_display = ("place_id", "region", "last_seen_at")
    list_filter = ("region",)
    search_fields = ("place_id", "region")


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "owner", "cuisine_type", "external_rating", "status")
    list_filter = ("status", "cuisine_type")
    search_fields = ("name", "address", "owner__username")


@admin.register(SignatureDish)
class SignatureDishAdmin(admin.ModelAdmin):
    list_display = ("name", "restaurant", "vegetarian", "specialty")


@admin.register(RestaurantReview)
class RestaurantReviewAdmin(admin.ModelAdmin):
    list_display = ("restaurant", "reviewer", "rating", "approved")


@admin.register(SavedTrip)
class SavedTripAdmin(admin.ModelAdmin):
    list_display = ("title", "tourist", "created_at")


@admin.register(TripStop)
class TripStopAdmin(admin.ModelAdmin):
    list_display = ("trip", "name", "stop_type", "sequence")


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "created_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "created_at")
