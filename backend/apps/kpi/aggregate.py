"""Rebuild the daily KPI aggregates from ingested submissions.

A submission is attributed to its collection day — the field date if known
(event_date), else the server submission time, else when we ingested it. Rebuild
is idempotent per project (delete + recompute), so it can run on the Beat
schedule or be triggered by a webhook without creating duplicates.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, DateField
from django.db.models.functions import Coalesce, TruncDate

from apps.submissions.models import Submission
from apps.usecases.models import UseCase
from apps.validation.models import ValidationFlag

from .models import EnumeratorKpiDaily, FormKpiDaily, ProjectKpiDaily


def _day_expr(prefix: str = ""):
    """The day a submission counts towards (its field date, else server time,
    else ingest time). `prefix` lets related queries reach through e.g. 'submission__'."""
    return Coalesce(
        f"{prefix}event_date",
        TruncDate(f"{prefix}ona_submission_time"),
        TruncDate(f"{prefix}ingested_at"),
        output_field=DateField(),
    )


_DAY = _day_expr()


@transaction.atomic
def rebuild_use_case_kpis(use_case: UseCase) -> dict[str, int]:
    """Recompute all daily aggregates for one project. Returns row counts."""
    subs = Submission.objects.filter(use_case=use_case)

    # Project per-day: submissions + active (distinct) enumerators.
    proj = (
        subs.annotate(day=_DAY).values("day")
        .annotate(n=Count("id"), enums=Count("enumerator", distinct=True))
    )
    # A flag counts on its submission's collection day (so it lines up with the
    # submission rows, not the day the rule happened to run).
    flags = (
        ValidationFlag.objects.filter(submission__use_case=use_case)
        .annotate(day=_day_expr("submission__"))
        .values("day").annotate(n=Count("id"))
    )
    flags_by_day = {f["day"]: f["n"] for f in flags if f["day"]}

    ProjectKpiDaily.objects.filter(use_case=use_case).delete()
    ProjectKpiDaily.objects.bulk_create([
        ProjectKpiDaily(
            use_case=use_case, date=r["day"], submissions=r["n"],
            active_enumerators=r["enums"], flags_opened=flags_by_day.get(r["day"], 0),
        )
        for r in proj if r["day"]
    ])

    # Form per-day.
    form_rows = (
        subs.filter(form__isnull=False).annotate(day=_DAY)
        .values("form", "day").annotate(n=Count("id"))
    )
    FormKpiDaily.objects.filter(form__use_case=use_case).delete()
    FormKpiDaily.objects.bulk_create([
        FormKpiDaily(form_id=r["form"], date=r["day"], submissions=r["n"])
        for r in form_rows if r["day"]
    ])

    # Enumerator per-day.
    enum_rows = (
        subs.filter(enumerator__isnull=False).annotate(day=_DAY)
        .values("enumerator", "day").annotate(n=Count("id"))
    )
    EnumeratorKpiDaily.objects.filter(use_case=use_case).delete()
    EnumeratorKpiDaily.objects.bulk_create([
        EnumeratorKpiDaily(
            enumerator_id=r["enumerator"], use_case=use_case, date=r["day"], submissions=r["n"]
        )
        for r in enum_rows if r["day"]
    ])

    return {
        "project_days": ProjectKpiDaily.objects.filter(use_case=use_case).count(),
        "form_days": FormKpiDaily.objects.filter(form__use_case=use_case).count(),
        "enumerator_days": EnumeratorKpiDaily.objects.filter(use_case=use_case).count(),
    }


def rebuild_all_kpis() -> dict[str, int]:
    """Rebuild aggregates for every active project."""
    totals = {"projects": 0, "project_days": 0, "form_days": 0, "enumerator_days": 0}
    for uc in UseCase.objects.filter(is_active=True):
        r = rebuild_use_case_kpis(uc)
        totals["projects"] += 1
        for k in ("project_days", "form_days", "enumerator_days"):
            totals[k] += r[k]
    return totals
