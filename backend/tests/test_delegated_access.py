"""Delegated administration: coordinators grant access only within their scope.

The security core — a coordinator must never be able to grant outside their
geographic authority or above their own role rank. Tests cover both the
permission helpers and the Team views end-to-end (including tamper attempts).
"""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Country, Project, Region
from apps.rbac.models import Membership, Role
from apps.rbac.permissions import (
    can_grant,
    can_manage_access,
    grantable_roles,
    manageable_memberships,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def geo():
    ea = Region.objects.create(code="EA", name="East Africa")
    wa = Region.objects.create(code="WA", name="West Africa")
    rwanda = Country.objects.create(region=ea, code="RW", name="Rwanda")
    kenya = Country.objects.create(region=ea, code="KE", name="Kenya")
    nigeria = Country.objects.create(region=wa, code="NG", name="Nigeria")
    return {
        "ea": ea, "wa": wa, "rwanda": rwanda, "kenya": kenya, "nigeria": nigeria,
        "uc_rw": Project.objects.create(code="SNS-RW", name="SNS Rwanda", country=rwanda),
        "uc_ke": Project.objects.create(code="KALRO", name="KALRO", country=kenya),
        "uc_ng": Project.objects.create(code="BIOSSA", name="BioSSA", country=nigeria),
    }


def _user(dj, email, active=True):
    return dj.objects.create_user(email, "pw", is_active=active)


# --- Scope authority ---


def test_country_coordinator_can_grant_within_country(django_user_model, geo):
    cc = _user(django_user_model, "cc@x.org")
    Membership.objects.create(user=cc, country=geo["rwanda"], role=Role.COUNTRY_COORDINATOR)
    assert can_grant(cc, geo["uc_rw"], Role.ENUMERATOR)  # project in their country
    assert can_grant(cc, geo["rwanda"], Role.TRIAL_COORDINATOR)  # the country itself
    # Not another country, nor a project elsewhere, nor the region above them.
    assert not can_grant(cc, geo["uc_ke"], Role.VIEWER)
    assert not can_grant(cc, geo["kenya"], Role.VIEWER)
    assert not can_grant(cc, geo["ea"], Role.VIEWER)


def test_regional_coordinator_spans_region(django_user_model, geo):
    rc = _user(django_user_model, "rc@x.org")
    Membership.objects.create(user=rc, region=geo["ea"], role=Role.REGIONAL_COORDINATOR)
    assert can_grant(rc, geo["uc_rw"], Role.ENUMERATOR)
    assert can_grant(rc, geo["uc_ke"], Role.COUNTRY_COORDINATOR)
    assert can_grant(rc, geo["kenya"], Role.COUNTRY_COORDINATOR)
    # The other region is out of bounds.
    assert not can_grant(rc, geo["uc_ng"], Role.VIEWER)
    assert not can_grant(rc, geo["wa"], Role.VIEWER)


def test_trial_coordinator_limited_to_one_project(django_user_model, geo):
    tc = _user(django_user_model, "tc@x.org")
    Membership.objects.create(user=tc, project=geo["uc_rw"], role=Role.TRIAL_COORDINATOR)
    assert can_grant(tc, geo["uc_rw"], Role.ENUMERATOR)
    assert not can_grant(tc, geo["uc_ke"], Role.ENUMERATOR)
    assert not can_grant(tc, geo["rwanda"], Role.ENUMERATOR)  # cannot widen to the country


# --- Role ceiling ---


def test_role_ceiling_blocks_upgrading_above_self(django_user_model, geo):
    cc = _user(django_user_model, "cc2@x.org")
    Membership.objects.create(user=cc, country=geo["rwanda"], role=Role.COUNTRY_COORDINATOR)
    # Equal + below allowed...
    assert can_grant(cc, geo["uc_rw"], Role.COUNTRY_COORDINATOR)
    assert can_grant(cc, geo["uc_rw"], Role.TRIAL_COORDINATOR)
    # ...but never above (Regional) nor Platform Admin.
    assert not can_grant(cc, geo["uc_rw"], Role.REGIONAL_COORDINATOR)
    assert not can_grant(cc, geo["uc_rw"], Role.PLATFORM_ADMIN)


def test_grantable_roles_capped_at_own_rank(django_user_model, geo):
    tc = _user(django_user_model, "tc2@x.org")
    Membership.objects.create(user=tc, project=geo["uc_rw"], role=Role.TRIAL_COORDINATOR)
    roles = set(grantable_roles(tc))
    assert Role.TRIAL_COORDINATOR in roles
    assert Role.ENUMERATOR in roles
    assert Role.REGIONAL_COORDINATOR not in roles
    assert Role.PLATFORM_ADMIN not in roles


def test_non_coordinator_cannot_manage_access(django_user_model, geo):
    viewer = _user(django_user_model, "v@x.org")
    Membership.objects.create(user=viewer, project=geo["uc_rw"], role=Role.VIEWER)
    assert not can_manage_access(viewer)
    assert grantable_roles(viewer) == []
    assert not can_grant(viewer, geo["uc_rw"], Role.VIEWER)


def test_platform_admin_can_grant_anything(django_user_model, geo):
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    assert can_manage_access(admin)
    assert can_grant(admin, geo["uc_ng"], Role.REGIONAL_COORDINATOR)
    assert not can_grant(admin, geo["uc_ng"], Role.PLATFORM_ADMIN)  # superuser flag, not via UI


# --- Manageable set (revocation authority) ---


def test_manageable_memberships_scoped(django_user_model, geo):
    cc = _user(django_user_model, "cc3@x.org")
    Membership.objects.create(user=cc, country=geo["rwanda"], role=Role.COUNTRY_COORDINATOR)
    other = _user(django_user_model, "other@x.org")
    in_scope = Membership.objects.create(user=other, project=geo["uc_rw"], role=Role.VIEWER)
    out_scope = Membership.objects.create(user=other, project=geo["uc_ke"], role=Role.VIEWER)

    pks = set(manageable_memberships(cc).values_list("pk", flat=True))
    assert in_scope.pk in pks
    assert out_scope.pk not in pks


# --- Views end-to-end ---


def test_approve_pending_user_via_view(client, django_user_model, geo):
    cc = _user(django_user_model, "cc4@x.org")
    Membership.objects.create(user=cc, country=geo["rwanda"], role=Role.COUNTRY_COORDINATOR)
    pending = _user(django_user_model, "newbie@x.org", active=False)
    client.force_login(cc)

    resp = client.post(reverse("dashboards:team_grant"), {
        "user": str(pending.pk),
        "scope": f"project:{geo['uc_rw'].pk}",
        "role": Role.ENUMERATOR,
    })
    assert resp.status_code == 302
    pending.refresh_from_db()
    assert pending.is_active is True
    assert pending.approved_by == cc
    assert Membership.objects.filter(
        user=pending, project=geo["uc_rw"], role=Role.ENUMERATOR
    ).exists()


def test_view_rejects_out_of_scope_grant(client, django_user_model, geo):
    cc = _user(django_user_model, "cc5@x.org")
    Membership.objects.create(user=cc, country=geo["rwanda"], role=Role.COUNTRY_COORDINATOR)
    target = _user(django_user_model, "t@x.org", active=False)
    client.force_login(cc)

    # Tamper: try to grant on a project in another country.
    resp = client.post(reverse("dashboards:team_grant"), {
        "user": str(target.pk),
        "scope": f"project:{geo['uc_ke'].pk}",
        "role": Role.VIEWER,
    })
    assert resp.status_code == 403
    target.refresh_from_db()
    assert target.is_active is False  # not approved
    assert not Membership.objects.filter(user=target).exists()


def test_view_rejects_over_rank_grant(client, django_user_model, geo):
    cc = _user(django_user_model, "cc6@x.org")
    Membership.objects.create(user=cc, country=geo["rwanda"], role=Role.COUNTRY_COORDINATOR)
    target = _user(django_user_model, "t2@x.org")
    client.force_login(cc)

    resp = client.post(reverse("dashboards:team_grant"), {
        "user": str(target.pk),
        "scope": f"project:{geo['uc_rw'].pk}",
        "role": Role.REGIONAL_COORDINATOR,  # above the coordinator's rank
    })
    assert resp.status_code == 403
    assert not Membership.objects.filter(user=target).exists()


def test_view_revoke_only_within_authority(client, django_user_model, geo):
    cc = _user(django_user_model, "cc7@x.org")
    Membership.objects.create(user=cc, country=geo["rwanda"], role=Role.COUNTRY_COORDINATOR)
    victim = _user(django_user_model, "vic@x.org")
    out = Membership.objects.create(user=victim, project=geo["uc_ke"], role=Role.VIEWER)
    client.force_login(cc)

    resp = client.post(reverse("dashboards:team_revoke"), {"membership": str(out.pk)})
    assert resp.status_code == 403
    assert Membership.objects.filter(pk=out.pk).exists()  # not revoked


def test_team_page_denied_for_non_manager(client, django_user_model, geo):
    viewer = _user(django_user_model, "v2@x.org")
    Membership.objects.create(user=viewer, project=geo["uc_rw"], role=Role.VIEWER)
    client.force_login(viewer)
    resp = client.get(reverse("dashboards:team"))
    assert resp.status_code == 403
