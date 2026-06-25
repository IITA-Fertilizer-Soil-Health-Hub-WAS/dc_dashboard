"""Dashboard views — feature parity with the R Shiny app, RBAC-scoped.

Per use case: Summary (info boxes, trials map, submission trend), Enumerators
(ranking + colour-coded event-completion grid), Issues (validation flags with
inline, role-gated review actions), and Data Preview. Tabs load as HTMX partials.
"""
from __future__ import annotations

import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.rbac.permissions import user_can, visible_use_cases
from apps.review import services
from apps.review.models import ReviewAction
from apps.review.state_machine import ReviewPermissionDenied, TransitionError
from apps.submissions.models import Enumerator, Submission, SubmissionValue
from apps.validation.models import ValidationFlag

from .charts import submission_trend_html, trials_map_html
from .final import final_rows
from .grid import build_event_grid
from .scoping import get_scoped_use_case

ACTION_SERVICES = {
    ReviewAction.OPEN_REVIEW: services.open_review,
    ReviewAction.REQUEST_EDIT: services.request_edit,
    ReviewAction.DECLINE: services.decline,
    ReviewAction.QC_APPROVE: services.qc_approve,
    ReviewAction.REOPEN: services.reopen,
}


@login_required
def index(request):
    """Landing page: the use cases this user may view."""
    use_cases = visible_use_cases(request.user)
    return render(request, "dashboards/index.html", {"use_cases": use_cases})


@login_required
def usecase_detail(request, code):
    uc = get_scoped_use_case(request, code)
    return render(request, "dashboards/usecase.html", {"uc": uc, "active_tab": "summary"})


# --- Tab partials (HTMX) -----------------------------------------------------

@login_required
def tab_summary(request, code):
    uc = get_scoped_use_case(request, code)
    submissions = list(Submission.objects.filter(use_case=uc).select_related("household"))
    households = list(uc.households.all())
    ctx = {
        "uc": uc,
        "total_submissions": len(submissions),
        "country": ", ".join(uc.countries) or "—",
        "trend_html": submission_trend_html(submissions),
        "map_html": trials_map_html(households),
    }
    return render(request, "dashboards/_summary.html", ctx)


@login_required
def tab_enumerators(request, code):
    uc = get_scoped_use_case(request, code)
    ranking = (
        Enumerator.objects.filter(use_case=uc, is_test=False)
        .annotate(n=Count("submissions"))
        .order_by("-n")
    )
    grid = build_event_grid(uc)
    return render(
        request,
        "dashboards/_enumerators.html",
        {"uc": uc, "ranking": ranking, "grid": grid},
    )


@login_required
def tab_issues(request, code):
    uc = get_scoped_use_case(request, code)
    return render(request, "dashboards/_issues.html", _issues_context(request, uc))


@login_required
def tab_data(request, code):
    uc = get_scoped_use_case(request, code)
    submissions = (
        Submission.objects.filter(use_case=uc)
        .select_related("enumerator", "household", "crop")
        .order_by("-event_date")[:500]
    )
    return render(request, "dashboards/_data.html", {"uc": uc, "submissions": submissions})


@login_required
def tab_final(request, code):
    """Final dataset: approved submissions only, with authoritative values."""
    uc = get_scoped_use_case(request, code)
    rows = final_rows(uc)[2]
    return render(request, "dashboards/_final.html", {"uc": uc, "rows": rows, "count": len(rows)})


@login_required
def export_final(request, code):
    """Download the final (approved) dataset as CSV — authoritative values."""
    uc = get_scoped_use_case(request, code)
    subs, keys, rows = final_rows(uc)
    base = ["ona_uuid", "ENID", "HHID", "event", "crop", "date", "state"]
    columns = base + [k for k in keys if k not in base]

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{uc.code.lower()}_final.csv"'
    writer = csv.writer(response)
    writer.writerow(columns)
    for row in rows:
        s, values = row["submission"], row["values"]
        record = {
            "ona_uuid": s.ona_uuid,
            "ENID": s.enumerator.enid if s.enumerator else "",
            "HHID": s.household.hhid if s.household else "",
            "event": s.event_key,
            "crop": s.crop.name if s.crop else "",
            "date": s.event_date or "",
            "state": "APPROVED",
            **{k: values.get(k, "") for k in keys},
        }
        writer.writerow([record.get(c, "") for c in columns])
    return response


# --- Inline review actions (HTMX POST) ---------------------------------------

@login_required
@require_POST
def submission_action(request, code, submission_id):
    uc = get_scoped_use_case(request, code)
    submission = Submission.objects.filter(use_case=uc, pk=submission_id).first()
    if submission is None:
        return render(request, "dashboards/_issues.html", _issues_context(request, uc))

    action = request.POST.get("action")
    note = request.POST.get("note", "")
    error = None
    try:
        if action == ReviewAction.EDIT_VALUE:
            services.edit_value(
                request.user,
                submission,
                field_key=request.POST.get("field_key", ""),
                new_value=request.POST.get("new_value"),
                note=note,
            )
        elif action in ACTION_SERVICES:
            ACTION_SERVICES[action](request.user, submission, note=note)
        else:
            error = f"Unknown action: {action}"
    except ReviewPermissionDenied as exc:
        error = str(exc)
    except TransitionError as exc:
        error = str(exc)

    ctx = _issues_context(request, uc)
    ctx["error"] = error
    return render(request, "dashboards/_issues.html", ctx)


def _issues_context(request, uc) -> dict:
    flags = (
        ValidationFlag.objects.filter(rule__use_case=uc, status=ValidationFlag.Status.OPEN)
        .select_related("submission", "submission__review", "submission__enumerator",
                        "submission__household", "rule")
        .order_by("submission__ona_uuid")
    )
    can = {
        "decline": user_can(request.user, "decline", uc),
        "request_edit": user_can(request.user, "request_edit", uc),
        "edit": user_can(request.user, "edit", uc),
        "qc_approve": user_can(request.user, "qc_approve", uc),
        "open_review": user_can(request.user, "open_review", uc),
    }
    return {"uc": uc, "flags": flags, "can": can}


# Field values for an edit modal/inline form (optional helper used by templates).
def submission_values(submission) -> list[SubmissionValue]:
    return list(submission.values.all())
