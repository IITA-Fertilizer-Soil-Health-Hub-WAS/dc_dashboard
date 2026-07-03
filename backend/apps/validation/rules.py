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


def geo_containment(submission, params) -> list[FlagResult]:
    """Flag a submission whose GPS falls OUTSIDE the elected plot boundary of its
    collection unit — the field team registered the farmer off the elected plot.
    No flag when there's no boundary or no submission GPS (nothing to test).

    params: {message?}.
    """
    from apps.common.geo import point_in_polygon

    unit = submission.collection_unit
    if unit is None or not getattr(unit, "boundary", None):
        return []
    if submission.lat is None or submission.lon is None:
        return []
    if point_in_polygon(submission.lat, submission.lon, unit.boundary):
        return []
    msg = params.get("message", "Collected outside the elected plot boundary")
    return [FlagResult(submission.id, msg, "", {"outside_boundary": True})]


# --- Per-use-case rules (need the whole distribution / cross-submission view) --

def numeric_outlier(project, params) -> list[FlagResult]:
    """Flag numeric values that are statistical outliers for their field across the
    whole project — a value that may sit *inside* the allowed range yet lies far from
    the norm (a unit slip or data-entry error a fixed range waves through). The
    field's mean/σ is learned from the collected data, so there is no threshold to
    hand-set; complements (does not replace) NUMERIC_RANGE / form constraints.

    params: {field, z?: 3.0, min_n?: 20}. No flag until at least min_n numeric values
    exist (too few to trust the distribution) or when every value is identical."""
    import statistics

    field_key = params["field"]
    z_thresh = float(params.get("z", 3.0))
    min_n = int(params.get("min_n", 20))

    pairs: list[tuple] = []
    for sid, raw in SubmissionValue.objects.filter(
        submission__project=project, field_key=field_key
    ).values_list("submission_id", "current_value"):
        try:
            pairs.append((sid, float(raw)))
        except (TypeError, ValueError):
            continue
    if len(pairs) < min_n:
        return []
    values = [v for _, v in pairs]
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    if stdev == 0:
        return []
    out: list[FlagResult] = []
    for sid, val in pairs:
        z = (val - mean) / stdev
        if abs(z) >= z_thresh:
            msg = params.get(
                "message", f"{field_key} = {val:g} is a statistical outlier (z={z:+.1f})"
            )
            out.append(FlagResult(sid, msg, field_key, {
                "value": val, "z": round(z, 2),
                "mean": round(mean, 2), "stdev": round(stdev, 2),
            }))
    return out


def geo_duplicate(project, params) -> list[FlagResult]:
    """Data-integrity / curbstoning signal: submissions from DIFFERENT households at
    the same GPS point — an enumerator who never actually moved. Submissions are
    snapped onto a small grid; any cell holding more than one household flags every
    submission in it. (Same household revisited across events is fine.)

    params: {precision?: 4 (decimal places; 4 ≈ 11 m at the equator), message?}."""
    precision = int(params.get("precision", 4))
    cells: dict[tuple, list] = {}
    for s in Submission.objects.filter(
        project=project, lat__isnull=False, lon__isnull=False
    ).values("id", "lat", "lon", "collection_unit_id"):
        key = (round(float(s["lat"]), precision), round(float(s["lon"]), precision))
        cells.setdefault(key, []).append(s)
    out: list[FlagResult] = []
    for (lat, lon), rows in cells.items():
        households = {r["collection_unit_id"] for r in rows if r["collection_unit_id"] is not None}
        if len(households) < 2:
            continue
        msg = params.get(
            "message", f"Shared GPS point {lat},{lon} across {len(households)} households"
        )
        for r in rows:
            out.append(FlagResult(
                r["id"], msg, "", {"lat": lat, "lon": lon, "households": len(households)}
            ))
    return out


