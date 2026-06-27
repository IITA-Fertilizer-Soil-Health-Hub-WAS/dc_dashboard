from __future__ import annotations

from django.urls import path

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
]
