"""Visit plans + coverage — the agronomic 'care plan' (Phase 2).

For a soil-health hub, a client's care plan is the trial's **visit schedule**: a
farmer/plot enrolled on an anchor date is expected at Event1…N (offsets from that
anchor), and each expected visit is done / due / overdue. This reuses the exact
same status engine as the event-completion grid (apps.validation.status) so the
care view and the M&E grid never disagree.

The anchor is the unit's ``site_selection_date`` (enrollment); if that's unset we
fall back to the earliest encounter, so a plan still renders. EVENT1-anchored
visits count from the actual Event1 encounter, matching the grid.
"""
from __future__ import annotations

from django.utils import timezone

from apps.validation.status import event_status, status_color, target_date

STATUS_LABEL = {"complete": "Done", "due": "Due", "overdue": "Overdue", "future": "Upcoming"}


def _encounters_by_key(encounters):
    """{event_key: earliest event_date} for a client's submissions."""
    by_key: dict[str, object] = {}
    for e in encounters:
        if e.event_date and (e.event_key not in by_key or e.event_date < by_key[e.event_key]):
            by_key[e.event_key] = e.event_date
    return by_key


def _crop_of(encounters):
    for e in encounters:
        if getattr(e, "crop", None):
            return e.crop.name
    return None


def client_visit_plan(unit, schedule, encounters, today=None):
    """Per-visit status for one client. ``schedule`` is the project's ordered
    EventScheduleItem list; ``encounters`` its Submissions. Returns a list of
    {event_key, target, done, status, label, color, is_open}."""
    today = today or timezone.localdate()
    by_key = _encounters_by_key(encounters)
    crop = _crop_of(encounters)
    site = unit.site_selection_date or (min(by_key.values()) if by_key else None)
    event1 = by_key.get("Event1")

    plan = []
    for item in schedule:
        offset = item.target_offset_for_crop(crop)
        anchor = site if item.anchor == item.Anchor.SITE_SELECTION else event1
        done = by_key.get(item.event_key)
        st = event_status(event_date=done, anchor_date=anchor, offset_days=offset,
                          grace_days=item.grace_days, today=today)
        plan.append({
            "event_key": item.event_key,
            "target": target_date(anchor, offset),
            "done": done,
            "status": st,
            "label": STATUS_LABEL.get(st, st),
            "color": status_color(st),
            "is_open": st in ("due", "overdue"),
        })
    return plan


def plan_summary(plan):
    """Roll a plan up to counts for a client-row badge."""
    done = sum(1 for v in plan if v["status"] == "complete")
    overdue = sum(1 for v in plan if v["status"] == "overdue")
    due = sum(1 for v in plan if v["status"] == "due")
    return {"total": len(plan), "done": done, "overdue": overdue, "due": due}


def _subs_by_unit(qs):
    """{unit_id: [submissions]} from one query, keeping only the fields a visit
    plan needs (encounter date + crop for the per-crop offset)."""
    subs = list(qs.select_related("crop").only(
        "collection_unit_id", "event_key", "event_date", "crop"))
    by_unit: dict = {}
    for s in subs:
        by_unit.setdefault(s.collection_unit_id, []).append(s)
    return by_unit


def _plan_rows(project, units, today=None):
    """Build ``(unit, plan, summary, last_visit)`` for each unit in one pass —
    the project's encounters and schedule are loaded once, not per client. Order
    follows ``units``. Returns ``(rows, schedule_len)``. The single scaffold behind
    every programme-level rollup below."""
    today = today or timezone.localdate()
    schedule = list(project.schedule.all())
    from apps.submissions.models import Submission

    by_unit = _subs_by_unit(Submission.objects.filter(project=project))
    rows = []
    for u in units:
        encs = by_unit.get(u.id, [])
        plan = client_visit_plan(u, schedule, encs, today)
        last = max((e.event_date for e in encs if e.event_date), default=None)
        rows.append((u, plan, plan_summary(plan), last))
    return rows, len(schedule)


