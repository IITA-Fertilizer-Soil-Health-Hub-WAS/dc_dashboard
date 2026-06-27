from __future__ import annotations

from django.urls import path

from . import views

app_name = "kpi"

urlpatterns = [
    path("", views.kpi_overview, name="overview"),
    path("<slug:code>/", views.kpi_project, name="project"),
    path("<slug:code>/quality/", views.kpi_quality, name="quality"),
    path("<slug:code>/enumerators/", views.kpi_enumerators, name="enumerators"),
    path("<slug:code>/coverage/", views.kpi_coverage, name="coverage"),
]
