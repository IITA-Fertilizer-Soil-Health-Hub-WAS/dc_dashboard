"""The validation engine must not issue a query per field per submission — the
N+1 that would block scaling to the national-database vision."""
from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.projects.models import FormDefinition, Organization, Project
from apps.submissions.models import Submission, SubmissionValue
from apps.validation.engine import run_for_project
from apps.validation.models import ValidationRule

pytestmark = pytest.mark.django_db


def _seed(code, n, fields=5):
    org, _ = Organization.objects.get_or_create(code="o", defaults={"name": "O"})
    p = Project.objects.create(code=code, name=code, organization=org)
    f = FormDefinition.objects.create(project=p, ona_form_id=1,
                                      role=FormDefinition.Role.VALIDATION)
    rows = []
    subs = [Submission(project=p, form=f, ona_uuid=f"{code}-{i}", content_hash=f"{code}-{i}")
            for i in range(n)]
    Submission.objects.bulk_create(subs)
    for s in Submission.objects.filter(project=p):
        for j in range(fields):
            rows.append(SubmissionValue(submission=s, field_key=f"q{j}",
                                        raw_value="1", current_value="1"))
    SubmissionValue.objects.bulk_create(rows)
    # A per-submission rule reading every field — all present, so it flags nothing
    # (isolates read cost from the write cost of creating flags).
    ValidationRule.objects.create(
        project=p, code="req", rule_type="REQUIRED_FIELD",
        params={"fields": [f"q{j}" for j in range(fields)]}, severity="WARNING")
    return p


def _queries(project):
    with CaptureQueriesContext(connection) as ctx:
        run_for_project(project)
    return len(ctx.captured_queries)


def test_validation_query_count_is_flat_in_submissions():
    small = _queries(_seed("SMALL", 5))
    big = _queries(_seed("BIG", 60))
    # 12x the submissions (and 12x the field values) must not mean ~12x the
    # queries — the per-submission field reads come from the in-memory cache.
    assert big - small <= 4, f"query count scaled with data: {small} -> {big}"
