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


def program_coverage(program, today=None):
    """Programme-level rollup across every enrolled client: overall visit
    coverage and the defaulters (clients with an overdue visit)."""
    from apps.fieldwork.models import CollectionUnit
    from apps.submissions.models import Submission

    today = today or timezone.localdate()
    schedule = list(program.project.schedule.all())
    units = list(CollectionUnit.objects.filter(project=program.project))
    subs = list(Submission.objects.filter(project=program.project)
                .select_related("crop").only("collection_unit_id", "event_key",
                                              "event_date", "crop"))
    by_unit: dict = {}
    for s in subs:
        by_unit.setdefault(s.collection_unit_id, []).append(s)

    total_expected = total_done = 0
    defaulters = []
    for u in units:
        plan = client_visit_plan(u, schedule, by_unit.get(u.id, []), today)
        s = plan_summary(plan)
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
        "schedule_len": len(schedule),
    }
