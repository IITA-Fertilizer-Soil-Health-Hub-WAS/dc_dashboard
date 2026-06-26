"""People registry: platform UserID stamping, geo hierarchy, expanded roles.

Proves Stage 1 of making this platform the identity registry — every user gets
a stable UserID for stamping submissions, use cases hang off a Region → Country
hierarchy, and the coordinator/quality roles map to the right review actions.
"""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.rbac.models import Role, UseCaseMembership
from apps.rbac.permissions import user_can
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
    assert not user_can(u, "qc_approve", use_case)


def test_regional_coordinator_has_coordinator_powers(django_user_model, use_case):
    u = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, use_case=use_case, role=Role.REGIONAL_COORDINATOR)
    assert user_can(u, "sync", use_case)
    assert user_can(u, "request_edit", use_case)


def test_survey_domain_expert_is_quality(django_user_model, use_case):
    u = django_user_model.objects.create_user("sde@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, use_case=use_case, role=Role.SURVEY_DOMAIN_EXPERT)
    assert user_can(u, "qc_approve", use_case)
    assert user_can(u, "view", use_case)
    assert not user_can(u, "decline", use_case)


def test_enumerator_is_read_only(django_user_model, use_case):
    u = django_user_model.objects.create_user("en@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, use_case=use_case, role=Role.ENUMERATOR)
    assert user_can(u, "view", use_case)
    assert not user_can(u, "edit", use_case)
    assert not user_can(u, "qc_approve", use_case)
