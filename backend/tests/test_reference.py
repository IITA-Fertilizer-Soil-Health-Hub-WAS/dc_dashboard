"""Reference datasets: import, reconciliation coverage, and the reference /
lab-consistency / media validation rules."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import (
    FormDefinition,
    Organization,
    Project,
    ReferenceDataset,
)
from apps.projects.reference import import_reference_csv, reconcile
from apps.rbac.models import Membership, Role
from apps.submissions.models import Submission, SubmissionValue
from apps.validation import rules

pytestmark = pytest.mark.django_db


@pytest.fixture
def proj(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    FormDefinition.objects.create(project=p, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    Membership.objects.create(user=coord, project=p, role=Role.TRIAL_COORDINATOR)
    return {"p": p, "admin": admin, "coord": coord}


def _sub(project, uuid, values, media=None):
    s = Submission.objects.create(project=project, form=project.forms.first(),
                                  ona_uuid=uuid, content_hash=uuid,
                                  media_hashes=media or [])
    for k, v in values.items():
        SubmissionValue.objects.create(submission=s, field_key=k, raw_value=str(v),
                                       current_value=str(v))
    return s


FRAME = "sample_id,ph,expected_n\nS1,6.5,10\nS2,7.0,12\nS3,5.8,9\n"


def test_import_and_reconcile(proj):
    ds = import_reference_csv(proj["p"], code="frame", name="Frame", kind="SAMPLING_FRAME",
                              key_field="sample_id", text=FRAME)
    assert ds.row_count == 3 and ds.columns == ["sample_id", "ph", "expected_n"]
    _sub(proj["p"], "a", {"sid": "S1"})
    _sub(proj["p"], "b", {"sid": "S2"})
    _sub(proj["p"], "c", {"sid": "S9"})   # not in frame
    cov = reconcile(ds, "sid")
    assert cov["matched"] == 2 and cov["missing_n"] == 1        # S3 never submitted
    assert cov["unknown_n"] == 1 and cov["unknown"] == ["S9"]   # S9 not in frame
    assert cov["coverage_pct"] == pytest.approx(66.7, abs=0.1)


def test_reference_match_rule(proj):
    import_reference_csv(proj["p"], code="frame", name="Frame", kind="LOOKUP",
                         key_field="sample_id", text=FRAME)
    good = _sub(proj["p"], "g", {"sid": "S1"})
    bad = _sub(proj["p"], "b", {"sid": "TYPO9"})
    fired = {r.submission_id for r in rules.reference_match(
        proj["p"], {"field": "sid", "dataset": "frame"})}
    assert bad.id in fired and good.id not in fired


def test_reference_compare_lab_consistency(proj):
    import_reference_csv(proj["p"], code="lab", name="Lab", kind="LAB_RESULTS",
                         key_field="sample_id", text=FRAME)
    ok = _sub(proj["p"], "ok", {"sid": "S1", "field_ph": "6.5"})     # matches lab 6.5
    off = _sub(proj["p"], "off", {"sid": "S2", "field_ph": "9.9"})   # lab says 7.0
    params = {"key_field": "sid", "dataset": "lab", "ref_column": "ph",
              "field": "field_ph", "compare": "eq", "tol": 0.3}
    fired = {r.submission_id for r in rules.reference_compare(proj["p"], params)}
    assert off.id in fired and ok.id not in fired


def test_media_required_rule(proj):
    withphoto = _sub(proj["p"], "w", {"x": "1"}, media=["abc"])
    nophoto = _sub(proj["p"], "n", {"x": "1"}, media=[])
    assert rules.media_required(nophoto, {"min": 1})
    assert not rules.media_required(withphoto, {"min": 1})


def test_reference_views(client, proj):
    ds = import_reference_csv(proj["p"], code="frame", name="Frame", kind="SAMPLING_FRAME",
                              key_field="sample_id", text=FRAME)
    client.force_login(proj["admin"])
    s = client.session
    s["active_project"] = proj["p"].code
    s.save()
    lst = client.get(reverse("console:reference_datasets") + f"?project={proj['p'].code}")
    assert lst.status_code == 200 and "Frame" in lst.content.decode()
    cov = client.get(reverse("console:reference_coverage", args=[ds.pk]) + "?field=sid")
    assert cov.status_code == 200 and "Coverage" in cov.content.decode()


def test_reference_import_bad_key_column(proj):
    with pytest.raises(ValueError):
        import_reference_csv(proj["p"], code="x", name="X", kind="LOOKUP",
                             key_field="not_a_column", text=FRAME)
