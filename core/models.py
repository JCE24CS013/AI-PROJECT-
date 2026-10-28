from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse


class TouristProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="tourist_profile")
    preferred_interests = models.CharField(max_length=200, blank=True)
    home_city = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return self.user.username


class RestaurantOwnerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="owner_profile")
    restaurant_name = models.CharField(max_length=150, blank=True)
    contact_number = models.CharField(max_length=50, blank=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return self.user.username


class Destination(models.Model):
    CATEGORY_CHOICES = [
        ("beach", "Beach"),
        ("nature", "Nature"),
        ("history", "Historical"),
        ("adventure", "Adventure"),
        ("culture", "Culture"),
    ]
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="culture")
    region = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    best_for = models.CharField(max_length=200, blank=True)
    visit_hours = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to="destinations/", blank=True, null=True)

    def __str__(self):
        return self.name


class Restaurant(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="restaurants")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=300)
    region = models.CharField(max_length=120, blank=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    cuisine_type = models.CharField(max_length=120, blank=True)
    price_range = models.CharField(max_length=30, blank=True)
    contact_number = models.CharField(max_length=50, blank=True)
    opening_hours = models.CharField(max_length=200, blank=True)
    external_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    external_review_count = models.PositiveIntegerField(null=True, blank=True)
    listing_source = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to="restaurants/", blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    is_demo = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def average_rating(self):
        reviews = self.reviews.filter(approved=True)
        if not reviews.exists():
            return 0.0
        return round(sum(r.rating for r in reviews) / reviews.count(), 1)

    @property
    def review_count(self):
        return self.reviews.filter(approved=True).count()

    def get_absolute_url(self):
        return reverse("restaurant_detail", kwargs={"pk": self.pk})


class GooglePlaceReference(models.Model):
    place_id = models.CharField(max_length=255)
    region = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("region", "place_id")
        constraints = [
            models.UniqueConstraint(
                fields=("region", "place_id"),
                name="unique_google_place_reference_per_region",
            )
        ]

    def __str__(self):
        return self.place_id


class RegionalDishSuggestion(models.Model):
    region = models.CharField(max_length=120)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("region", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("region", "name"),
                name="unique_regional_dish_suggestion",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.region})"


class SignatureDish(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="signature_dishes")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    image = models.ImageField(upload_to="dishes/", blank=True, null=True)
    vegetarian = models.BooleanField(default=False)
    specialty = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class RestaurantReview(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="restaurant_reviews")
    rating = models.IntegerField(default=5)
    comment = models.TextField(blank=True)
    approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.restaurant.name} - {self.rating}"


class SavedTrip(models.Model):
    tourist = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_trips")
    title = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class TripStop(models.Model):
    STOP_TYPE_CHOICES = [
        ("destination", "Destination"),
        ("restaurant", "Restaurant"),
    ]
    trip = models.ForeignKey(SavedTrip, on_delete=models.CASCADE, related_name="stops")
    stop_type = models.CharField(max_length=20, choices=STOP_TYPE_CHOICES)
    destination = models.ForeignKey(Destination, null=True, blank=True, on_delete=models.SET_NULL, related_name="trip_stops")
    restaurant = models.ForeignKey(Restaurant, null=True, blank=True, on_delete=models.SET_NULL, related_name="trip_stops")
    name = models.CharField(max_length=200)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    sequence = models.IntegerField(default=0)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


class ChatConversation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_conversations")
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or f"Chat {self.pk}"


class ChatMessage(models.Model):
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=20, choices=[("user", "User"), ("bot", "Bot")], default="user")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sender}: {self.content[:80]}"
