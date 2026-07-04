from __future__ import annotations

from django.urls import path

from . import views

app_name = "care"

urlpatterns = [
    path("", views.programs, name="programs"),
    path("my-caseload/", views.my_caseload, name="my_caseload"),
    path("<slug:code>/clients/", views.clients, name="clients"),
    path("<slug:code>/assign/", views.assign, name="assign"),
    path("<slug:code>/coverage/", views.coverage, name="coverage"),
    path("<slug:code>/client/<uuid:unit_id>/", views.client_timeline, name="client_timeline"),
]
