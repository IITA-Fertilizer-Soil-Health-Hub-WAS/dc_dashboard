"""Importing form names + full field schemas from the collection server."""
from __future__ import annotations

import pytest

from apps.ingestion.backends.base import RemoteForm
from apps.projects.models import FormDefinition, Organization, Project

pytestmark = pytest.mark.django_db


class StubBackend:
    def list_forms(self):
        return [RemoteForm(id="9", title="Maize Survey")]

    def get_form_schema(self, ref):
        return [
            {"path": "grp/yield", "label": "Yield (kg)", "group": "", "type": "integer"},
            {"path": "grp/note", "label": "Read this", "type": "note"},
        ]


def test_sync_sets_title_and_fields(monkeypatch):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    f = FormDefinition.objects.create(project=p, ona_form_id=9, server_form_id="9", title="")

    from apps.ingestion import form_schema
    monkeypatch.setattr(
        "apps.ingestion.backends.registry.get_backend_for", lambda proj: StubBackend())

    form_schema.sync_project_schemas(p)
    f.refresh_from_db()
    assert f.title == "Maize Survey"                 # blank name filled from server
    assert len(f.field_schema) == 2                  # full field list cached

    # The rule builder's field choices expose them by label, minus display notes.
    from apps.console.views import _form_field_choices
    choices = {c["key"]: c["label"] for c in _form_field_choices(f)}
    assert choices == {"grp/yield": "Yield (kg)"}    # note dropped, label used