def program_coverage(program, today=None):
    """Programme-level rollup across every enrolled client: overall visit
    coverage and the defaulters (clients with an overdue visit)."""
    from apps.fieldwork.models import CollectionUnit

    units = list(CollectionUnit.objects.filter(project=program.project))
    rows, schedule_len = _plan_rows(program.project, units, today)

    total_expected = total_done = 0
    defaulters = []
    for u, _plan, s, _last in rows:
        total_expected += s["total"]
        total_done += s["done"]
        if s["overdue"]:
            defaulters.append({"unit": u, "overdue": s["overdue"], "done": s["done"],
                               "total": s["total"]})
    defaulters.sort(key=lambda d: (-d["overdue"], d["unit"].code))
    coverage = round(100 * total_done / total_expected) if total_expected else 0
    return {
        "clients": len(units), "total_expected": total_expected, "total_done": total_done,
        "coverage": coverage, "defaulters": defaulters,
        "schedule_len": schedule_len,
    }


def worker_breakdown(program, today=None):
    """Per-worker accountability: caseload size, visits done / expected, overdue,
    and coverage %, for the workers with active assignments in this programme."""
    from .models import CareAssignment

    assignments = list(
        CareAssignment.objects.filter(program=program, is_active=True)
        .select_related("worker", "unit")
    )
    rows, _ = _plan_rows(program.project, [a.unit for a in assignments], today)
    summ_by_unit = {u.id: s for (u, _p, s, _last) in rows}

    workers: dict = {}
    for a in assignments:
        s = summ_by_unit.get(a.unit_id) or {"total": 0, "done": 0, "overdue": 0}
        w = workers.setdefault(a.worker_id, {
            "worker": a.worker, "caseload": 0, "expected": 0, "done": 0, "overdue": 0,
        })
        w["caseload"] += 1
        w["expected"] += s["total"]
        w["done"] += s["done"]
        w["overdue"] += s["overdue"]
    rows = list(workers.values())
    for w in rows:
        w["coverage"] = round(100 * w["done"] / w["expected"]) if w["expected"] else 0
    rows.sort(key=lambda w: (-w["overdue"], w["worker"].full_name or w["worker"].email))
    return rows


def program_status_rows(program, today=None):
    """Flat per-client status for the CSV export: code, name, worker, visits
    done/expected, overdue, last visit."""
    from apps.fieldwork.models import CollectionUnit

    from .models import CareAssignment

    worker_by_unit = {
        a.unit_id: a.worker for a in
        CareAssignment.objects.filter(program=program, is_active=True).select_related("worker")
    }
    units = list(CollectionUnit.objects.filter(project=program.project).order_by("code"))
    rows, _ = _plan_rows(program.project, units, today)

    out = []
    for u, _plan, s, last in rows:
        w = worker_by_unit.get(u.id)
        out.append({
            "code": u.code, "name": u.name,
            "worker": (w.full_name or w.email) if w else "",
            "done": s["done"], "expected": s["total"], "overdue": s["overdue"],
            "last_visit": last.isoformat() if last else "",
        })
    return out


def caseload_plans(assignments, today=None):
    """``(assignment, plan, summary)`` for a worker's caseload, which may span
    several projects — loaded with ONE encounter query total and one schedule read
    per project (was one query per client). Order follows ``assignments``."""
    from apps.submissions.models import Submission

    today = today or timezone.localdate()
    assignments = list(assignments)
    by_unit = _subs_by_unit(
        Submission.objects.filter(collection_unit_id__in=[a.unit_id for a in assignments])
    )
    schedule_by_project: dict = {}
    out = []
    for a in assignments:
        pid = a.program.project_id
        if pid not in schedule_by_project:
            schedule_by_project[pid] = list(a.program.project.schedule.all())
        plan = client_visit_plan(a.unit, schedule_by_project[pid],
                                 by_unit.get(a.unit_id, []), today)
        out.append((a, plan, plan_summary(plan)))
    return out
