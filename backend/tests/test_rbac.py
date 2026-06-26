"""RBAC scoping tests — a role grant in one use case must not leak to another."""
from __future__ import annotations

import pytest

from apps.rbac.models import Role, UseCaseMembership
from apps.rbac.permissions import user_can, visible_use_cases
from apps.usecases.models import UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def users(django_user_model):
    coord = django_user_model.objects.create_user("coord@x.org", "pw", is_active=True)
    qc = django_user_model.objects.create_user("qc@x.org", "pw", is_active=True)
    admin = django_user_model.objects.create_superuser("admin@x.org", "pw")
    viewer = django_user_model.objects.create_user("viewer@x.org", "pw", is_active=True)
    return coord, qc, admin, viewer


@pytest.fixture
def use_cases():
    rwanda = UseCase.objects.create(code="SNS-RWANDA", name="SNS Rwanda")
    kalro = UseCase.objects.create(code="KALRO", name="KALRO")
    return rwanda, kalro


def test_coordinator_scoped_to_their_use_case(users, use_cases):
    coord, _, _, _ = users
    rwanda, kalro = use_cases
    UseCaseMembership.objects.create(user=coord, use_case=rwanda, role=Role.TRIAL_COORDINATOR)

    # Can act on Rwanda...
    assert user_can(coord, "decline", rwanda)
    assert user_can(coord, "request_edit", rwanda)
    assert user_can(coord, "edit", rwanda)
    assert user_can(coord, "view", rwanda)
    # ...but NOT on KALRO (no membership there).
    assert not user_can(coord, "decline", kalro)
    assert not user_can(coord, "view", kalro)


def test_gate1_coordinator_endorses_not_validates(users, use_cases):
    """Trial Coordinator = Gate 1: reviews and endorses, but cannot finally validate."""
    coord, _, _, _ = users
    rwanda, _ = use_cases
    UseCaseMembership.objects.create(user=coord, use_case=rwanda, role=Role.TRIAL_COORDINATOR)
    for action in ("view", "open_review", "request_edit", "edit", "decline", "endorse", "sync"):
        assert user_can(coord, action, rwanda), action
    assert not user_can(coord, "final_approve", rwanda)  # Gate 2 is Regional's


def test_country_coordinator_is_gate1(users, use_cases):
    _, person, _, _ = users
    rwanda, _ = use_cases
    UseCaseMembership.objects.create(user=person, use_case=rwanda, role=Role.COUNTRY_COORDINATOR)
    assert user_can(person, "endorse", rwanda)
    assert not user_can(person, "final_approve", rwanda)


def test_regional_coordinator_is_gate2(users, use_cases):
    """Regional Coordinator = Gate 2: the final validation, and not a Gate-1 endorser."""
    _, _, _, person = users
    rwanda, _ = use_cases
    UseCaseMembership.objects.create(user=person, use_case=rwanda, role=Role.REGIONAL_COORDINATOR)
    assert user_can(person, "final_approve", rwanda)
    assert user_can(person, "decline", rwanda)  # can still send back / decline
    assert not user_can(person, "endorse", rwanda)  # endorsement is Gate 1's


def test_viewer_is_read_only(users, use_cases):
    _, _, _, viewer = users
    rwanda, _ = use_cases
    UseCaseMembership.objects.create(user=viewer, use_case=rwanda, role=Role.VIEWER)
    assert user_can(viewer, "view", rwanda)
    assert not user_can(viewer, "decline", rwanda)
    assert not user_can(viewer, "endorse", rwanda)
    assert not user_can(viewer, "final_approve", rwanda)


def test_platform_admin_can_do_everything(users, use_cases):
    _, _, admin, _ = users
    rwanda, kalro = use_cases
    for uc in (rwanda, kalro):
        assert user_can(admin, "decline", uc)
        assert user_can(admin, "endorse", uc)
        assert user_can(admin, "final_approve", uc)
        assert user_can(admin, "view", uc)
    assert user_can(admin, "manage_config")
    assert user_can(admin, "manage_users")


def test_non_admin_cannot_manage_config(users, use_cases):
    coord, _, _, _ = users
    rwanda, _ = use_cases
    UseCaseMembership.objects.create(user=coord, use_case=rwanda, role=Role.TRIAL_COORDINATOR)
    assert not user_can(coord, "manage_config")


def test_inactive_user_denied(django_user_model, use_cases):
    rwanda, _ = use_cases
    pending = django_user_model.objects.create_user("pending@x.org", "pw")  # is_active=False
    UseCaseMembership.objects.create(user=pending, use_case=rwanda, role=Role.TRIAL_COORDINATOR)
    assert not user_can(pending, "view", rwanda)


def test_visible_use_cases_scoping(users, use_cases):
    coord, _, admin, _ = users
    rwanda, kalro = use_cases
    UseCaseMembership.objects.create(user=coord, use_case=rwanda, role=Role.TRIAL_COORDINATOR)

    coord_visible = set(visible_use_cases(coord).values_list("code", flat=True))
    assert coord_visible == {"SNS-RWANDA"}

    admin_visible = set(visible_use_cases(admin).values_list("code", flat=True))
    assert admin_visible == {"SNS-RWANDA", "KALRO"}


def test_unknown_action_raises(users, use_cases):
    _, _, _, viewer = users
    rwanda, _ = use_cases
    with pytest.raises(ValueError):
        user_can(viewer, "frobnicate", rwanda)
