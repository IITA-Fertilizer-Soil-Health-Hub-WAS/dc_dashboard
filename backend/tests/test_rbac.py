"""RBAC scoping tests — a role grant in one project must not leak to another."""
from __future__ import annotations

import pytest

from apps.projects.models import Project
from apps.rbac.models import Role, UseCaseMembership
from apps.rbac.permissions import user_can, visible_projects

pytestmark = pytest.mark.django_db


@pytest.fixture
def users(django_user_model):
    coord = django_user_model.objects.create_user("coord@x.org", "pw", is_active=True)
    qc = django_user_model.objects.create_user("qc@x.org", "pw", is_active=True)
    admin = django_user_model.objects.create_superuser("admin@x.org", "pw")
    viewer = django_user_model.objects.create_user("viewer@x.org", "pw", is_active=True)
    return coord, qc, admin, viewer


@pytest.fixture
def projects():
    rwanda = Project.objects.create(code="SNS-RWANDA", name="SNS Rwanda")
    kalro = Project.objects.create(code="KALRO", name="KALRO")
    return rwanda, kalro


def test_coordinator_scoped_to_their_project(users, projects):
    coord, _, _, _ = users
    rwanda, kalro = projects
    UseCaseMembership.objects.create(user=coord, project=rwanda, role=Role.TRIAL_COORDINATOR)

    # Can act on Rwanda...
    assert user_can(coord, "decline", rwanda)
    assert user_can(coord, "request_edit", rwanda)
    assert user_can(coord, "edit", rwanda)
    assert user_can(coord, "view", rwanda)
    # ...but NOT on KALRO (no membership there).
    assert not user_can(coord, "decline", kalro)
    assert not user_can(coord, "view", kalro)


def test_gate1_coordinator_endorses_not_validates(users, projects):
    """Trial Coordinator = Gate 1: reviews and endorses, but cannot finally validate."""
    coord, _, _, _ = users
    rwanda, _ = projects
    UseCaseMembership.objects.create(user=coord, project=rwanda, role=Role.TRIAL_COORDINATOR)
    for action in ("view", "open_review", "request_edit", "edit", "decline", "endorse", "sync"):
        assert user_can(coord, action, rwanda), action
    assert not user_can(coord, "final_approve", rwanda)  # Gate 2 is Regional's


def test_country_coordinator_is_gate1(users, projects):
    coord, person, _, regional = users
    rwanda, _ = projects
    UseCaseMembership.objects.create(user=person, project=rwanda, role=Role.COUNTRY_COORDINATOR)
    UseCaseMembership.objects.create(user=regional, project=rwanda, role=Role.REGIONAL_COORDINATOR)
    assert user_can(person, "endorse", rwanda)
    # With a Regional present, the Country Coordinator does not validate.
    assert not user_can(person, "final_approve", rwanda)


def test_country_coordinator_validates_when_no_regional(users, projects):
    """Fallback: with no Regional covering the project, a Country Coordinator
    may give the final validation so reviews don't stall."""
    _, person, _, _ = users
    rwanda, _ = projects
    UseCaseMembership.objects.create(user=person, project=rwanda, role=Role.COUNTRY_COORDINATOR)
    assert user_can(person, "final_approve", rwanda)  # no Regional exists


def test_regional_coordinator_is_gate2(users, projects):
    """Regional Coordinator = Gate 2: the final validation, and not a Gate-1 endorser."""
    _, _, _, person = users
    rwanda, _ = projects
    UseCaseMembership.objects.create(user=person, project=rwanda, role=Role.REGIONAL_COORDINATOR)
    assert user_can(person, "final_approve", rwanda)
    assert user_can(person, "decline", rwanda)  # can still send back / decline
    assert not user_can(person, "endorse", rwanda)  # endorsement is Gate 1's


def test_viewer_is_read_only(users, projects):
    _, _, _, viewer = users
    rwanda, _ = projects
    UseCaseMembership.objects.create(user=viewer, project=rwanda, role=Role.VIEWER)
    assert user_can(viewer, "view", rwanda)
    assert not user_can(viewer, "decline", rwanda)
    assert not user_can(viewer, "endorse", rwanda)
    assert not user_can(viewer, "final_approve", rwanda)


def test_platform_admin_can_do_everything(users, projects):
    _, _, admin, _ = users
    rwanda, kalro = projects
    for uc in (rwanda, kalro):
        assert user_can(admin, "decline", uc)
        assert user_can(admin, "endorse", uc)
        assert user_can(admin, "final_approve", uc)
        assert user_can(admin, "view", uc)
    assert user_can(admin, "manage_config")
    assert user_can(admin, "manage_users")


def test_non_admin_cannot_manage_config(users, projects):
    coord, _, _, _ = users
    rwanda, _ = projects
    UseCaseMembership.objects.create(user=coord, project=rwanda, role=Role.TRIAL_COORDINATOR)
    assert not user_can(coord, "manage_config")


def test_inactive_user_denied(django_user_model, projects):
    rwanda, _ = projects
    pending = django_user_model.objects.create_user("pending@x.org", "pw")  # is_active=False
    UseCaseMembership.objects.create(user=pending, project=rwanda, role=Role.TRIAL_COORDINATOR)
    assert not user_can(pending, "view", rwanda)


def test_visible_projects_scoping(users, projects):
    coord, _, admin, _ = users
    rwanda, kalro = projects
    UseCaseMembership.objects.create(user=coord, project=rwanda, role=Role.TRIAL_COORDINATOR)

    coord_visible = set(visible_projects(coord).values_list("code", flat=True))
    assert coord_visible == {"SNS-RWANDA"}

    admin_visible = set(visible_projects(admin).values_list("code", flat=True))
    assert admin_visible == {"SNS-RWANDA", "KALRO"}


def test_unknown_action_raises(users, projects):
    _, _, _, viewer = users
    rwanda, _ = projects
    with pytest.raises(ValueError):
        user_can(viewer, "frobnicate", rwanda)
