"""Feature C, Stage C3: Quality + Enumerator + Coverage detail dashboards."""
from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from apps.fieldwork.models import CollectionUnit
from apps.kpi.metrics import coverage_metrics, enumerator_metrics, quality_metrics
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Role, UseCaseMembership
from apps.review.models import Review, ReviewState
from apps.submissions.models import Enumerator, Submission
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="Project A", organization=org)
    other = Project.objects.create(code="PROJ-B", name="Project B", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=11,
                                         role=FormDefinition.Role.VALIDATION)
    en1 = Enumerator.objects.create(project=uc, enid="EN-1", first_name="Ana")
    en2 = Enumerator.objects.create(project=uc, enid="EN-2")

    # Two geo-located units; only u1 gets data (collected), u2 stays pending.
    u1 = CollectionUnit.objects.create(project=uc, code="U1", name="Plot 1",
                                       lat="1.0", lon="2.0")
    CollectionUnit.objects.create(project=uc, code="U2", name="Plot 2",
                                  lat="1.1", lon="2.1")

    rule = ValidationRule.objects.create(project=uc, code="id-format",
                                         rule_type=ValidationRule.RuleType.REGEX_ID,
                                         severity=ValidationRule.Severity.ERROR)
    for i in range(4):
        s = Submission.objects.create(project=uc, form=form, ona_uuid=f"a-{i}",
                                      content_hash="h", enumerator=en1,
                                      collection_unit=u1, event_date=date.today())
        if i == 0:
            Review.objects.filter(submission=s).update(state=ReviewState.APPROVED)
        if i < 2:
            ValidationFlag.objects.create(submission=s, rule=rule, message="bad id",
                                          severity=ValidationRule.Severity.ERROR,
                                          status=ValidationFlag.Status.OPEN, field_key=f"f{i}")
    Submission.objects.create(project=uc, form=form, ona_uuid="a-x",
                              content_hash="h", enumerator=en2, event_date=date.today())

    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    return {"uc": uc, "other": other, "coord": coord}


def test_quality_metrics(world):
    m = quality_metrics(world["uc"], "30")
    assert m["open_flags"] == 2
    assert m["heatmap"][0]["code"] == "id-format"
    assert m["heatmap"][0]["total"] == 2
    # ERROR is the first severity column and holds both flags.
    assert m["heatmap"][0]["cells"][0]["n"] == 2


def test_enumerator_metrics(world):
    m = enumerator_metrics(world["uc"], "30")
    top = m["leaderboard"][0]
    assert top["enumerator__enid"] == "EN-1"
    assert top["n"] == 4
    assert top["approved"] == 1
    assert top["open_flags"] == 2
    assert m["active_count"] == 2
    # Only the collected, geo-located unit shows as a point.
    assert len(m["points"]) == 1


def test_coverage_metrics(world):
    m = coverage_metrics(world["uc"])
    assert m["total_units"] == 2
    assert m["collected_units"] == 1
    assert m["pending_units"] == 1
    assert m["coverage_pct"] == 50
    assert len(m["points"]) == 2          # both units are geo-located


@pytest.mark.parametrize("name", ["quality", "enumerators", "coverage"])
def test_detail_views_member_ok_nonmember_404(client, world, name):
    client.force_login(world["coord"])
    assert client.get(reverse(f"kpi:{name}", args=["PROJ-A"])).status_code == 200
    assert client.get(reverse(f"kpi:{name}", args=["PROJ-B"])).status_code == 404


def test_quality_view_renders_heatmap(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:quality", args=["PROJ-A"]))
    assert resp.status_code == 200
    assert b"id-format" in resp.content
