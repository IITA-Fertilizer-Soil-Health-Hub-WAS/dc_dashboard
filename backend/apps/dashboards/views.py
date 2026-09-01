"""Dashboard views — feature parity with the R Shiny app, RBAC-scoped.

Per project: Summary (info boxes, trials map, submission trend), Enumerators
(ranking + colour-coded event-completion grid), Issues (validation flags with
inline, role-gated review actions), and Data Preview. Tabs load as HTMX partials.
"""
from __future__ import annotations

import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.rbac.permissions import user_can, visible_projects
from apps.review import services
from apps.review.models import (
    IN_PROGRESS_STATES,
    NEEDS_REVIEW_STATES,
    REVIEW_CLOSED_STATES,
    WAITING_STATES,
    ReviewAction,
    ReviewActionLog,
    ReviewState,
)
from apps.review.state_machine import (
    ReviewPermissionDenied,
    TransitionError,
    legal_actions_from,
)
from apps.submissions.models import Enumerator, Submission
from apps.validation.models import ValidationFlag

from .charts import monthly_submission_counts, points_map_html, trials_map_html
from .final import final_rows
from .grid import build_event_grid
from .scoping import get_scoped_project

ACTION_SERVICES = {
    ReviewAction.OPEN_REVIEW: services.open_review,
    ReviewAction.REQUEST_EDIT: services.request_edit,
    ReviewAction.DECLINE: services.decline,
    ReviewAction.ENDORSE: services.endorse,
    ReviewAction.QC_APPROVE: services.qc_approve,
    ReviewAction.REOPEN: services.reopen,
}


def style_preview(request):
    """Dev-only component gallery — eyeball the redesign without signing in.

    Gated on DEBUG, so it exists locally (settings.dev) and is a hard 404 in
    staging/production. No authentication, by design, so it can't surface data.
    """
    if not settings.DEBUG:
        raise Http404()
    return render(request, "dashboards/style_preview.html")


@login_required
def my_assignments(request):
    """An enumerator's field work: the collection units assigned to them,
    grouped by job, with the form to collect and the deadline."""
    from apps.fieldwork.models import UnitAssignment

    assignments = (
        UnitAssignment.objects.filter(enumerator=request.user)
        .select_related("job", "job__project", "job__form", "unit")
        .order_by("job__deadline", "job__name", "unit__code")
    )
    groups: dict = {}
    for a in assignments:
        groups.setdefault(a.job, []).append(a)
    job_groups = [{"job": job, "units": units} for job, units in groups.items()]
    return render(request, "dashboards/my_assignments.html",
                  {"job_groups": job_groups, "count": assignments.count()})


@login_required
def my_submissions(request):
    """An enumerator's own collected submissions and the open flags they need to
    fix — scoped strictly to records attributed to this user (no one else's)."""
    from django.db.models import Prefetch
    user = request.user
    subs = (
        Submission.objects.filter(
            Q(collected_by=user) | Q(enumerator__user=user)
        )
        .select_related("project", "form", "enumerator", "collection_unit", "review")
        .annotate(open_flags=Count("flags", filter=Q(flags__status=ValidationFlag.Status.OPEN)))
        # The actual issues to fix — shown inline so the enumerator knows WHAT is wrong.
        .prefetch_related(Prefetch(
            "flags",
            queryset=ValidationFlag.objects.filter(
                status=ValidationFlag.Status.OPEN).select_related("rule"),
            to_attr="open_flag_list"))
        .order_by("-event_date", "-ona_submission_time")
    )
    to_fix = sum(1 for s in subs if s.open_flags)
    return render(request, "dashboards/my_submissions.html", {
        "submissions": subs[:300],
        "total": subs.count(),
        "to_fix": to_fix,
    })


