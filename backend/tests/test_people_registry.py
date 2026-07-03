"""People registry: platform UserID stamping, geo hierarchy, expanded roles.

Proves Stage 1 of making this platform the identity registry — every user gets
a stable UserID for stamping submissions, use cases hang off a Region → Country
hierarchy, and the coordinator/quality roles map to the right review actions.
"""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.projects.models import Country, Project, Region
from apps.rbac.models import Role, UseCaseMembership
from apps.rbac.permissions import user_can, visible_projects

pytestmark = pytest.mark.django_db


def test_user_id_auto_generated(django_user_model):
    u = django_user_model.objects.create_user("a@x.org", "pw")
    assert u.user_id
    assert u.user_id.startswith("U-")
    assert len(u.user_id) == 10  # "U-" + 8 hex


def test_user_id_is_unique_across_users(django_user_model):
    ids = {
        django_user_model.objects.create_user(f"u{i}@x.org", "pw").user_id
        for i in range(25)
    }
    assert len(ids) == 25  # no collisions


def test_user_id_preserved_on_resave(django_user_model):
    u = django_user_model.objects.create_user("b@x.org", "pw")
    original = u.user_id
    u.full_name = "Changed"
    u.save()
    u.refresh_from_db()
    assert u.user_id == original


def test_explicit_user_id_respected(django_user_model):
    u = django_user_model.objects.create_user("c@x.org", "pw", user_id="U-CUSTOM01")
    assert u.user_id == "U-CUSTOM01"


def test_geo_hierarchy_links_region_country_project():
    region = Region.objects.create(code="WAS", name="West Africa & Sahel")
    country = Country.objects.create(region=region, code="NG", name="Nigeria")
    uc = Project.objects.create(code="BIOSSA", name="BioSSA", country=country)

    assert uc.country == country
    assert country.region == region
    assert list(region.countries.all()) == [country]
    assert list(country.projects.all()) == [uc]


def test_project_country_optional():
    uc = Project.objects.create(code="NOGEO", name="No geo")
    assert uc.country is None


def test_country_unique_per_region():
    r = Region.objects.create(code="EA", name="East Africa")
    Country.objects.create(region=r, code="KE", name="Kenya")
    with pytest.raises(IntegrityError):
        Country.objects.create(region=r, code="KE", name="Kenya duplicate")


@pytest.fixture
def project():
    return Project.objects.create(code="SNS-RWANDA", name="SNS Rwanda")


