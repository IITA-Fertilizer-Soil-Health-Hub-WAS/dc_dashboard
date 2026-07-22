from __future__ import annotations

from django.urls import path

from .read_views import (
    FlagListAPI,
    KpiAPI,
    ProjectListAPI,
    SubmissionListAPI,
)
from .review_views import ReviewActionView
from .webhooks import collection_webhook

app_name = "api"

urlpatterns = [
    path(
        "review/<uuid:submission_id>/action/",
        ReviewActionView.as_view(),
        name="review-action",
    ),
    path(
        "webhooks/collection/<slug:code>/",
        collection_webhook,
        name="collection-webhook",
    ),
    # --- Read API (v1) ---
    path("v1/projects/", ProjectListAPI.as_view(), name="v1-projects"),
    path("v1/projects/<slug:code>/submissions/", SubmissionListAPI.as_view(),
         name="v1-submissions"),
    path("v1/projects/<slug:code>/flags/", FlagListAPI.as_view(), name="v1-flags"),
    path("v1/projects/<slug:code>/kpis/", KpiAPI.as_view(), name="v1-kpis"),
]
