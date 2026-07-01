"""Pluggable validation rule implementations.

Each rule turns a use case's data into a list of FlagResult. Rules operate on the
authoritative (edited) values via the helper `value_of`. The engine maps a
ValidationRule.rule_type to one of these and persists the results as flags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from apps.submissions.models import Submission, SubmissionValue

from .status import event_status


@dataclass
class FlagResult:
    submission_id: Any
    message: str
    field_key: str = ""
    detail: dict = field(default_factory=dict)


def value_of(submission: Submission, field_key: str) -> Any:
    """The authoritative (current) value of a field on a submission."""
    v = SubmissionValue.objects.filter(submission=submission, field_key=field_key).first()
    return v.current_value if v else None


# --- Per-submission rules ----------------------------------------------------

def regex_id(submission, params) -> list[FlagResult]:
    """Flag when an ID field matches none of the allowed patterns.
    (R: filter(!grepl(patternissues, ENID)) -> "Check ENID".)"""
    field_key = params["field"]
    patterns = params.get("patterns", [])
    message = params.get("message", f"Check {field_key}")
    val = value_of(submission, field_key)
    if val in (None, ""):
        return []
    if any(re.search(p, str(val)) for p in patterns):
        return []
    return [FlagResult(submission.id, message, field_key, {"value": val, "patterns": patterns})]


def required_field(submission, params) -> list[FlagResult]:
    out: list[FlagResult] = []
    for field_key in params.get("fields", []):
        if value_of(submission, field_key) in (None, ""):
            out.append(FlagResult(submission.id, f"Missing {field_key}", field_key))
    return out


def numeric_range(submission, params) -> list[FlagResult]:
    field_key = params["field"]
    val = value_of(submission, field_key)
    if val in (None, ""):
        return []
    try:
        num = float(val)
    except (ValueError, TypeError):
        return [FlagResult(submission.id, f"{field_key} is not numeric", field_key, {"value": val})]
    lo, hi = params.get("min"), params.get("max")
    if (lo is not None and num < lo) or (hi is not None and num > hi):
        msg = params.get("message", f"{field_key} out of range [{lo}, {hi}]")
        return [FlagResult(submission.id, msg, field_key, {"value": num, "min": lo, "max": hi})]
    return []


def geo_distance(submission, params) -> list[FlagResult]:
    """Flag a submission collected too far from its assigned plot — a GPS mismatch
    that usually means the wrong plot was visited, or the location was faked.
    (Adapted from SDMT's distance-to-reference-point spatial check.)

    params: {max_m: metres (default 100), message?}. No flag when the submission
    or its unit lacks coordinates (nothing to compare).
    """
    dist = submission.distance_to_unit_m
    if dist is None:
        return []
    max_m = params.get("max_m", 100)
    if dist <= max_m:
        return []
    msg = params.get("message", f"Collected {dist:.0f} m from assigned plot (>{max_m:.0f} m)")
    return [FlagResult(submission.id, msg, "", {"distance_m": round(dist, 1), "max_m": max_m})]


# --- Per-household rules (need the whole event timeline) ----------------------

def event_sequence(use_case, params) -> list[FlagResult]:
    """Flag households where an event was submitted while an earlier one is
    missing. (R: event N filled but event N-1 missing -> "Check submission events".)"""
    message = params.get("message", "Check submission events")
    order = {e.event_key: e.sequence for e in use_case.schedule.all()}
    if not order:
        return []
    out: list[FlagResult] = []
    subs = Submission.objects.filter(use_case=use_case).select_related("household")
    by_hh: dict[Any, list[Submission]] = {}
    for s in subs:
        by_hh.setdefault(s.household_id, []).append(s)

    for hh_subs in by_hh.values():
        present = {s.event_key for s in hh_subs if s.event_key in order}
        if not present:
            continue
        max_seq = max(order[e] for e in present)
        expected = {e for e, seq in order.items() if seq <= max_seq}
        missing = expected - present
        if missing:
            # Flag the latest submission of the household.
            latest = max(hh_subs, key=lambda s: order.get(s.event_key, 0))
            out.append(FlagResult(latest.id, message, "", {"missing_events": sorted(missing)}))
    return out


def date_window(use_case, params, today: date | None = None) -> list[FlagResult]:
    """Flag overdue events: an expected event whose target date has passed but was
    never submitted. Drives the same schedule that colours the dashboard grid."""
    from django.utils import timezone

    today = today or timezone.localdate()
    schedule = list(use_case.schedule.all())
    if not schedule:
        return []
    out: list[FlagResult] = []

    subs = list(
        Submission.objects.filter(use_case=use_case).select_related("household", "crop")
    )
    # Group submissions per household; track submitted events, Event1 date, and a
    # representative submission (latest) to carry the household's overdue flags.
    by_hh: dict[Any, dict[str, Any]] = {}
    for s in subs:
        if s.household_id is None:
            continue
        hh = by_hh.setdefault(
            s.household_id,
            {"submitted": {}, "event1": None, "rep": s, "crop": None, "site": None},
        )
        hh["submitted"][s.event_key] = s.event_date
        if s.event_key == "Event1" and s.event_date:
            hh["event1"] = s.event_date
        if s.crop:
            hh["crop"] = s.crop.name
        if s.household and s.household.site_selection_date:
            hh["site"] = s.household.site_selection_date
        # Keep the latest-dated submission as representative.
        if s.event_date and (hh["rep"].event_date is None or s.event_date > hh["rep"].event_date):
            hh["rep"] = s

    for info in by_hh.values():
        rep = info["rep"]
        for item in schedule:
            if info["submitted"].get(item.event_key):
                continue  # already submitted
            anchor = info["site"] if item.anchor == item.Anchor.SITE_SELECTION else info["event1"]
            offset = item.target_offset_for_crop(info["crop"])
            st = event_status(
                event_date=None,
                anchor_date=anchor,
                offset_days=offset,
                grace_days=item.grace_days,
                today=today,
            )
            if st == "overdue":
                out.append(
                    FlagResult(
                        rep.id,
                        f"{item.event_key} overdue",
                        item.event_key,
                        {"status": st, "event": item.event_key},
                    )
                )
    return out
