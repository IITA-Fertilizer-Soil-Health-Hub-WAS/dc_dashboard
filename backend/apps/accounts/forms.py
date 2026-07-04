"""The one-step signup form shown right after Auth0 verifies a first-time user.

With SOCIALACCOUNT_AUTO_SIGNUP off, allauth renders this before the account is
finalized: the person fills their profile once, and only on submit is the User +
UserProfile created (inactive, pending admin approval). No account exists until
everything is provided — so there's no half-registered state to gate afterwards.
"""
from __future__ import annotations

from allauth.socialaccount.forms import SignupForm as SocialSignupBase
from django import forms
from django.utils import timezone

from .models import UserProfile


class SocialSignupForm(SocialSignupBase):
    # Name is collected as parts (familiar registration UX) but stored once, on
    # User.full_name — mirrors the ODK 00_RegisterEnumerator form.
    first_name = forms.CharField(max_length=128, label="First name")
    second_name = forms.CharField(max_length=128, required=False, label="Second name")
    family_name = forms.CharField(max_length=128, label="Family name")
    phone = forms.CharField(max_length=32, label="Primary mobile phone")

    gender = forms.ChoiceField(choices=[("", "—"), *UserProfile.Gender.choices], required=False)
    age = forms.IntegerField(min_value=0, max_value=120, required=False)
    education_level = forms.ChoiceField(
        choices=[("", "—"), *UserProfile.Education.choices], required=False,
        label="Education level",
    )
    experience_years = forms.IntegerField(
        min_value=0, max_value=80, required=False,
        label="Years of data-collection experience",
    )
    phone_alt = forms.CharField(max_length=32, required=False, label="Alternate phone")
    country = forms.CharField(max_length=64, label="Country")

    # Optional self-service institution. Left blank for field enumerators who
    # don't belong to a listed institution — an admin can bind them at approval.
    organization = forms.ModelChoiceField(
        queryset=None, required=False, label="Institution (if you belong to one)",
        empty_label="— none / not sure —",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.projects.models import Organization

        self.fields["organization"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")

    consent_personal_info = forms.BooleanField(
        required=False, label="I consent to the platform storing my personal information."
    )
    consent_followup = forms.BooleanField(
        required=False, label="I consent to being contacted for follow-up."
    )
    consent_photos = forms.BooleanField(
        required=False, label="I consent to photos I capture being stored."
    )

    def custom_signup(self, request, user):
        """Runs after the account is created — persist the name/phone on the User
        and the rest as the completed one-time UserProfile."""
        cd = self.cleaned_data
        parts = [cd.get("first_name"), cd.get("second_name"), cd.get("family_name")]
        user.full_name = " ".join(p for p in parts if p).strip()
        user.phone = cd["phone"]
        fields = ["full_name", "phone", "updated_at"]
        if cd.get("organization"):
            user.organization = cd["organization"]
            fields.append("organization")
        user.save(update_fields=fields)

        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "gender": cd.get("gender") or "",
                "age": cd.get("age"),
                "education_level": cd.get("education_level") or "",
                "experience_years": cd.get("experience_years"),
                "phone_alt": cd.get("phone_alt") or "",
                "country": cd.get("country") or "",
                "consent_personal_info": cd.get("consent_personal_info", False),
                "consent_followup": cd.get("consent_followup", False),
                "consent_photos": cd.get("consent_photos", False),
                "completed_at": timezone.now(),
            },
        )
