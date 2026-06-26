"""People registry: platform UserID stamping, geo hierarchy, expanded roles.

Proves Stage 1 of making this platform the identity registry — every user gets
a stable UserID for stamping submissions, use cases hang off a Region → Country
hierarchy, and the coordinator/quality roles map to the right review actions.
"""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.rbac.models import Role, UseCaseMembership
from apps.rbac.permissions import user_can, visible_use_cases
from apps.usecases.models import Country, Region, UseCase

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


def test_geo_hierarchy_links_region_country_use_case():
    region = Region.objects.create(code="WAS", name="West Africa & Sahel")
    country = Country.objects.create(region=region, code="NG", name="Nigeria")
    uc = UseCase.objects.create(code="BIOSSA", name="BioSSA", country=country)

    assert uc.country == country
    assert country.region == region
    assert list(region.countries.all()) == [country]
    assert list(country.use_cases.all()) == [uc]


def test_use_case_country_optional():
    uc = UseCase.objects.create(code="NOGEO", name="No geo")
    assert uc.country is None


def test_country_unique_per_region():
    r = Region.objects.create(code="EA", name="East Africa")
    Country.objects.create(region=r, code="KE", name="Kenya")
    with pytest.raises(IntegrityError):
        Country.objects.create(region=r, code="KE", name="Kenya duplicate")


@pytest.fixture
def use_case():
    return UseCase.objects.create(code="SNS-RWANDA", name="SNS Rwanda")


def test_country_coordinator_has_coordinator_powers(django_user_model, use_case):
    u = django_user_model.objects.create_user("cc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, use_case=use_case, role=Role.COUNTRY_COORDINATOR)
    assert user_can(u, "decline", use_case)
    assert user_can(u, "edit", use_case)
    assert user_can(u, "qc_approve", use_case)  # coordinators can approve too


def test_regional_coordinator_has_coordinator_powers(django_user_model, use_case):
    u = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, use_case=use_case, role=Role.REGIONAL_COORDINATOR)
    assert user_can(u, "sync", use_case)
    assert user_can(u, "request_edit", use_case)


def test_survey_domain_expert_is_full_reviewer(django_user_model, use_case):
    u = django_user_model.objects.create_user("sde@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, use_case=use_case, role=Role.SURVEY_DOMAIN_EXPERT)
    # Domain experts review end to end now — open, request edit, edit, decline, approve.
    for action in ("view", "open_review", "request_edit", "edit", "decline", "qc_approve"):
        assert user_can(u, action, use_case), action
    assert not user_can(u, "sync", use_case)  # ops stays with coordinators


def test_enumerator_is_read_only(django_user_model, use_case):
    u = django_user_model.objects.create_user("en@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, use_case=use_case, role=Role.ENUMERATOR)
    assert user_can(u, "view", use_case)
    assert not user_can(u, "edit", use_case)
    assert not user_can(u, "qc_approve", use_case)


# --- Hierarchical membership scoping (Stage 2) ---


@pytest.fixture
def geo_use_cases():
    """Two countries in one region, each with a use case; plus an unrelated region."""
    region = Region.objects.create(code="EA", name="East Africa")
    rwanda = Country.objects.create(region=region, code="RW", name="Rwanda")
    kenya = Country.objects.create(region=region, code="KE", name="Kenya")
    other_region = Region.objects.create(code="WA", name="West Africa")
    nigeria = Country.objects.create(region=other_region, code="NG", name="Nigeria")

    uc_rw = UseCase.objects.create(code="SNS-RWANDA", name="SNS Rwanda", country=rwanda)
    uc_ke = UseCase.objects.create(code="KALRO", name="KALRO", country=kenya)
    uc_ng = UseCase.objects.create(code="BIOSSA", name="BioSSA", country=nigeria)
    return {
        "region": region, "other_region": other_region,
        "rwanda": rwanda, "kenya": kenya, "nigeria": nigeria,
        "uc_rw": uc_rw, "uc_ke": uc_ke, "uc_ng": uc_ng,
    }


def test_country_grant_cascades_to_its_use_cases(django_user_model, geo_use_cases):
    cc = django_user_model.objects.create_user("cc2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(
        user=cc, country=geo_use_cases["rwanda"], role=Role.COUNTRY_COORDINATOR
    )
    # Cascades to the Rwanda use case...
    assert user_can(cc, "edit", geo_use_cases["uc_rw"])
    # ...but not Kenya (same region, different country) or Nigeria.
    assert not user_can(cc, "edit", geo_use_cases["uc_ke"])
    assert not user_can(cc, "view", geo_use_cases["uc_ng"])

    visible = set(visible_use_cases(cc).values_list("code", flat=True))
    assert visible == {"SNS-RWANDA"}


def test_region_grant_cascades_to_all_countries(django_user_model, geo_use_cases):
    rc = django_user_model.objects.create_user("rc2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(
        user=rc, region=geo_use_cases["region"], role=Role.REGIONAL_COORDINATOR
    )
    # Both use cases in the region are reachable...
    assert user_can(rc, "sync", geo_use_cases["uc_rw"])
    assert user_can(rc, "sync", geo_use_cases["uc_ke"])
    # ...but the other region's use case is not.
    assert not user_can(rc, "view", geo_use_cases["uc_ng"])

    visible = set(visible_use_cases(rc).values_list("code", flat=True))
    assert visible == {"SNS-RWANDA", "KALRO"}


def test_direct_use_case_grant_still_works(django_user_model, geo_use_cases):
    u = django_user_model.objects.create_user("d2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(
        user=u, use_case=geo_use_cases["uc_ke"], role=Role.TRIAL_COORDINATOR
    )
    assert user_can(u, "edit", geo_use_cases["uc_ke"])
    assert not user_can(u, "edit", geo_use_cases["uc_rw"])
    assert set(visible_use_cases(u).values_list("code", flat=True)) == {"KALRO"}


def test_membership_requires_exactly_one_scope(django_user_model, geo_use_cases):
    from django.db import IntegrityError as IE

    u = django_user_model.objects.create_user("bad@x.org", "pw", is_active=True)
    # Two scopes set at once violates the check constraint.
    with pytest.raises(IE):
        UseCaseMembership.objects.create(
            user=u, use_case=geo_use_cases["uc_rw"], country=geo_use_cases["rwanda"],
            role=Role.VIEWER,
        )


def test_membership_no_scope_rejected(django_user_model):
    from django.db import IntegrityError as IE

    u = django_user_model.objects.create_user("bad2@x.org", "pw", is_active=True)
    with pytest.raises(IE):
        UseCaseMembership.objects.create(user=u, role=Role.VIEWER)
