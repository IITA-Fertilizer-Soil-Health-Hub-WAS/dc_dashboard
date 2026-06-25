from __future__ import annotations

from django.urls import path

from .review_views import ReviewActionView

app_name = "api"

urlpatterns = [
    path(
        "review/<uuid:submission_id>/action/",
        ReviewActionView.as_view(),
        name="review-action",
    ),
]
