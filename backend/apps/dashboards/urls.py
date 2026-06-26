from __future__ import annotations

from django.urls import path

from . import team, views

app_name = "dashboards"

urlpatterns = [
    path("", views.index, name="index"),
    path("overview/", views.overview, name="overview"),
    path("my-queue/", views.my_queue, name="my_queue"),
    path("team/", team.team, name="team"),
    path("team/grant/", team.team_grant, name="team_grant"),
    path("team/revoke/", team.team_revoke, name="team_revoke"),
    path("usecase/<slug:code>/", views.usecase_detail, name="usecase"),
    path("usecase/<slug:code>/audit.csv", views.export_audit, name="export_audit"),
    path("usecase/<slug:code>/tab/summary/", views.tab_summary, name="tab_summary"),
    path("usecase/<slug:code>/tab/enumerators/", views.tab_enumerators, name="tab_enumerators"),
    path("usecase/<slug:code>/tab/issues/", views.tab_issues, name="tab_issues"),
    path("usecase/<slug:code>/tab/data/", views.tab_data, name="tab_data"),
    path("usecase/<slug:code>/tab/final/", views.tab_final, name="tab_final"),
    path("usecase/<slug:code>/final.csv", views.export_final, name="export_final"),
    path(
        "usecase/<slug:code>/submission/<uuid:submission_id>/review/",
        views.submission_review,
        name="submission_review",
    ),
    path("usecase/<slug:code>/bulk-action/", views.bulk_submission_action, name="bulk_action"),
    path(
        "usecase/<slug:code>/submission/<uuid:submission_id>/action/",
        views.submission_action,
        name="submission_action",
    ),
]