def submission_speed(project, params) -> list[FlagResult]:
    """Data-integrity / curbstoning signal: an enumerator filing more than `max`
    submissions inside a short window — faster than genuine field interviews allow.
    Uses the server receipt time; a sliding window flags every submission caught in
    a burst.

    params: {max?: 6, window_min?: 30, message?}."""
    from datetime import timedelta

    max_n = int(params.get("max", 6))
    window_min = int(params.get("window_min", 30))
    window = timedelta(minutes=window_min)

    by_enum: dict = {}
    for s in Submission.objects.filter(
        project=project, enumerator__isnull=False, ona_submission_time__isnull=False
    ).values("id", "enumerator_id", "ona_submission_time"):
        by_enum.setdefault(s["enumerator_id"], []).append(s)

    flagged: dict = {}  # submission_id -> peak burst size it appeared in
    for rows in by_enum.values():
        rows.sort(key=lambda r: r["ona_submission_time"])
        left = 0
        for right in range(len(rows)):
            while rows[right]["ona_submission_time"] - rows[left]["ona_submission_time"] > window:
                left += 1
            count = right - left + 1
            if count > max_n:
                for j in range(left, right + 1):
                    sid = rows[j]["id"]
                    flagged[sid] = max(flagged.get(sid, 0), count)
    out: list[FlagResult] = []
    for sid, count in flagged.items():
        msg = params.get(
            "message", f"{count} submissions within {window_min} min — implausible pace"
        )
        out.append(FlagResult(sid, msg, "", {"burst_count": count, "window_min": window_min}))
    return out


def photo_reuse(project, params) -> list[FlagResult]:
    """Data-integrity / curbstoning signal: the same photo (identical image bytes)
    submitted for DIFFERENT households — a fabricated visit reusing an earlier
    picture. Relies on `Submission.media_hashes` (populated by the media-hashing
    task); a hash shared by two or more households flags every submission carrying
    it. Same household reusing an image across its own events is ignored.

    params: {message?}."""
    by_hash: dict[str, list] = {}
    for s in Submission.objects.filter(
        project=project, collection_unit__isnull=False
    ).exclude(media_hashes=[]).values("id", "collection_unit_id", "media_hashes"):
        for h in s["media_hashes"] or []:
            by_hash.setdefault(h, []).append(s)

    seen: set = set()
    out: list[FlagResult] = []
    for _h, rows in by_hash.items():
        households = {r["collection_unit_id"] for r in rows}
        if len(households) < 2:
            continue
        msg = params.get(
            "message", f"Photo reused across {len(households)} households"
        )
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append(FlagResult(r["id"], msg, "", {"households": len(households)}))
    return out


# --- Per-household rules (need the whole event timeline) ----------------------

def event_sequence(project, params) -> list[FlagResult]:
    """Flag households where an event was submitted while an earlier one is
    missing. (R: event N filled but event N-1 missing -> "Check submission events".)"""
    message = params.get("message", "Check submission events")
    order = {e.event_key: e.sequence for e in project.schedule.all()}
    if not order:
        return []
    out: list[FlagResult] = []
    subs = Submission.objects.filter(project=project).select_related("collection_unit")
    by_hh: dict[Any, list[Submission]] = {}
    for s in subs:
        by_hh.setdefault(s.collection_unit_id, []).append(s)

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


def date_window(project, params, today: date | None = None) -> list[FlagResult]:
    """Flag overdue events: an expected event whose target date has passed but was
    never submitted. Drives the same schedule that colours the dashboard grid."""
    from django.utils import timezone

    today = today or timezone.localdate()
    schedule = list(project.schedule.all())
    if not schedule:
        return []
    out: list[FlagResult] = []

    subs = list(
        Submission.objects.filter(project=project).select_related("collection_unit", "crop")
    )
    # Group submissions per unit; track submitted events, Event1 date, and a
    # representative submission (latest) to carry the unit's overdue flags.
    by_hh: dict[Any, dict[str, Any]] = {}
    for s in subs:
        if s.collection_unit_id is None:
            continue
        hh = by_hh.setdefault(
            s.collection_unit_id,
            {"submitted": {}, "event1": None, "rep": s, "crop": None, "site": None},
        )
        hh["submitted"][s.event_key] = s.event_date
        if s.event_key == "Event1" and s.event_date:
            hh["event1"] = s.event_date
        if s.crop:
            hh["crop"] = s.crop.name
        if s.collection_unit and s.collection_unit.site_selection_date:
            hh["site"] = s.collection_unit.site_selection_date
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
