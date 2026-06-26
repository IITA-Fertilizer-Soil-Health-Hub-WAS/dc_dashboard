"""Dashboard views — feature parity with the R Shiny app, RBAC-scoped.

Per use case: Summary (info boxes, trials map, submission trend), Enumerators
(ranking + colour-coded event-completion grid), Issues (validation flags with
inline, role-gated review actions), and Data Preview. Tabs load as HTMX partials.
"""
from __future__ import annotations

import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.rbac.permissions import user_can, visible_use_cases
from apps.review import services
from apps.review.models import ReviewAction, ReviewActionLog, ReviewState
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
def overview(request):
    """Cross-use-case overview: key metrics for every use case I can see."""
    from apps.validation.models import ValidationFlag

    closed = [ReviewState.APPROVED, ReviewState.DECLINED]
    rows = []
    totals = {"total": 0, "approved": 0, "in_review": 0, "open_issues": 0,
              "wb_pending": 0, "wb_failed": 0}
    for uc in visible_use_cases(request.user):
        subs = Submission.objects.filter(use_case=uc)
        row = {
            "uc": uc,
            "total": subs.count(),
            "approved": subs.filter(review__state=ReviewState.APPROVED).count(),
            "in_review": subs.exclude(review__state__in=closed).count(),
            "open_issues": ValidationFlag.objects.filter(
                rule__use_case=uc, status=ValidationFlag.Status.OPEN).count(),
            "wb_pending": subs.filter(
                writeback_status=Submission.WriteBackStatus.PENDING).count(),
            "wb_failed": subs.filter(
                writeback_status=Submission.WriteBackStatus.FAILED).count(),
        }
        rows.append(row)
        for k in totals:
            totals[k] += row[k]
    return render(request, "dashboards/overview.html", {"rows": rows, "totals": totals})


@login_required
def my_queue(request):
    """Submissions assigned to me that still need action, across my use cases."""
    submissions = (
        Submission.objects.filter(
            use_case__in=visible_use_cases(request.user),
            review__assigned_to=request.user,
        )
        .exclude(review__state__in=[ReviewState.APPROVED, ReviewState.DECLINED])
        .select_related("use_case", "enumerator", "household", "review")
        .order_by("review__state", "-updated_at")
    )
    return render(request, "dashboards/my_queue.html",
                  {"submissions": submissions, "count": submissions.count()})


@login_required
def export_audit(request, code):
    """CSV of the review audit trail for a use case."""
    uc = get_scoped_use_case(request, code)
    logs = (
        ReviewActionLog.objects.filter(submission__use_case=uc)
        .select_related("actor", "submission", "submission__collected_by")
        .order_by("created_at")
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{uc.code.lower()}_audit.csv"'
    writer = csv.writer(response)
    writer.writerow(["timestamp", "actor", "submission", "collected_by", "action",
                     "from_state", "to_state", "field", "old_value", "new_value", "note"])
    for log in logs:
        collector = log.submission.collected_by
        writer.writerow([
            log.created_at.isoformat(),
            log.actor.email if log.actor else "system",
            log.submission.ona_uuid,
            collector.user_id if collector else "",
            log.action, log.from_state, log.to_state,
            log.field_key, log.old_value, log.new_value, log.note,
        ])
    return response


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
        "health": _health_counts(uc),
        "attribution": _attribution_stats(uc),
    }
    return render(request, "dashboards/_summary.html", ctx)


def _attribution_stats(uc) -> dict:
    """How much of a use case's data traces to a registered platform account.

    Tracks migration off the ONA-era ENID bridge toward stamped UserIDs — the
    closer to 100%, the more of the data is owned by a known collector.
    """
    subs = Submission.objects.filter(use_case=uc)
    total = subs.count()
    attributed = subs.filter(collected_by__isnull=False).count()
    return {
        "total": total,
        "attributed": attributed,
        "unattributed": total - attributed,
        "pct": round(attributed / total * 100) if total else 0,
    }


def _health_counts(uc) -> dict:
    """Per-use-case review + write-back health for the Summary tab."""
    from apps.review.models import ReviewState

    subs = Submission.objects.filter(use_case=uc)
    closed = [ReviewState.APPROVED, ReviewState.DECLINED]
    return {
        "approved": subs.filter(review__state=ReviewState.APPROVED).count(),
        "declined": subs.filter(review__state=ReviewState.DECLINED).count(),
        "in_review": subs.exclude(review__state__in=closed).count(),
        "wb_sent": subs.filter(writeback_status=Submission.WriteBackStatus.SENT).count(),
        "wb_pending": subs.filter(writeback_status=Submission.WriteBackStatus.PENDING).count(),
        "wb_failed": subs.filter(writeback_status=Submission.WriteBackStatus.FAILED).count(),
    }


