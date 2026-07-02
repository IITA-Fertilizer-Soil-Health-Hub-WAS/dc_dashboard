"""In-app management console: staff-gated generic CRUD inside the app shell."""
from __future__ import annotations

import pytest

from apps.usecases.models import Trial, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return UseCase.objects.create(code="SNS-RWANDA", name="SNS Rwanda")


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_superuser("admin@x.org", "pw")


@pytest.fixture
def plain(django_user_model):
    return django_user_model.objects.create_user("user@x.org", "pw", is_active=True)


def test_list_renders_for_staff(client, staff, uc):
    client.force_login(staff)
    resp = client.get("/manage/use-cases/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Rendered in the app shell; management sections appear directly in the single
    # green rail (no separate console sidebar).
    assert "Configuration" in body
    assert "console-nav" not in body


def test_non_staff_forbidden(client, plain, uc):
    client.force_login(plain)
    assert client.get("/manage/use-cases/").status_code == 403


def test_create_edit_delete_cycle(client, staff, uc):
    client.force_login(staff)
    # create
    r = client.post("/manage/trials/new/", {"use_case": str(uc.pk), "name": "T1", "code": "T1"})
    assert r.status_code == 302
    t = Trial.objects.get(name="T1")
    # edit
    r = client.post(f"/manage/trials/{t.pk}/", {"use_case": str(uc.pk), "name": "T1b", "code": "T1"})
    assert r.status_code == 302
    t.refresh_from_db()
    assert t.name == "T1b"
    # delete
    r = client.post(f"/manage/trials/{t.pk}/delete/")
    assert r.status_code == 302
    assert not Trial.objects.filter(pk=t.pk).exists()


def test_new_form_defaults_use_case_to_active_project(client, staff, uc):
    client.force_login(staff)
    # ?use_case= (carried by every scoped sidebar link) pre-selects the project.
    body = client.get(f"/manage/trials/new/?use_case={uc.code}").content.decode()
    assert f'value="{uc.pk}" selected' in body
    # Falls back to the active-project session when no query param is present.
    other = UseCase.objects.create(code="OTHER", name="Other")  # noqa: F841
    session = client.session
    session["active_project"] = uc.code
    session.save()
    body = client.get("/manage/trials/new/").content.decode()
    assert f'value="{uc.pk}" selected' in body


def test_readonly_section_blocks_writes(client, staff, uc):
    client.force_login(staff)
    assert client.get("/manage/submissions/").status_code == 200       # list allowed
    assert client.get("/manage/submissions/new/").status_code == 403    # create blocked


def test_membership_stamps_granted_by(client, staff, uc, django_user_model):
    client.force_login(staff)
    target = django_user_model.objects.create_user("member@x.org", "pw", is_active=True)
    r = client.post("/manage/memberships/new/",
                    {"user": str(target.pk), "use_case": str(uc.pk), "role": "VIEWER"})
    assert r.status_code == 302
    from apps.rbac.models import UseCaseMembership
    m = UseCaseMembership.objects.get(user=target, use_case=uc)
    assert m.granted_by == staff  # auto-stamped
