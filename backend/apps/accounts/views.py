from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import UserProfile
from .services import claim_admin_available, platform_admin_exists


class LoginLandingView(LoginView):
    """Single sign-in page offering BOTH paths:

    * "Continue with Auth0" (the primary path for everyone), and
    * an email/password form for Platform Admins / staff.

    Regular users provisioned via Auth0 have an unusable password, so the form
    only works for accounts that have a password set (admins) and, like all
    logins, only for active users. Authentication uses the ModelBackend.
    """

    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["auth0_configured"] = settings.AUTH0_CONFIGURED
        ctx["auth0_login_url"] = settings.AUTH0_LOGIN_URL
        # Entra ID is an optional fallback — only surfaced when configured.
        ctx["entra_configured"] = settings.ENTRA_CONFIGURED
        ctx["entra_login_url"] = settings.ENTRA_LOGIN_URL
        ctx["next"] = self.request.GET.get("next", "")
        return ctx


@login_required
@require_http_methods(["GET", "POST"])
def claim_admin(request):
    """One-time in-app bootstrap: the first user claims Platform Admin.

    Available only while no Platform Admin exists; closes permanently after the
    first claim. The POST re-checks inside a transaction so two simultaneous
    claims can't both win.
    """
    if not claim_admin_available(request.user):
        if platform_admin_exists():
            messages.info(request, "A Platform Admin already exists.")
        return redirect("dashboards:index")

    if request.method == "POST":
        with transaction.atomic():
            if platform_admin_exists():
                messages.info(request, "A Platform Admin already exists.")
                return redirect("dashboards:index")
            user = request.user
            user.is_superuser = True
            user.is_staff = True
            user.is_active = True
            user.approved_at = user.approved_at or timezone.now()
            user.save(update_fields=[
                "is_superuser", "is_staff", "is_active", "approved_at", "updated_at",
            ])
        messages.success(
            request, "You are now the Platform Admin. You can approve users and "
            "manage everything from here."
        )
        return redirect("dashboards:index")

    return render(request, "accounts/claim_admin.html", {})


class ProfileForm(forms.ModelForm):
    """The 'register once' profile, mirroring the ODK 00_RegisterEnumerator form.
    Primary phone lives on the User; everything else on UserProfile."""

    phone = forms.CharField(max_length=32, required=True, label="Primary mobile phone")

    class Meta:
        model = UserProfile
        fields = [
            "first_name", "second_name", "family_name", "gender", "age",
            "education_level", "phone_alt", "country", "enumerator_card_id",
            "consent_personal_info", "consent_followup", "consent_photos",
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        for req in ("first_name", "family_name", "country"):
            self.fields[req].required = True
        if user and not (self.data or self.initial.get("phone")):
            self.fields["phone"].initial = user.phone


@login_required
def profile(request):
    """Fill the identity profile once; reused everywhere instead of re-registering
    in the field on every ODK form."""
    prof, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=prof, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            request.user.phone = form.cleaned_data["phone"]
            request.user.save(update_fields=["phone", "updated_at"])
            obj.save()
            obj.mark_complete()
            messages.success(request, "Your profile has been saved. You won't need to re-enter this.")
            return redirect("profile")
    else:
        initial = {"phone": request.user.phone}
        if not prof.first_name and request.user.full_name:
            bits = request.user.full_name.split()
            initial["first_name"] = bits[0]
            if len(bits) > 1:
                initial["family_name"] = bits[-1]
        form = ProfileForm(instance=prof, user=request.user, initial=initial)
    return render(request, "accounts/profile.html", {"form": form, "profile": prof})
