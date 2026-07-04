from __future__ import annotations

from django.urls import path

from . import views

app_name = "care"

urlpatterns = [
    path("", views.programs, name="programs"),
    path("<slug:code>/clients/", views.clients, name="clients"),
    path("<slug:code>/coverage/", views.coverage, name="coverage"),
    path("<slug:code>/client/<uuid:unit_id>/", views.client_timeline, name="client_timeline"),
]