@login_required
def overview(request):
    """Cross-project overview: key metrics for every project I can see."""
    from apps.validation.models import ValidationFlag

    closed = REVIEW_CLOSED_STATES
    rows = []
    totals = {"total": 0, "approved": 0, "in_review": 0, "open_issues": 0,
              "wb_pending": 0, "wb_failed": 0}
    for uc in visible_projects(request.user):
        subs = Submission.objects.filter(project=uc)
        row = {
            "uc": uc,
            "total": subs.count(),
            "approved": subs.filter(review__state=ReviewState.APPROVED).count(),
            "in_review": subs.exclude(review__state__in=closed).count(),
            "open_issues": ValidationFlag.objects.filter(
                rule__project=uc, status=ValidationFlag.Status.OPEN).count(),
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
def review_log(request, code):
    """On-screen review-actions log for a project — the append-only audit trail
    of every endorse / validate / decline / edit. Project-scoped (replaces the
    global admin ReviewActionLog list); the CSV export sits alongside it."""
    uc = get_scoped_project(request, code)
    logs = (
        ReviewActionLog.objects.filter(submission__project=uc)
        .select_related("actor", "submission", "submission__collected_by")
        .order_by("-created_at")[:500]
    )
    return render(request, "dashboards/review_log.html", {"uc": uc, "logs": logs})


@login_required
def export_audit(request, code):
    """CSV of the review audit trail for a project."""
    uc = get_scoped_project(request, code)
    logs = (
        ReviewActionLog.objects.filter(submission__project=uc)
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


WORKSPACE_TABS = {"summary", "review", "enumerators", "issues", "data", "final"}

# Each project section's content partial (loaded into the page body). The sidebar
# is the single navigation surface — there is no in-page tab bar.
TAB_URL_NAMES = {
    "summary": "dashboards:tab_summary",
    "review": "dashboards:tab_review",
    "enumerators": "dashboards:tab_enumerators",
    "issues": "dashboards:tab_issues",
    "data": "dashboards:tab_data",
    "final": "dashboards:tab_final",
}
TAB_LABELS = {
    "summary": "Dashboard", "review": "Review queue", "enumerators": "Enumerators",
    "issues": "Flagged issues", "data": "Submissions", "final": "Approved data",
}


@login_required
def project_detail(request, code):
    uc = get_scoped_project(request, code)
    # The project is the workspace: remember it as the user's current context so
    # the sidebar scopes to it until they switch.
    request.session["active_project"] = uc.code
    from django.urls import reverse

    tab = request.GET.get("tab", "summary")
    if tab not in WORKSPACE_TABS:
        tab = "summary"
    return render(request, "dashboards/project.html", {
        "uc": uc, "active_tab": tab,
        "tab_url": reverse(TAB_URL_NAMES[tab], args=[uc.code]),
        "tab_label": TAB_LABELS[tab],
    })


# --- Tab partials (HTMX) -----------------------------------------------------

@login_required
def tab_summary(request, code):
    uc = get_scoped_project(request, code)
    submissions = list(
        Submission.objects.filter(project=uc).select_related("collection_unit", "enumerator")
    )
    # Plot the submissions' own collected locations; fall back to unit points for
    # projects whose data predates geo capture.
    points = [
        {"lat": s.lat, "lon": s.lon, "color": "#0d5c3f",
         "label": " · ".join(p for p in [
             s.enumerator.enid if s.enumerator else "",
             s.collection_unit.code if s.collection_unit else "",
             s.event_key, str(s.event_date or "")] if p)}
        for s in submissions if s.lat is not None and s.lon is not None
    ]
    if points:
        map_html = points_map_html(points)
    else:
        map_html = trials_map_html(list(uc.collection_units.all()))
    trend = monthly_submission_counts(submissions)
    ctx = {
        "uc": uc,
        "total_submissions": len(submissions),
        "mapped_points": len(points),
        "country": ", ".join(uc.countries) or "—",
        "trend": trend,
        "trend_max": max((t["n"] for t in trend), default=0),
        "map_html": map_html,
        "health": _health_counts(uc),
        "attribution": _attribution_stats(uc),
        "jobs_progress": _jobs_progress(uc),
    }
    return render(request, "dashboards/_summary.html", ctx)


def _jobs_progress(uc):
    from apps.fieldwork.services import project_jobs_progress

    return project_jobs_progress(uc)


def _attribution_stats(uc) -> dict:
    """How much of a project's data traces to a registered platform account.

    Tracks migration off the ONA-era ENID bridge toward stamped UserIDs — the
    closer to 100%, the more of the data is owned by a known collector.
    """
    subs = Submission.objects.filter(project=uc)
    total = subs.count()
    attributed = subs.filter(collected_by__isnull=False).count()
    return {
        "total": total,
        "attributed": attributed,
        "unattributed": total - attributed,
        "pct": round(attributed / total * 100) if total else 0,
    }


def _health_counts(uc) -> dict:
    """Per-project review + write-back health for the Summary tab. The review
    side mirrors the Review-queue pools exactly (one submission, one stage), so
    the headline numbers match what a coordinator sees in the queue."""
    from apps.review.models import ReviewState

    subs = Submission.objects.filter(project=uc)

    def _c(states):
        return subs.filter(review__state__in=states).count()

    return {
        "needs_review": _c(NEEDS_REVIEW_STATES),
        "in_progress": _c(IN_PROGRESS_STATES),
        "waiting": _c(WAITING_STATES),
        "awaiting_validation": subs.filter(review__state=ReviewState.QC_PENDING).count(),
        "approved": subs.filter(review__state=ReviewState.APPROVED).count(),
        "declined": subs.filter(review__state=ReviewState.DECLINED).count(),
        # Superseded = replaced by a newer server record. Rare, but count it so the
        # pipeline pools sum to the total and nothing silently vanishes.
        "superseded": subs.filter(review__state=ReviewState.SUPERSEDED).count(),
        "wb_sent": subs.filter(writeback_status=Submission.WriteBackStatus.SENT).count(),
        "wb_pending": subs.filter(writeback_status=Submission.WriteBackStatus.PENDING).count(),
        "wb_failed": subs.filter(writeback_status=Submission.WriteBackStatus.FAILED).count(),
    }


@login_required
def tab_review(request, code, action_error: str = ""):
    """This project's review queue, split by pipeline stage, with inline actions."""
    uc = get_scoped_project(request, code)
    can_endorse = user_can(request.user, "endorse", uc)
    can_validate = user_can(request.user, "final_approve", uc)
    sel = ("enumerator", "collection_unit", "review", "review__endorsed_by", "review__assigned_to")

    def _pool(states, order):
        return list(Submission.objects.filter(project=uc, review__state__in=states)
                    .select_related(*sel).order_by(*order)[:300])

    to_validate = _pool([ReviewState.QC_PENDING], ["-updated_at"]) if can_validate else []
    needs_review = _pool(NEEDS_REVIEW_STATES, ["-ingested_at"]) if can_endorse else []
    in_progress = _pool(IN_PROGRESS_STATES, ["-updated_at"]) if can_endorse else []
    waiting = _pool(WAITING_STATES, ["-updated_at"]) if can_endorse else []
    approved = Submission.objects.filter(project=uc, review__state=ReviewState.APPROVED).count()

    from apps.console.registry import console_can_edit

    return render(request, "dashboards/_review.html", {
        "uc": uc, "to_validate": to_validate, "needs_review": needs_review,
        "in_progress": in_progress, "waiting": waiting,
        "can_endorse": can_endorse, "can_validate": can_validate,
        "approved_count": approved,
        "can_edit_reasons": console_can_edit(request.user, "rejection-reasons"),
        "action_error": action_error,
    })


@login_required
@require_POST
def tab_review_action(request, code):
    """Endorse / validate / decline a submission from the Review tab, then refresh it."""
    uc = get_scoped_project(request, code)
    submission = Submission.objects.filter(project=uc, pk=request.POST.get("submission")).first()
    fn = {
        ReviewAction.ENDORSE: services.endorse,
        ReviewAction.QC_APPROVE: services.qc_approve,
        ReviewAction.DECLINE: services.decline,
    }.get(request.POST.get("action"))
    error = ""
    if submission is None or fn is None:
        error = "That action is no longer available — the queue has moved on."
    else:
        try:
            fn(request.user, submission, note=(request.POST.get("note") or "").strip())
        except ReviewPermissionDenied:
            error = "You don't have permission to do that here."
        except TransitionError:
            error = "That item already moved on — this action no longer applies. The queue has been refreshed."
    return tab_review(request, code, action_error=error)


@login_required
def my_performance(request):
    """An enumerator's own quality scorecard — the same composite the coordinator
    sees, shown back to the person who earned it, per project they collect on, with
    where they rank. Self-service so field staff can watch their own quality."""
    from apps.kpi.metrics import PERIODS, enumerator_metrics
    from apps.submissions.models import Enumerator

    user = request.user
    days = request.GET.get("days", "90")
    if days not in PERIODS:
        days = "90"

    # The projects this user collects on, via their enumerator identity.
    identities = (
        Enumerator.objects.filter(user=user)
        .select_related("project").order_by("project__code")
    )
    by_uc: dict = {}
    for e in identities:
        by_uc.setdefault(e.project, set()).add(e.id)

    cards = []
    for uc, enum_ids in by_uc.items():
        m = enumerator_metrics(uc, days)
        board = m["leaderboard"]
        for pos, row in enumerate(board, start=1):
            if row["enumerator_id"] in enum_ids:
                cards.append({"uc": uc, "row": row, "rank": pos, "of": len(board)})
    cards.sort(key=lambda c: -c["row"]["quality_score"])

    return render(request, "dashboards/my_performance.html", {
        "cards": cards, "days": days, "periods": PERIODS,
        "period_label": PERIODS.get(days), "has_identity": bool(identities),
    })


@login_required
def household_timeline(request, code, hh_id):
    """One unit's whole season on a page: every scheduled event in order, with its
    submission date, review state and a few captured values — and the gaps (missing
    / overdue events) highlighted. The per-unit drill-down that complements the
    project-wide event grid."""
    from django.utils import timezone

    from apps.fieldwork.models import CollectionUnit
    from apps.submissions.models import SubmissionValue
    from apps.validation.status import event_status, status_color

    uc = get_scoped_project(request, code)
    hh = get_object_or_404(CollectionUnit, pk=hh_id, project=uc)
    schedule = list(uc.schedule.all())

    subs = {
        s.event_key: s
        for s in Submission.objects.filter(project=uc, collection_unit=hh)
        .select_related("review", "enumerator", "crop").order_by("event_date")
    }
    event1 = subs.get("Event1")
    event1_date = event1.event_date if event1 else None
    crop = next((s.crop.name for s in subs.values() if s.crop), None)
    today = timezone.localdate()

    # A compact set of captured values per submission (first handful, labelled).
    value_map = {}
    for ev, s in subs.items():
        value_map[ev] = list(
            SubmissionValue.objects.filter(submission=s)
            .exclude(current_value__in=["", None])
            .values("field_key", "current_value")[:6]
        )

    steps = []
    for item in schedule:
        s = subs.get(item.event_key)
        anchor = hh.site_selection_date if item.anchor == item.Anchor.SITE_SELECTION else event1_date
        st = event_status(
            event_date=s.event_date if s else None,
            anchor_date=anchor,
            offset_days=item.target_offset_for_crop(crop),
            grace_days=item.grace_days,
            today=today,
        )
        steps.append({
            "event_key": item.event_key,
            "submission": s,
            "status": st,
            "color": status_color(st),
            "values": value_map.get(item.event_key, []),
        })

    return render(request, "dashboards/household_timeline.html", {
        "uc": uc, "hh": hh, "unit": hh, "steps": steps, "crop": crop,
        "submitted_count": len(subs), "event_count": len(schedule),
    })


@login_required
def qc_signoff(request, code):
    """Agronomist QC sign-off — a dedicated, focused Gate-2 queue.

    After a coordinator endorses a submission (Gate 1 → QC_PENDING), the quality
    checker / agronomist signs off its agronomic validity here before it becomes
    APPROVED. Its own screen (not buried in the Review tab's dual list) so the
    validator works one clean backlog. Guarded by the `final_approve` right."""
    uc = get_scoped_project(request, code)
    if not user_can(request.user, "final_approve", uc):
        raise Http404("You are not a validator on this project.")

    if request.method == "POST":
        submission = Submission.objects.filter(
            project=uc, pk=request.POST.get("submission")
        ).first()
        fn = {
            ReviewAction.QC_APPROVE: services.qc_approve,
            ReviewAction.DECLINE: services.decline,
            ReviewAction.REQUEST_EDIT: services.request_edit,
        }.get(request.POST.get("action"))
        if submission is not None and fn is not None:
            try:
                fn(request.user, submission, note=(request.POST.get("note") or "").strip())
                messages.success(request, f"Submission {submission.ona_uuid[:8]} updated.")
            except (ReviewPermissionDenied, TransitionError) as e:
                messages.error(request, str(e))
        return redirect("dashboards:qc_signoff", code=uc.code)

    pending = list(
        Submission.objects.filter(project=uc, review__state=ReviewState.QC_PENDING)
        .select_related("enumerator", "collection_unit", "review", "review__endorsed_by",
                        "collection_unit")
        .order_by("review__updated_at")[:300]
    )
    approved = Submission.objects.filter(
        project=uc, review__state=ReviewState.APPROVED
    ).count()
    return render(request, "dashboards/qc_signoff.html", {
        "uc": uc, "pending": pending, "pending_count": len(pending),
        "approved_count": approved,
    })


@login_required
def tab_enumerators(request, code):
    uc = get_scoped_project(request, code)
    ranking = (
        Enumerator.objects.filter(project=uc, is_test=False)
        .select_related("user")
        .annotate(n=Count("submissions"))
        .order_by("-n")
    )
    # Ranking by platform identity (collected_by), not ENID — the identity-first
    # view of who collected what, spanning the ENID bridge and stamped UserIDs.
    from apps.accounts.models import User

    collectors = (
        User.objects.annotate(
            n=Count("collected_submissions", filter=Q(collected_submissions__project=uc))
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
    uc = get_scoped_project(request, code)
    return render(request, "dashboards/_issues.html", _issues_context(request, uc))


@login_required
def tab_data(request, code):
    uc = get_scoped_project(request, code)
    submissions = list(
        Submission.objects.filter(project=uc)
        .select_related("enumerator", "collection_unit", "review", "collected_by")
        .prefetch_related("values")
        .order_by("-event_date", "-ona_submission_time")[:100]
    )
    columns, rows = _data_grid(submissions)
    total = Submission.objects.filter(project=uc).count()
    return render(request, "dashboards/_data.html", {
        "uc": uc, "columns": columns, "rows": rows,
        "showing": len(submissions), "total": total,
    })


def _data_grid(submissions, max_cols: int = 60):
    """A spreadsheet of submissions × their form fields, showing the current
    (authoritative) value, with the column set = union of fields seen."""
    col_order: list[str] = []
    seen: set[str] = set()
    built = []
    for s in submissions:
        fm = _raw_field_map(s.raw_payload)
        corrected = False
        for v in s.values.all():           # overlay reviewer edits
            if v.field_key in fm:
                fm[v.field_key] = v.current_value
            if v.is_edited:
                corrected = True
        for k in fm:
            if k not in seen:
                seen.add(k)
                col_order.append(k)
        built.append((s, fm, corrected))
    columns = sorted(col_order)[:max_cols]
    rows = [{"s": s, "corrected": corrected, "cells": [fm.get(c, "") for c in columns]}
            for s, fm, corrected in built]
    return columns, rows


@login_required
def tab_final(request, code):
    """Final dataset: approved submissions only, with authoritative values."""
    uc = get_scoped_project(request, code)
    rows = final_rows(uc)[2]
    return render(request, "dashboards/_final.html", {"uc": uc, "rows": rows, "count": len(rows)})


@login_required
def export_final(request, code):
    """Download the final (approved) dataset as CSV — authoritative values."""
    uc = get_scoped_project(request, code)
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
            "HHID": s.collection_unit.code if s.collection_unit else "",
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
    uc = get_scoped_project(request, code)
    submission = Submission.objects.filter(project=uc, pk=submission_id).first()
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


# The one action a reviewer most likely wants next, per state — rendered as the
# panel's primary button. The rest of the state-legal actions are secondary.
PRIMARY_ACTION_BY_STATE = {
    ReviewState.INGESTED: ReviewAction.OPEN_REVIEW,
    ReviewState.FLAGGED: ReviewAction.OPEN_REVIEW,
    ReviewState.EDIT_REQUESTED: ReviewAction.OPEN_REVIEW,
    ReviewState.EDITED: ReviewAction.ENDORSE,
    ReviewState.IN_REVIEW: ReviewAction.ENDORSE,
    ReviewState.QC_PENDING: ReviewAction.QC_APPROVE,
    ReviewState.APPROVED: ReviewAction.REOPEN,
    ReviewState.DECLINED: ReviewAction.REOPEN,
    ReviewState.SUPERSEDED: ReviewAction.REOPEN,
}

# Simple (single-click) review buttons: (action, permission, label, css class).
# DECLINE is rendered separately because it carries a reason + note form.
REVIEW_ACTION_BTNS = [
    (ReviewAction.OPEN_REVIEW, "open_review", "Open review", "btn-open"),
    (ReviewAction.REQUEST_EDIT, "request_edit", "Request edit", "btn-request"),
    (ReviewAction.ENDORSE, "endorse", "Endorse (Gate 1)", "btn-edit"),
    (ReviewAction.QC_APPROVE, "final_approve", "Validate (Gate 2)", "btn-approve"),
    (ReviewAction.REOPEN, "open_review", "Reopen", "btn-request"),
]

# A one-line "what happens next" hint shown under the current-state chip.
STATE_NEXT_HINT = {
    ReviewState.INGESTED: "New submission — open it to start the review.",
    ReviewState.FLAGGED: "Validation flagged this — open it, then endorse or request a fix.",
    ReviewState.IN_REVIEW: "Under review — endorse it (Gate 1) or send it back for edits.",
    ReviewState.EDIT_REQUESTED: "Sent back to the enumerator — waiting for their correction.",
    ReviewState.EDITED: "Enumerator re-submitted — endorse it (Gate 1) or request more edits.",
    ReviewState.QC_PENDING: "Endorsed — awaiting Gate 2 validation to be approved.",
    ReviewState.APPROVED: "Approved and final. Reopen only if something needs changing.",
    ReviewState.DECLINED: "Declined. Reopen if it should be reconsidered.",
    ReviewState.SUPERSEDED: "Replaced by a newer server record. Reopen to review it.",
}


@login_required
def submission_review(request, code, submission_id):
    """Full review screen: edit field values and run workflow actions."""
    uc = get_scoped_project(request, code)
    submission = get_object_or_404(
        Submission.objects.select_related("enumerator", "collection_unit", "crop", "review", "form"),
        project=uc, pk=submission_id,
    )
    error = ok = None

    if request.method == "POST":
        action = request.POST.get("action")
        note = request.POST.get("note", "")
        try:
            if action == "save_edits":
                if not user_can(request.user, "edit", uc):
                    raise ReviewPermissionDenied("You may not edit submissions here.")
                # Baseline a field shows: a reviewer's current value if one exists,
                # else the raw value from the server record. Any field can be edited
                # — edit_value creates a tracked value for it on first change.
                current = {v.field_key: v.current_value for v in submission.values.all()}
                raw_map = _raw_field_map(submission.raw_payload)
                changed = 0
                for key, new in request.POST.items():
                    if not key.startswith("val-"):
                        continue
                    fk = key[4:]
                    baseline = current[fk] if fk in current else raw_map.get(fk)
                    if str(baseline if baseline is not None else "") != new:
                        services.edit_value(request.user, submission, field_key=fk,
                                            new_value=new, note=note)
                        changed += 1
                ok = f"Saved {changed} field edit(s)." if changed else "No changes to save."
            elif action == "assign_me":
                services.assign(request.user, submission, request.user)
                ok = "Assigned to you."
            elif action == ReviewAction.DECLINE:
                reason = None
                rc = (request.POST.get("rejection_reason") or "").strip()
                if rc:
                    from apps.review.models import RejectionReason
                    reason = RejectionReason.objects.filter(
                        Q(project=uc) | Q(project__isnull=True), pk=rc
                    ).first()
                services.decline(request.user, submission, note=note, reason=reason)
                ok = "Decline recorded."
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

    flags = submission.flags.filter(status=ValidationFlag.Status.OPEN).select_related("rule")
    actions = submission.actions.select_related("actor").order_by("-created_at")[:15]
    review = getattr(submission, "review", None)
    can = {
        "edit": user_can(request.user, "edit", uc),
        "decline": user_can(request.user, "decline", uc),
        "request_edit": user_can(request.user, "request_edit", uc),
        "endorse": user_can(request.user, "endorse", uc),
        "final_approve": user_can(request.user, "final_approve", uc),
        "open_review": user_can(request.user, "open_review", uc),
    }
    # Show only the actions legal from the current state (permission is still
    # required on top). The state machine already enforces this on POST; gating
    # the buttons here keeps the panel to the 1–2 moves that actually apply.
    state = review.state if review else ReviewState.INGESTED
    available_actions = set(legal_actions_from(state))
    primary_action = PRIMARY_ACTION_BY_STATE.get(state)
    state_hint = STATE_NEXT_HINT.get(state, "")
    can_assign = can["open_review"] and review is not None and review.assigned_to_id is None
    # Only the buttons legal from this state AND permitted for this user, primary first.
    review_actions = sorted(
        ({"action": a, "label": lbl, "cls": cls, "primary": a == primary_action}
         for a, perm, lbl, cls in REVIEW_ACTION_BTNS
         if can[perm] and a in available_actions),
        key=lambda b: not b["primary"],
    )
    show_decline = can["decline"] and ReviewAction.DECLINE in available_actions
    from apps.review.models import RejectionReason

    fields = _merged_fields(submission)
    from apps.ingestion.form_schema import label_map

    lm = label_map(getattr(submission.form, "field_schema", None) or [])
    media = _list_media(uc, submission)
    for m in media:
        meta = lm.get(m["question"])
        m["question_label"] = meta["label"] if meta else m["question"]
    from apps.dashboards.charts import submission_plot_map_html

    distance_m = submission.distance_to_unit_m
    return render(request, "dashboards/submission_review.html", {
        "uc": uc, "submission": submission, "flags": flags,
        "actions": actions, "review": review, "can": can, "ok": ok, "error": error,
        "review_actions": review_actions, "show_decline": show_decline,
        "state_hint": state_hint, "can_assign": can_assign,
        "fields": fields, "media": media,
        "distance_m": distance_m,
        "plot_map_html": submission_plot_map_html(submission),
        "is_corrected": any(f["is_edited"] for f in fields),
        "rejection_reasons": RejectionReason.objects.filter(
            Q(project=uc) | Q(project__isnull=True), is_active=True
        ).order_by("order", "label"),
    })


def _list_media(uc, submission) -> list[dict]:
    """A submission's media descriptors via its backend (ONA/Kobo read the embedded
    `_attachments`; ODK Central looks them up). Never fatal to the review page: on
    any backend error, fall back to whatever is embedded in the record."""
    try:
        from apps.ingestion.backends.registry import get_backend_for

        return get_backend_for(uc).list_attachments(submission)
    except Exception:
        from apps.ingestion.attachments import parse_attachments

        return parse_attachments(getattr(submission, "raw_payload", None))


@login_required
def submission_media(request, code, submission_id, name):
    """Stream one submission photo/media through the app, using the backend's own
    credentials — collection-server attachments aren't publicly fetchable. Scoped to
    a member of the project; the file must belong to this submission's record."""
    uc = get_scoped_project(request, code)
    submission = get_object_or_404(Submission, project=uc, pk=submission_id)
    match = next((a for a in _list_media(uc, submission) if a.get("name") == name), None)
    if match is None:
        raise Http404("Attachment not part of this submission.")
    from apps.ingestion.backends.registry import get_backend_for

    try:
        data, ctype = get_backend_for(uc).fetch_attachment(match)
    except NotImplementedError:
        raise Http404("This source does not expose attachments.") from None
    except Exception as exc:
        return HttpResponse(f"Could not load attachment: {exc}", status=502)
    resp = HttpResponse(data, content_type=ctype)
    resp["Cache-Control"] = "private, max-age=600"
    return resp


# ODK / ONA system fields to hide (keep the actual answers, drop plumbing).
_SYSTEM_FIELD_PREFIXES = ("_", "meta/", "formhub/")
_SYSTEM_FIELD_KEYS = {
    "start", "end", "today", "deviceid", "username", "subscriberid", "simserial",
    "phonenumber", "__version__", "instanceID", "instanceName",
}


def _raw_field_map(payload: dict) -> dict:
    """Every field the enumerator submitted (from the untouched server record),
    minus ODK/ONA system plumbing. Nested groups/repeats are serialised."""
    import json

    out: dict = {}
    for key, value in (payload or {}).items():
        if key in _SYSTEM_FIELD_KEYS or key.startswith(_SYSTEM_FIELD_PREFIXES):
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        out[key] = "" if value is None else value
    return out


def _merged_fields(submission) -> list[dict]:
    """Every editable field: the raw server fields plus any engine/mapped values,
    each showing its raw (source) value and current (authoritative) value. When the
    form's field schema is cached, each field also carries its human label + section
    group and fields are ordered by the form (SDMT-style labelled QC view); fields
    with no schema entry fall back to the raw key and sort after, alphabetically."""
    from apps.ingestion.form_schema import label_map

    raw_map = _raw_field_map(submission.raw_payload)
    svs = {v.field_key: v for v in submission.values.all()}
    form = getattr(submission, "form", None)
    lm = label_map(getattr(form, "field_schema", None) or [])
    order = {path: i for i, path in enumerate(lm)}

    def make(key, raw, current, is_edited):
        meta = lm.get(key)
        return {
            "key": key, "raw": raw, "current": current, "is_edited": is_edited,
            "label": meta["label"] if meta else key,
            "group": meta["group"] if meta else "",
        }

    fields = []
    for key in raw_map:
        sv = svs.get(key)
        fields.append(make(key, raw_map[key],
                           sv.current_value if sv else raw_map[key],
                           bool(sv and sv.is_edited)))
    for key in svs:
        if key in raw_map:
            continue
        sv = svs[key]
        fields.append(make(key, sv.raw_value, sv.current_value, sv.is_edited))
    # Ordered by the form schema first (in-form order), unknown fields after by key.
    fields.sort(key=lambda f: (order.get(f["key"], len(order)), f["key"]))
    return fields


@login_required
@require_POST
def bulk_submission_action(request, code):
    """Apply one review action to many selected submissions at once."""
    uc = get_scoped_project(request, code)
    action = request.POST.get("action")
    ids = request.POST.getlist("ids")
    ok = 0
    failures: list[str] = []

    if action in ACTION_SERVICES and ids:
        service = ACTION_SERVICES[action]
        submissions = Submission.objects.filter(project=uc, pk__in=ids)
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
        ValidationFlag.objects.filter(rule__project=uc, status=ValidationFlag.Status.OPEN)
        .select_related("submission", "submission__review", "submission__enumerator",
                        "submission__collection_unit", "rule")
        .order_by("submission__ona_uuid")
    )
    if f["q"]:
        flags = flags.filter(
            Q(submission__enumerator__enid__icontains=f["q"])
            | Q(submission__collection_unit__code__icontains=f["q"])
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
        Submission.objects.filter(project=uc).exclude(event_key="")
        .values_list("event_key", flat=True).distinct()
    )
    can = {
        "decline": user_can(request.user, "decline", uc),
        "request_edit": user_can(request.user, "request_edit", uc),
        "edit": user_can(request.user, "edit", uc),
        "endorse": user_can(request.user, "endorse", uc),
        "final_approve": user_can(request.user, "final_approve", uc),
        "open_review": user_can(request.user, "open_review", uc),
    }
    from apps.console.registry import console_can_edit

    return {
        "uc": uc, "flags": flags, "can": can, "filters": f,
        "event_options": events,
        "state_options": ReviewState.choices,
        "severity_options": ValidationRule.Severity.choices,
        "can_edit_rules": console_can_edit(request.user, "validation-rules"),
    }
