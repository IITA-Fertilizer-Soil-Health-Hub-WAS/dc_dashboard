from __future__ import annotations

from django.urls import path

from . import views

app_name = "kpi"

urlpatterns = [
    path("", views.kpi_overview, name="overview"),
    path("alerts/", views.kpi_alerts, name="alerts"),
    # Dashboards must precede the generic "<slug:code>/" project pattern.
    path("dashboards/", views.dashboards, name="dashboards"),
    path("dashboards/new/", views.dashboard_edit, name="dashboard_new"),
    path("dashboards/<uuid:pk>/", views.dashboard_view, name="dashboard_view"),
    path("dashboards/<uuid:pk>/edit/", views.dashboard_edit, name="dashboard_edit"),
    path("dashboards/<uuid:pk>/delete/", views.dashboard_delete, name="dashboard_delete"),
    path("<slug:code>/", views.kpi_project, name="project"),
    path("<slug:code>/quality/", views.kpi_quality, name="quality"),
    path("<slug:code>/enumerators/", views.kpi_enumerators, name="enumerators"),
    path("<slug:code>/enumerators/<uuid:enum_id>/", views.kpi_enumerator_detail, name="enumerator_detail"),
    path("<slug:code>/coverage/", views.kpi_coverage, name="coverage"),
    path("<slug:code>/export/<slug:kind>/", views.kpi_export, name="export"),
]
