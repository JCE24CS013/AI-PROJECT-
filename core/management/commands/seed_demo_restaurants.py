from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from core.food_data import REGIONAL_DISH_SUGGESTIONS
from core.models import Restaurant, SignatureDish
from core.places import INDIAN_STATES_AND_TERRITORIES


class Command(BaseCommand):
    help = "Create the demo restaurant examples used across Indian states and union territories."

    @transaction.atomic
    def handle(self, *args, **options):
        demo_restaurants = Restaurant.objects.filter(is_demo=True)
        SignatureDish.objects.filter(restaurant__is_demo=True).delete()
        demo_restaurants.delete()

        demo_owner, _ = User.objects.get_or_create(username="demo_restaurant_examples")
        demo_owner.is_active = False
        demo_owner.set_unusable_password()
        demo_owner.save(update_fields=["is_active", "password"])

        created_count = 0
        for region in INDIAN_STATES_AND_TERRITORIES:
            restaurant = Restaurant.objects.create(
                owner=demo_owner,
                name=f"Demo Kitchen — {region}",
                description="Demo example — not a real restaurant",
                address=f"Demo listing — {region}, India (not a real location)",
                region=region,
                cuisine_type="Regional cuisine",
                price_range="₹₹",
                status="approved",
                is_demo=True,
            )
            dish_tuple = REGIONAL_DISH_SUGGESTIONS.get(region, (("Regional tasting platter", "A demo regional dish idea."),))
            dish_name, dish_description = dish_tuple[0]
            SignatureDish.objects.create(
                restaurant=restaurant,
                name=dish_name,
                description=dish_description,
                price="199.00",
                vegetarian=True,
                specialty=True,
            )
            created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created_count} demo restaurant examples and sample dishes for Indian states and union territories."
            )
        )
