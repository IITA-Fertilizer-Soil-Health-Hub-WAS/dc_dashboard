from __future__ import annotations

from django.urls import path

from . import views

app_name = "console"

urlpatterns = [
    # Must precede the generic "<slug:key>/" pattern.
    path("writeback/", views.WriteBackQueueView.as_view(), name="writeback"),
    path("new-project/", views.WizardView.as_view(), name="onboard"),
    path("new-project/advanced/", views.OnboardProjectView.as_view(), name="onboard_yaml"),
    path("new-project/fields/", views.FieldDiscoveryView.as_view(), name="discover_fields"),
    path("<slug:key>/", views.ConsoleListView.as_view(), name="list"),
    path("<slug:key>/new/", views.ConsoleFormView.as_view(), name="create"),
    path("<slug:key>/<uuid:pk>/", views.ConsoleFormView.as_view(), name="edit"),
    path("<slug:key>/<uuid:pk>/action/<slug:slug>/", views.ConsoleActionView.as_view(), name="action"),
    path("<slug:key>/<uuid:pk>/delete/", views.ConsoleDeleteView.as_view(), name="delete"),
]
