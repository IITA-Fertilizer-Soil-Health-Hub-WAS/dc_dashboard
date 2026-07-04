"""Per-form Overview (ONA-style): stats + 'collect this form' server URL + QR."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.console.collect import collect_qr_data_uri, collect_server_url
from apps.projects.models import DataSource, FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Enumerator, Submission

pytestmark = pytest.mark.django_db


def test_collect_server_url_per_backend():
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    DataSource.objects.create(project=p, backend="ONA", base_url="https://api.ona.io",
                              config={"project_id": "251274"})
    assert collect_server_url(p) == "https://api.ona.io/projects/251274"


def test_qr_is_svg_data_uri():
    uri = collect_qr_data_uri("https://api.ona.io/projects/1", "SNS")
    assert uri.startswith("data:image/svg+xml")
    assert collect_qr_data_uri("") == ""  # no server → no QR


@pytest.fixture
def form(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    proj = Project.objects.create(code="SL", name="Sierra Leone", organization=org)
    DataSource.objects.create(project=proj, backend="ONA", base_url="https://api.ona.io",
                              config={"project_id": "251274"})
    f = FormDefinition.objects.create(project=proj, ona_form_id=9, title="01 Rapid Survey",
                                      role=FormDefinition.Role.VALIDATION)
    en = Enumerator.objects.create(project=proj, enid="EN1")
    Submission.objects.create(project=proj, form=f, enumerator=en, ona_uuid="u1", content_hash="h")
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, region=None, project=proj, role=Role.TRIAL_COORDINATOR)
    return {"f": f, "proj": proj, "admin": admin, "coord": coord}


def test_form_overview_renders(client, form):
    client.force_login(form["admin"])
    resp = client.get(reverse("console:form_overview", args=[form["f"].pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "01 Rapid Survey" in body
    assert "Submissions" in body and "Collect this form" in body
    # The collection server URL + QR are shown.
    assert "https://api.ona.io/projects/251274" in body
    assert "data:image/svg+xml" in body
    assert "Collects validation data" in body  # role → relationship


def test_form_overview_scoped_for_nonstaff(client, django_user_model, form):
    """A coordinator can't open a form in a project they can't see."""
    other = Project.objects.create(code="OTHER", name="Other")
    of = FormDefinition.objects.create(project=other, ona_form_id=2,
                                       role=FormDefinition.Role.VALIDATION)
    client.force_login(form["coord"])
    # Their own project's form is fine; the other project's 404s.
    assert client.get(reverse("console:form_overview", args=[form["f"].pk])).status_code == 200
    assert client.get(reverse("console:form_overview", args=[of.pk])).status_code == 404


def test_forms_list_links_to_overview(client, form):
    client.force_login(form["admin"])
    html = client.get(reverse("console:list", args=["forms"])).content
    assert reverse("console:form_overview", args=[form["f"].pk]).encode() in html
