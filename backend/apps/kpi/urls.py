from __future__ import annotations

from django.urls import path

from . import views

app_name = "kpi"

urlpatterns = [
    path("", views.kpi_overview, name="overview"),
    path("<slug:code>/", views.kpi_project, name="project"),
]
