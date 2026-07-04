from __future__ import annotations

from django.urls import path

from . import views

app_name = "console"

urlpatterns = [
    # Must precede the generic "<slug:key>/" pattern.
    path("forms/<uuid:pk>/mappings/", views.FormMappingsView.as_view(), name="form_mappings"),
    path("jobs/<uuid:pk>/assignments/", views.JobAssignmentsView.as_view(), name="job_assignments"),
    path("writeback/", views.WriteBackQueueView.as_view(), name="writeback"),
    path("publish-form/", views.PublishFormView.as_view(), name="publish_form"),
    path("form-builder/", views.FormBuilderListView.as_view(), name="form_builder"),
    path("form-builder/new/", views.FormDraftEditView.as_view(), name="form_new"),
    path("form-builder/<uuid:pk>/", views.FormDraftEditView.as_view(), name="form_edit"),
    path("form-builder/<uuid:pk>/publish/", views.FormDraftPublishView.as_view(),
         name="form_publish_draft"),
    path("form-builder/<uuid:pk>/delete/", views.FormDraftDeleteView.as_view(),
         name="form_delete_draft"),
    path("collection-units/import/", views.ImportCollectionUnitsView.as_view(),
         name="import_units"),
    path("plot-election/", views.PlotElectionQueueView.as_view(), name="plot_election"),
    path("plot-election/<slug:code>/<str:trial_key>/", views.PlotElectionView.as_view(),
         name="plot_elect"),
    path("new-project/", views.WizardView.as_view(), name="onboard"),
    path("new-project/advanced/", views.OnboardProjectView.as_view(), name="onboard_yaml"),
    path("new-project/projects/", views.WizardProjectsView.as_view(), name="wizard_projects"),
    path("new-project/fields/", views.FieldDiscoveryView.as_view(), name="discover_fields"),
    path("<slug:key>/", views.ConsoleListView.as_view(), name="list"),
    path("<slug:key>/new/", views.ConsoleFormView.as_view(), name="create"),
    path("<slug:key>/<uuid:pk>/", views.ConsoleFormView.as_view(), name="edit"),
    path("<slug:key>/<uuid:pk>/action/<slug:slug>/", views.ConsoleActionView.as_view(), name="action"),
    path("<slug:key>/<uuid:pk>/delete/", views.ConsoleDeleteView.as_view(), name="delete"),
]
