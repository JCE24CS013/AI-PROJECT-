from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Restaurant, SignatureDish, RestaurantReview


class TouristSignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "placeholder": "Choose a username"}
        )
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "placeholder": "you@example.com"}
        )
        self.fields["password1"].widget.attrs.update(
            {"autocomplete": "new-password", "placeholder": "Create a password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"autocomplete": "new-password", "placeholder": "Repeat your password"}
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class OwnerSignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    restaurant_name = forms.CharField(max_length=150, required=True)
    contact_number = forms.CharField(max_length=50, required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2", "restaurant_name", "contact_number")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class ProfileUpdateForm(forms.Form):
    first_name = forms.CharField(max_length=100, required=False)
    last_name = forms.CharField(max_length=100, required=False)
    email = forms.EmailField(required=False)
    home_city = forms.CharField(max_length=100, required=False)
    preferred_interests = forms.CharField(max_length=200, required=False)
    restaurant_name = forms.CharField(max_length=150, required=False)
    contact_number = forms.CharField(max_length=50, required=False)
    bio = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


class RestaurantForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = [
            "name",
            "description",
            "address",
            "latitude",
            "longitude",
            "cuisine_type",
            "price_range",
            "contact_number",
            "opening_hours",
            "image",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "opening_hours": forms.TextInput(attrs={"placeholder": "Mon-Sun 9:00 AM - 10:00 PM"}),
        }


class SignatureDishForm(forms.ModelForm):
    class Meta:
        model = SignatureDish
        fields = ["name", "description", "price", "image", "vegetarian", "specialty"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class ReviewForm(forms.ModelForm):
    class Meta:
        model = RestaurantReview
        fields = ["rating", "comment"]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3}),
        }


class RouteSearchForm(forms.Form):
    start_location = forms.CharField(
        max_length=200,
        required=True,
        label="From",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Kochi", "list": "route-locations"}),
    )
    end_location = forms.CharField(
        max_length=200,
        required=True,
        label="To",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Munnar", "list": "route-locations"}),
    )
    days = forms.IntegerField(min_value=1, max_value=14, initial=2)
    interests = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "beach,nature,history"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
