"""In-app management console: staff-gated generic CRUD inside the app shell."""
from __future__ import annotations

import pytest

from apps.projects.models import Project, Trial

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return Project.objects.create(code="SNS-RWANDA", name="SNS Rwanda")


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_superuser("admin@x.org", "pw")


@pytest.fixture
def plain(django_user_model):
    return django_user_model.objects.create_user("user@x.org", "pw", is_active=True)


def test_list_renders_for_staff(client, staff, uc):
    client.force_login(staff)
    resp = client.get("/manage/projects/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Rendered in the app shell; management lives in the single green rail (no
    # separate console sidebar). Tenancy (institutions/regions/countries) is
    # consolidated behind the admin "Structure & projects" Set up hub.
    assert "Structure &amp; projects" in body
    assert "/manage/setup/structure/" in body
    assert "console-nav" not in body


def test_non_staff_forbidden(client, plain, uc):
    client.force_login(plain)
    assert client.get("/manage/projects/").status_code == 403


def test_admin_home_uses_lifecycle_sections(client, staff, uc):
    """The staff home rail is organised by the platform life-cycle with plain
    section headers — Overview / Structure / People / Build & integrate —
    mirroring the in-project phases. (Monitor appears only when a Care programme
    is active, so it isn't asserted here.)"""
    client.force_login(staff)
    body = client.get("/projects/").content.decode()  # directory = admin home, no active project
    for header in (">Overview<", ">Structure<", ">People<",
                   "Build &amp; integrate"):
        assert header in body
    # Renamed People items come from the registry (People-group labels).
    assert "Project access" in body and "Collector accounts" in body
    # Retired section headers are gone.
    assert ">Set up<" not in body and ">Accounts &amp; roles<" not in body and ">System<" not in body


def test_project_scoped_console_page_wears_workspace_frame(client, staff, uc):
    """A console section opened with ?project= is a section of that project's
    workspace, so it shows the 'Projects / <project> / <section>' breadcrumb —
    the same frame as the ?tab= pages — instead of the global 'Manage' trail."""
    client.force_login(staff)
    body = client.get(f"/manage/collection-units/?project={uc.code}").content.decode()
    assert uc.name in body  # the project name is in the breadcrumb
    assert f'href="/project/{uc.code}/"' in body  # crumb links back to the workspace


def test_global_admin_page_keeps_manage_frame_despite_active_project(client, staff, uc):
    """A global admin page (no ?project=) must NOT inherit a stale session project
    in its breadcrumb, even right after visiting a project-scoped page."""
    client.force_login(staff)
    client.get(f"/manage/collection-units/?project={uc.code}")  # sets active project
    body = client.get("/manage/organizations/").content.decode()
    assert "Manage" in body  # falls back to the global trail, not the project


def test_create_edit_delete_cycle(client, staff, uc):
    client.force_login(staff)
    # create
    r = client.post("/manage/trials/new/", {"project": str(uc.pk), "name": "T1", "code": "T1"})
    assert r.status_code == 302
    t = Trial.objects.get(name="T1")
    # edit
    r = client.post(f"/manage/trials/{t.pk}/", {"project": str(uc.pk), "name": "T1b", "code": "T1"})
    assert r.status_code == 302
    t.refresh_from_db()
    assert t.name == "T1b"
    # delete
    r = client.post(f"/manage/trials/{t.pk}/delete/")
    assert r.status_code == 302
    assert not Trial.objects.filter(pk=t.pk).exists()


def test_new_form_defaults_project_to_active_project(client, staff, uc):
    client.force_login(staff)
    # ?project= (carried by every scoped sidebar link) pre-selects the project.
    body = client.get(f"/manage/trials/new/?project={uc.code}").content.decode()
    assert f'value="{uc.pk}" selected' in body
    # Falls back to the active-project session when no query param is present.
    other = Project.objects.create(code="OTHER", name="Other")  # noqa: F841
    session = client.session
    session["active_project"] = uc.code
    session.save()
    body = client.get("/manage/trials/new/").content.decode()
    assert f'value="{uc.pk}" selected' in body


def test_field_data_has_no_console_group_only_workspace_links(staff):
    from apps.console.registry import REGISTRY, console_key_allowed, grouped_for

    groups = dict(grouped_for(staff))
    # Readonly mirrors of the project Data / Issues tabs are removed entirely.
    assert "submissions" not in REGISTRY and "validation-flags" not in REGISTRY
    # The field-data sections all live in the sidebar workspace / Manage — routable
    # and editable, but never repeated in a console group. There is no "Field data"
    # console group any more.
    assert "Field data" not in groups
    for key in ("jobs", "enumerators", "collection-units"):
        assert all(key not in {m.key for m in items} for items in groups.values())
        assert key in REGISTRY and console_key_allowed(staff, key)


def test_readonly_section_blocks_writes(client, staff, uc):
    client.force_login(staff)
    assert client.get("/manage/alert-events/").status_code == 200       # list allowed
    assert client.get("/manage/alert-events/new/").status_code == 403    # create blocked


def test_membership_stamps_granted_by(client, staff, uc, django_user_model):
    client.force_login(staff)
    target = django_user_model.objects.create_user("member@x.org", "pw", is_active=True)
    r = client.post("/manage/memberships/new/",
                    {"user": str(target.pk), "project": str(uc.pk), "role": "VIEWER"})
    assert r.status_code == 302
    from apps.rbac.models import Membership
    m = Membership.objects.get(user=target, project=uc)
    assert m.granted_by == staff  # auto-stamped


def test_every_managed_group_is_declared():
    """Guard the nav taxonomy: each console entry's group must be a rendered nav
    group (GROUPS/WORKSPACE_GROUPS) or an acknowledged off-nav category
    (OFF_NAV_GROUPS). A group outside ALL_GROUPS would silently never render —
    this catches that mistake at test time instead of in the UI."""
    from apps.console.registry import ALL_GROUPS, _ENTRIES

    unknown = sorted({m.group for m in _ENTRIES} - ALL_GROUPS)
    assert not unknown, f"Managed entries use undeclared group(s): {unknown}"
