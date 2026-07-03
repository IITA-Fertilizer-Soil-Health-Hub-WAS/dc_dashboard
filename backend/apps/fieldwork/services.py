"""Field-work helpers."""
from __future__ import annotations

from datetime import date

from django.db.models import Count, Q


def project_enumerators(project):
    """Active users holding the Enumerator role on a project (incl. the
    country/region cascade) — the pool a coordinator assigns units to."""
    from apps.accounts.models import User
    from apps.rbac.models import Role

    covers = Q(memberships__project=project)
    if project.country_id:
        covers |= Q(memberships__country_id=project.country_id)
        if project.country.region_id:
            covers |= Q(memberships__region_id=project.country.region_id)
    return (
        User.objects.filter(Q(memberships__role=Role.ENUMERATOR) & covers, is_approved=True)
        .distinct()
        .order_by("email")
    )


# A unit counts as "collected" once a submission has matched it (Submission.
# collection_unit, set at ingest). These roll-ups are the basis for the Coverage
# and Timeliness KPIs in Feature C.

def _pct(done: int, total: int) -> int:
    return round(done / total * 100) if total else 0


def job_progress(job) -> dict:
    """Expected vs actual for one job: assigned / collected / pending / overdue."""
    from apps.fieldwork.models import UnitAssignment

    agg = UnitAssignment.objects.filter(job=job).aggregate(
        total=Count("id", distinct=True),
        collected=Count("id", distinct=True, filter=Q(unit__submissions__isnull=False)),
    )
    total = agg["total"] or 0
    collected = agg["collected"] or 0
    target = job.target_count or total
    overdue = bool(
        job.deadline and job.status != job.Status.CLOSED
        and date.today() > job.deadline and collected < target
    )
    # QC progress: of the submissions on this job's units, how many are validated
    # (final-approved). Mirrors SDMT's per-job QC % column.
    from apps.review.models import ReviewState
    from apps.submissions.models import Submission

    unit_ids = UnitAssignment.objects.filter(job=job).values_list("unit_id", flat=True)
    subs = Submission.objects.filter(project=job.project, collection_unit_id__in=unit_ids)
    total_subs = subs.count()
    approved_subs = subs.filter(review__state=ReviewState.APPROVED).count()

    return {
        "total": total,
        "collected": collected,
        "pending": total - collected,
        "target": target,
        "pct": _pct(collected, target or total),
        "overdue": overdue,
        "submissions": total_subs,
        "approved_submissions": approved_subs,
        "qc_pct": _pct(approved_subs, total_subs),
    }


def job_enumerator_progress(job) -> list[dict]:
    """Per-enumerator collected/total within a job."""
    from apps.fieldwork.models import UnitAssignment

    rows = (
        UnitAssignment.objects.filter(job=job)
        .values("enumerator", "enumerator__email", "enumerator__full_name")
        .annotate(
            total=Count("id", distinct=True),
            collected=Count("id", distinct=True, filter=Q(unit__submissions__isnull=False)),
        )
        .order_by("-collected")
    )
    out = []
    for r in rows:
        name = r["enumerator__full_name"] or r["enumerator__email"] or "Unassigned"
        out.append({
            "name": name,
            "total": r["total"],
            "collected": r["collected"],
            "pct": _pct(r["collected"], r["total"]),
        })
    return out


def project_jobs_progress(project) -> list[dict]:
    """Progress for each active job in a project (for the Summary tab)."""
    jobs = project.jobs.exclude(status="CLOSED").order_by("deadline", "name")
    return [{"job": j, "progress": job_progress(j)} for j in jobs]
