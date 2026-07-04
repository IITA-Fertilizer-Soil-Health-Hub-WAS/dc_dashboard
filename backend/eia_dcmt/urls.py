"""Root URL configuration."""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts.views import LoginLandingView, claim_admin, create_admin, profile
from apps.common.views import healthcheck

# Auth0 is the only end-user auth path. Our /login/ landing is the single entry
# point; allauth's local login/signup are shadowed with redirects to it (these
# must precede the allauth include).
urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", LoginLandingView.as_view(), name="login"),
    path("claim-admin/", claim_admin, name="claim_admin"),
    path("create-admin/", create_admin, name="create_admin"),
    path("profile/", profile, name="profile"),
    path("accounts/login/", RedirectView.as_view(pattern_name="login", query_string=True)),
    path("accounts/signup/", RedirectView.as_view(pattern_name="login", query_string=True)),
    path("accounts/", include("allauth.urls")),
    path("healthz/", healthcheck, name="healthcheck"),
    path("api/", include("apps.api.urls")),
    path("kpi/", include("apps.kpi.urls")),
    path("care/", include("apps.care.urls")),
    path("manage/", include("apps.console.urls")),
    path("", include("apps.dashboards.urls")),
]