@login_required
def tab_enumerators(request, code):
    uc = get_scoped_use_case(request, code)
    ranking = (
        Enumerator.objects.filter(use_case=uc, is_test=False)
        .select_related("user")
        .annotate(n=Count("submissions"))
        .order_by("-n")
    )
    # Ranking by platform identity (collected_by), not ENID — the identity-first
    # view of who collected what, spanning the ENID bridge and stamped UserIDs.
    from apps.accounts.models import User

    collectors = (
        User.objects.annotate(
            n=Count("collected_submissions", filter=Q(collected_submissions__use_case=uc))
        )
        .filter(n__gt=0)
        .order_by("-n", "email")
    )
    grid = build_event_grid(uc)
    return render(
        request,
        "dashboards/_enumerators.html",
        {"uc": uc, "ranking": ranking, "collectors": collectors, "grid": grid},
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
        .select_related("enumerator", "household", "crop", "collected_by")
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
    base = ["ona_uuid", "ENID", "HHID", "collected_by", "event", "crop", "date", "state"]
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
            "collected_by": s.collected_by.user_id if s.collected_by else "",
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


@login_required
def submission_review(request, code, submission_id):
    """Full review screen: edit field values and run workflow actions."""
    uc = get_scoped_use_case(request, code)
    submission = get_object_or_404(
        Submission.objects.select_related("enumerator", "household", "crop", "review", "form"),
        use_case=uc, pk=submission_id,
    )
    error = ok = None

    if request.method == "POST":
        action = request.POST.get("action")
        note = request.POST.get("note", "")
        try:
            if action == "save_edits":
                if not user_can(request.user, "edit", uc):
                    raise ReviewPermissionDenied("You may not edit submissions here.")
                current = {v.field_key: v.current_value for v in submission.values.all()}
                changed = 0
                for key, new in request.POST.items():
                    if not key.startswith("val-"):
                        continue
                    fk = key[4:]
                    if str(current.get(fk, "") or "") != new:
                        services.edit_value(request.user, submission, field_key=fk,
                                            new_value=new, note=note)
                        changed += 1
                ok = f"Saved {changed} field edit(s)." if changed else "No changes to save."
            elif action == "assign_me":
                services.assign(request.user, submission, request.user)
                ok = "Assigned to you."
            elif action in ACTION_SERVICES:
                ACTION_SERVICES[action](request.user, submission, note=note)
                ok = f"{dict(ReviewAction.choices).get(action, action)} recorded."
            else:
                error = f"Unknown action: {action}"
        except ReviewPermissionDenied as exc:
            error = str(exc)
        except TransitionError as exc:
            error = str(exc)
        submission.refresh_from_db()

    values = submission.values.all().order_by("field_key")
    flags = submission.flags.filter(status=ValidationFlag.Status.OPEN).select_related("rule")
    actions = submission.actions.select_related("actor").order_by("-created_at")[:15]
    review = getattr(submission, "review", None)
    can = {
        "edit": user_can(request.user, "edit", uc),
        "decline": user_can(request.user, "decline", uc),
        "request_edit": user_can(request.user, "request_edit", uc),
        "qc_approve": user_can(request.user, "qc_approve", uc),
        "open_review": user_can(request.user, "open_review", uc),
    }
    return render(request, "dashboards/submission_review.html", {
        "uc": uc, "submission": submission, "values": values, "flags": flags,
        "actions": actions, "review": review, "can": can, "ok": ok, "error": error,
    })


@login_required
@require_POST
def bulk_submission_action(request, code):
    """Apply one review action to many selected submissions at once."""
    uc = get_scoped_use_case(request, code)
    action = request.POST.get("action")
    ids = request.POST.getlist("ids")
    ok = 0
    failures: list[str] = []

    if action in ACTION_SERVICES and ids:
        service = ACTION_SERVICES[action]
        submissions = Submission.objects.filter(use_case=uc, pk__in=ids)
        for submission in submissions:
            try:
                service(request.user, submission, note=request.POST.get("note", ""))
                ok += 1
            except (ReviewPermissionDenied, TransitionError) as exc:
                failures.append(str(exc))
    elif not ids:
        failures.append("No submissions selected.")
    else:
        failures.append(f"Unknown bulk action: {action}")

    ctx = _issues_context(request, uc)
    label = dict(ReviewAction.choices).get(action, action)
    if ok:
        ctx["ok"] = f"{label}: {ok} submission(s) updated."
    if failures:
        # Collapse repeated permission/transition messages.
        ctx["error"] = "; ".join(sorted(set(failures))[:3])
    return render(request, "dashboards/_issues.html", ctx)


def _issues_context(request, uc) -> dict:
    from django.db.models import Q

    from apps.review.models import ReviewState
    from apps.validation.models import ValidationRule

    # Filters come from GET (filter bar) or POST (action re-renders carry them).
    src = request.POST if request.method == "POST" else request.GET
    f = {
        "q": (src.get("q") or "").strip(),
        "event": src.get("event") or "",
        "state": src.get("state") or "",
        "severity": src.get("severity") or "",
        "assigned_me": src.get("assigned_me") == "1",
    }

    flags = (
        ValidationFlag.objects.filter(rule__use_case=uc, status=ValidationFlag.Status.OPEN)
        .select_related("submission", "submission__review", "submission__enumerator",
                        "submission__household", "rule")
        .order_by("submission__ona_uuid")
    )
    if f["q"]:
        flags = flags.filter(
            Q(submission__enumerator__enid__icontains=f["q"])
            | Q(submission__household__hhid__icontains=f["q"])
            | Q(message__icontains=f["q"])
        )
    if f["event"]:
        flags = flags.filter(submission__event_key=f["event"])
    if f["state"]:
        flags = flags.filter(submission__review__state=f["state"])
    if f["severity"]:
        flags = flags.filter(severity=f["severity"])
    if f["assigned_me"]:
        flags = flags.filter(submission__review__assigned_to=request.user)

    events = sorted(
        Submission.objects.filter(use_case=uc).exclude(event_key="")
        .values_list("event_key", flat=True).distinct()
    )
    can = {
        "decline": user_can(request.user, "decline", uc),
        "request_edit": user_can(request.user, "request_edit", uc),
        "edit": user_can(request.user, "edit", uc),
        "qc_approve": user_can(request.user, "qc_approve", uc),
        "open_review": user_can(request.user, "open_review", uc),
    }
    return {
        "uc": uc, "flags": flags, "can": can, "filters": f,
        "event_options": events,
        "state_options": ReviewState.choices,
        "severity_options": ValidationRule.Severity.choices,
    }


# Field values for an edit modal/inline form (optional helper used by templates).
def submission_values(submission) -> list[SubmissionValue]:
    return list(submission.values.all())
