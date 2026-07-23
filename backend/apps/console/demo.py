"""Generate a self-contained demo project so a new user can learn the
review → validation → dashboard flow on realistic (but disposable) data before
touching production. Clearly labelled DEMO and safe to delete.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone


@transaction.atomic
def create_demo_project(owner=None):
    from apps.projects.models import Crop, FormDefinition, Project
    from apps.projects.tenancy import resolve_organization
    from apps.submissions.models import Enumerator, Submission, SubmissionValue
    from apps.validation.engine import run_for_project
    from apps.validation.models import ValidationRule

    org = resolve_organization(None)
    n = Project.objects.filter(code__startswith="DEMO-").count() + 1
    code = f"DEMO-{n}"
    uc = Project.objects.create(code=code, name=f"Demo soil project {n}",
                                organization=org, owner=owner)
    form = FormDefinition.objects.create(
        project=uc, ona_form_id=900000 + n, title="Demo soil survey",
        role=FormDefinition.Role.VALIDATION,
        field_schema=[
            {"path": "sample_id", "label": "Sample ID", "type": "text"},
            {"path": "ph", "label": "Soil pH", "type": "decimal"},
            {"path": "yield_kg", "label": "Yield (kg)", "type": "integer"},
        ])
    Crop.objects.create(project=uc, name="Maize")
    en = Enumerator.objects.create(project=uc, enid="DEMO-EN1",
                                   first_name="Demo", surname="Enumerator")

    now = timezone.now()
    for i in range(24):
        # Seed deliberate quality problems so the rules light up and teach:
        ph = "12.9" if i in (4, 15) else f"{6.3 + (i % 5) * 0.2:.1f}"   # out-of-range pH
        yld = "950" if i == 7 else str(100 + (i % 6))                    # one gross outlier
        sid = "S001" if i == 3 else f"S{i:03d}"                          # one duplicate id
        row = {"sample_id": sid, "ph": ph, "yield_kg": yld}
        s = Submission.objects.create(
            project=uc, form=form, enumerator=en,
            ona_uuid=f"{code}-{i}", content_hash=f"{code}-{i}",
            event_key="Event1", event_date=(now - timedelta(days=i)).date(),
            raw_payload=row)
        for k, v in row.items():
            SubmissionValue.objects.create(submission=s, field_key=k,
                                           raw_value=v, current_value=v)

    ValidationRule.objects.create(project=uc, form=form, code="ph-range",
                                  rule_type="NUMERIC_RANGE",
                                  params={"field": "ph", "min": 3, "max": 10},
                                  severity="WARNING")
    ValidationRule.objects.create(project=uc, form=form, code="unique-sample",
                                  rule_type="UNIQUE_FIELD",
                                  params={"field": "sample_id"}, severity="ERROR")
    ValidationRule.objects.create(project=uc, form=form, code="yield-outlier",
                                  rule_type="NUMERIC_OUTLIER",
                                  params={"field": "yield_kg", "z": 2.5, "min_n": 10},
                                  severity="WARNING")
    run_for_project(uc)
    return uc
