from __future__ import annotations

from django.urls import path

from . import projects as projects_views
from . import team, views

app_name = "dashboards"

urlpatterns = [
    path("", projects_views.projects, name="index"),
    path("projects/", projects_views.projects, name="projects"),
    path("projects/<slug:code>/request/", projects_views.project_request, name="project_request"),
    path("my-assignments/", views.my_assignments, name="my_assignments"),
    path("my-submissions/", views.my_submissions, name="my_submissions"),
    path("my-performance/", views.my_performance, name="my_performance"),
    path("style-preview/", views.style_preview, name="style_preview"),
    path("overview/", views.overview, name="overview"),
    path("team/", team.team, name="team"),
    path("team/grant/", team.team_grant, name="team_grant"),
    path("team/invite/", team.team_invite, name="team_invite"),
    path("team/revoke/", team.team_revoke, name="team_revoke"),
    path("team/request/", team.team_request_decision, name="team_request_decision"),
    path("usecase/<slug:code>/", views.usecase_detail, name="usecase"),
    path("usecase/<slug:code>/audit.csv", views.export_audit, name="export_audit"),
    path("usecase/<slug:code>/tab/summary/", views.tab_summary, name="tab_summary"),
    path("usecase/<slug:code>/tab/review/", views.tab_review, name="tab_review"),
    path("usecase/<slug:code>/tab/review/action/", views.tab_review_action, name="tab_review_action"),
    path("usecase/<slug:code>/qc-signoff/", views.qc_signoff, name="qc_signoff"),
    path("usecase/<slug:code>/household/<uuid:hh_id>/", views.household_timeline, name="household_timeline"),
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
    path(
        "usecase/<slug:code>/submission/<uuid:submission_id>/media/<str:name>/",
        views.submission_media,
        name="submission_media",
    ),
    path("usecase/<slug:code>/bulk-action/", views.bulk_submission_action, name="bulk_action"),
    path(
        "usecase/<slug:code>/submission/<uuid:submission_id>/action/",
        views.submission_action,
        name="submission_action",
    ),
]