def test_country_coordinator_has_coordinator_powers(django_user_model, project):
    u = django_user_model.objects.create_user("cc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, project=project, role=Role.COUNTRY_COORDINATOR)
    # A Regional covers this use case, so Gate 2 belongs to them.
    reg = django_user_model.objects.create_user("reg@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=reg, project=project, role=Role.REGIONAL_COORDINATOR)
    assert user_can(u, "decline", project)
    assert user_can(u, "edit", project)
    assert user_can(u, "endorse", project)  # Gate 1
    assert not user_can(u, "final_approve", project)  # Gate 2 is the Regional's


def test_country_coordinator_validates_when_no_regional(django_user_model, project):
    u = django_user_model.objects.create_user("cc-solo@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, project=project, role=Role.COUNTRY_COORDINATOR)
    # No Regional assigned -> the Country Coordinator may validate (fallback).
    assert user_can(u, "final_approve", project)


def test_regional_coordinator_has_coordinator_powers(django_user_model, project):
    u = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, project=project, role=Role.REGIONAL_COORDINATOR)
    assert user_can(u, "sync", project)
    assert user_can(u, "request_edit", project)


def test_trial_coordinator_is_gate1_reviewer(django_user_model, project):
    u = django_user_model.objects.create_user("tc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, project=project, role=Role.TRIAL_COORDINATOR)
    # Gate 1 reviewer: full workflow + endorse + sync, but not final validation.
    for action in ("view", "open_review", "request_edit", "edit", "decline", "endorse", "sync"):
        assert user_can(u, action, project), action
    assert not user_can(u, "final_approve", project)


def test_regional_coordinator_is_gate2_validator(django_user_model, project):
    u = django_user_model.objects.create_user("rc2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, project=project, role=Role.REGIONAL_COORDINATOR)
    assert user_can(u, "final_approve", project)  # Gate 2
    assert not user_can(u, "endorse", project)    # not Gate 1


def test_enumerator_is_read_only(django_user_model, project):
    u = django_user_model.objects.create_user("en@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, project=project, role=Role.ENUMERATOR)
    assert user_can(u, "view", project)
    assert not user_can(u, "edit", project)
    assert not user_can(u, "endorse", project)
    assert not user_can(u, "final_approve", project)


# --- Hierarchical membership scoping (Stage 2) ---


@pytest.fixture
def geo_projects():
    """Two countries in one region, each with a use case; plus an unrelated region."""
    region = Region.objects.create(code="EA", name="East Africa")
    rwanda = Country.objects.create(region=region, code="RW", name="Rwanda")
    kenya = Country.objects.create(region=region, code="KE", name="Kenya")
    other_region = Region.objects.create(code="WA", name="West Africa")
    nigeria = Country.objects.create(region=other_region, code="NG", name="Nigeria")

    uc_rw = Project.objects.create(code="SNS-RWANDA", name="SNS Rwanda", country=rwanda)
    uc_ke = Project.objects.create(code="KALRO", name="KALRO", country=kenya)
    uc_ng = Project.objects.create(code="BIOSSA", name="BioSSA", country=nigeria)
    return {
        "region": region, "other_region": other_region,
        "rwanda": rwanda, "kenya": kenya, "nigeria": nigeria,
        "uc_rw": uc_rw, "uc_ke": uc_ke, "uc_ng": uc_ng,
    }


def test_country_grant_cascades_to_its_projects(django_user_model, geo_projects):
    cc = django_user_model.objects.create_user("cc2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(
        user=cc, country=geo_projects["rwanda"], role=Role.COUNTRY_COORDINATOR
    )
    # Cascades to the Rwanda use case...
    assert user_can(cc, "edit", geo_projects["uc_rw"])
    # ...but not Kenya (same region, different country) or Nigeria.
    assert not user_can(cc, "edit", geo_projects["uc_ke"])
    assert not user_can(cc, "view", geo_projects["uc_ng"])

    visible = set(visible_projects(cc).values_list("code", flat=True))
    assert visible == {"SNS-RWANDA"}


def test_region_grant_cascades_to_all_countries(django_user_model, geo_projects):
    rc = django_user_model.objects.create_user("rc2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(
        user=rc, region=geo_projects["region"], role=Role.REGIONAL_COORDINATOR
    )
    # Both use cases in the region are reachable...
    assert user_can(rc, "sync", geo_projects["uc_rw"])
    assert user_can(rc, "sync", geo_projects["uc_ke"])
    # ...but the other region's use case is not.
    assert not user_can(rc, "view", geo_projects["uc_ng"])

    visible = set(visible_projects(rc).values_list("code", flat=True))
    assert visible == {"SNS-RWANDA", "KALRO"}


def test_direct_project_grant_still_works(django_user_model, geo_projects):
    u = django_user_model.objects.create_user("d2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(
        user=u, project=geo_projects["uc_ke"], role=Role.TRIAL_COORDINATOR
    )
    assert user_can(u, "edit", geo_projects["uc_ke"])
    assert not user_can(u, "edit", geo_projects["uc_rw"])
    assert set(visible_projects(u).values_list("code", flat=True)) == {"KALRO"}


def test_membership_requires_exactly_one_scope(django_user_model, geo_projects):
    from django.db import IntegrityError as IE

    u = django_user_model.objects.create_user("bad@x.org", "pw", is_active=True)
    # Two scopes set at once violates the check constraint.
    with pytest.raises(IE):
        UseCaseMembership.objects.create(
            user=u, project=geo_projects["uc_rw"], country=geo_projects["rwanda"],
            role=Role.VIEWER,
        )


def test_membership_no_scope_rejected(django_user_model):
    from django.db import IntegrityError as IE

    u = django_user_model.objects.create_user("bad2@x.org", "pw", is_active=True)
    with pytest.raises(IE):
        UseCaseMembership.objects.create(user=u, role=Role.VIEWER)
