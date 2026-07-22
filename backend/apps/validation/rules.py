"""Pluggable validation rule implementations.

Each rule turns a project's data into a list of FlagResult. Rules operate on the
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
    """The authoritative (current) value of a field on a submission.

    Falls back to the raw payload so a rule can target ANY imported form field,
    not only the mapped canonical ones (ONA/ODK records are flat slash-keyed,
    matching the form schema paths)."""
    # Fast path: the engine bulk-loads all values and attaches a per-submission
    # cache, so this is an in-memory lookup (no query) during a full run.
    cache = getattr(submission, "_value_cache", None)
    if cache is not None:
        if field_key in cache:
            return cache[field_key]
        return (submission.raw_payload or {}).get(field_key)
    v = SubmissionValue.objects.filter(submission=submission, field_key=field_key).first()
    if v is not None:
        return v.current_value
    return (submission.raw_payload or {}).get(field_key)


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _aggregate(op: str, values: list[float]) -> float | None:
    if not values:
        return None
    if op == "mean":
        return sum(values) / len(values)
    if op == "min":
        return min(values)
    if op == "max":
        return max(values)
    if op == "product":
        p = 1.0
        for v in values:
            p *= v
        return p
    if op == "diff":  # first minus the rest
        return values[0] - sum(values[1:])
    return sum(values)  # default


# Comparators take (lhs, rhs, tol) and return True when the check PASSES.
_CMP = {
    "eq": lambda a, b, t: abs(a - b) <= t,
    "neq": lambda a, b, t: abs(a - b) > t,
    "lte": lambda a, b, t: a <= b + t,
    "gte": lambda a, b, t: a >= b - t,
    "lt": lambda a, b, t: a < b - t,
    "gt": lambda a, b, t: a > b + t,
}


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated quantile (same method numpy uses by default)."""
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


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


def cross_field(submission, params) -> list[FlagResult]:
    """Combine several columns and check the result against a target, a range, or
    another combination of columns — the checks a fixed per-field range can't do.

    The classic case is *parts that must add up to a whole*: three land-use
    percentages summing to 100, fertiliser splits summing to a dose, allocations
    summing to a total. It also does field-to-field relations (planted >= harvested,
    a + b <= capacity).

    params:
      fields: [f1, f2, ...]              columns to combine
      op: sum|mean|min|max|product|diff  how to combine them (default sum)
      compare: eq|neq|lte|gte|lt|gt|between   (default eq)
      target: <number>                   constant right-hand side (eq/lte/…)
      min, max: <number>                 bounds when compare = between
      rhs_fields: [...], rhs_op           compare to op(rhs_fields) instead of target
      tol: <number>                      tolerance for eq / boundaries (default 0)
      message: <str>
    A partly-filled set (some parts entered, some blank/non-numeric) is flagged so
    the arithmetic can't silently pass; an all-blank set is skipped.
    """
    fields = params.get("fields", [])
    if not fields:
        return []
    raw = {f: value_of(submission, f) for f in fields}
    if all(v in (None, "") for v in raw.values()):
        return []  # nothing entered — nothing to cross-check
    nums, missing = [], []
    for f in fields:
        n = _to_float(raw[f])
        (nums if n is not None else missing).append(n if n is not None else f)
    if missing:
        msg = params.get("message") or (
            f"Incomplete for cross-check — {', '.join(missing)} missing or non-numeric"
        )
        return [FlagResult(submission.id, msg, missing[0], {"missing": missing})]

    op = params.get("op", "sum")
    lhs = _aggregate(op, nums)
    tol = float(params.get("tol", 0) or 0)
    compare = params.get("compare", "eq")
    label = f"{op}({', '.join(fields)})"

    if compare == "between":
        lo, hi = params.get("min"), params.get("max")
        if (lo is None or lhs >= lo - tol) and (hi is None or lhs <= hi + tol):
            return []
        msg = params.get("message") or f"{label} = {lhs:g} not in [{lo}, {hi}]"
        return [FlagResult(submission.id, msg, fields[0],
                           {"value": lhs, "min": lo, "max": hi})]

    rhs_fields = params.get("rhs_fields")
    if rhs_fields:
        rnums = [_to_float(value_of(submission, f)) for f in rhs_fields]
        if any(x is None for x in rnums):
            return []
        rhs = _aggregate(params.get("rhs_op", "sum"), rnums)
        rhs_label = f"{params.get('rhs_op', 'sum')}({', '.join(rhs_fields)})"
    else:
        if params.get("target") is None:
            return []
        rhs = float(params["target"])
        rhs_label = f"{rhs:g}"

    if _CMP.get(compare, _CMP["eq"])(lhs, rhs, tol):
        return []
    msg = params.get("message") or f"{label} = {lhs:g} should be {compare} {rhs_label}"
    return [FlagResult(submission.id, msg, fields[0],
                       {"value": lhs, "expected": rhs, "compare": compare, "tol": tol})]


def conditional_required(submission, params) -> list[FlagResult]:
    """Skip-logic integrity: when a trigger condition holds, some fields must be
    filled. E.g. if `fertiliser_used` = yes, then `fertiliser_type` is required;
    if `damage` is not blank, then `damage_cause` is required. Catches the gaps a
    plain REQUIRED_FIELD (which always fires) would over-flag.

    params:
      when: {field, equals: <v>}  or  {field, in: [..]}  or  {field, not_blank: true}
      require: [fields]
      message
    """
    cond = params.get("when", {})
    cfield = cond.get("field")
    if not cfield:
        return []
    cval = value_of(submission, cfield)
    if "equals" in cond:
        triggered = str(cval) == str(cond["equals"])
    elif "in" in cond:
        triggered = str(cval) in [str(x) for x in cond["in"]]
    elif cond.get("not_blank"):
        triggered = cval not in (None, "")
    else:
        triggered = False
    if not triggered:
        return []
    out: list[FlagResult] = []
    for f in params.get("require", []):
        if value_of(submission, f) in (None, ""):
            msg = params.get("message") or f"{f} required when {cfield} = {cval}"
            out.append(FlagResult(submission.id, msg, f, {"when": cfield, "when_value": cval}))
    return out


def media_required(submission, params) -> list[FlagResult]:
    """Flag a submission missing an expected attachment (e.g. a plot photo).
    Uses the media hashes populated on ingest; fewer than `min` → flagged.

    params: {min?: 1, message?}."""
    min_n = int(params.get("min", 1))
    have = len(submission.media_hashes or [])
    if have >= min_n:
        return []
    msg = params.get("message", f"Missing attachment — {have} of {min_n} expected")
    return [FlagResult(submission.id, msg, "", {"media": have, "min": min_n})]


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


# --- Per-project rules (need the whole distribution / cross-submission view) --

def _val_filter(project, form) -> dict:
    """Base filter for SubmissionValue queries, optionally scoped to one form."""
    f = {"submission__project": project}
    if form is not None:
        f["submission__form"] = form
    return f


def _field_values(project, form, field_key) -> dict:
    """submission_id -> value for a field across a project (optionally one form),
    preferring the authoritative SubmissionValue and falling back to the raw
    payload so statistical/uniqueness rules also work on any imported field."""
    out: dict = {}
    for sid, val in SubmissionValue.objects.filter(
        **_val_filter(project, form), field_key=field_key
    ).values_list("submission_id", "current_value"):
        out[sid] = val
    for sid, raw in _sub_qs(project, form).values_list("id", "raw_payload"):
        if sid not in out and raw:
            v = raw.get(field_key)
            if v not in (None, ""):
                out[sid] = v
    return out


def numeric_outlier(project, params, form=None) -> list[FlagResult]:
    """Flag numeric values that are statistical outliers for their field — values
    that may sit *inside* the allowed range yet lie far from the norm (a unit slip
    or data-entry error a fixed range waves through). The distribution is learned
    from the collected data, so there's no threshold to hand-set.

    params:
      field: <key>
      method: zscore | iqr      (default zscore)
      z: 3.0                     zscore: flag |value - mean| / σ ≥ z
      k: 1.5                     iqr: flag outside [Q1 - k·IQR, Q3 + k·IQR]
      group_by: <key>            compare within groups (e.g. per crop), so a big
                                 crop doesn't make a small crop's values look normal
      min_n: 20                  minimum values (per group) before trusting the shape
      message

    IQR is robust to skew and heavy tails; z-score assumes a roughly normal field."""
    import statistics

    field_key = params["field"]
    method = params.get("method", "zscore")
    min_n = int(params.get("min_n", 20))
    group_by = params.get("group_by")

    values_by_sid: dict = {}
    for sid, raw in _field_values(project, form, field_key).items():
        n = _to_float(raw)
        if n is not None:
            values_by_sid[sid] = n
    group_of: dict = {}
    if group_by:
        for sid, gval in _field_values(project, form, group_by).items():
            group_of[sid] = str(gval)

    buckets: dict = {}
    for sid, n in values_by_sid.items():
        g = group_of.get(sid, "") if group_by else ""
        buckets.setdefault(g, []).append((sid, n))

    out: list[FlagResult] = []
    for g, pairs in buckets.items():
        if len(pairs) < min_n:
            continue
        values = [v for _, v in pairs]
        gtxt = f", {g}" if group_by and g else ""
        if method == "iqr":
            k = float(params.get("k", 1.5))
            sv = sorted(values)
            q1, q3 = _quantile(sv, 0.25), _quantile(sv, 0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            lo, hi = q1 - k * iqr, q3 + k * iqr
            for sid, val in pairs:
                if val < lo or val > hi:
                    msg = params.get(
                        "message", f"{field_key} = {val:g} is an outlier (IQR{gtxt})")
                    d = {"value": val, "low": round(lo, 2), "high": round(hi, 2),
                         "method": "iqr"}
                    if group_by:
                        d["group"] = g
                    out.append(FlagResult(sid, msg, field_key, d))
        else:
            z_thresh = float(params.get("z", 3.0))
            mean, stdev = statistics.fmean(values), statistics.pstdev(values)
            if stdev == 0:
                continue
            for sid, val in pairs:
                z = (val - mean) / stdev
                if abs(z) >= z_thresh:
                    msg = params.get(
                        "message",
                        f"{field_key} = {val:g} is a statistical outlier (z={z:+.1f}{gtxt})")
                    d = {"value": val, "z": round(z, 2), "mean": round(mean, 2),
                         "stdev": round(stdev, 2), "method": "zscore"}
                    if group_by:
                        d["group"] = g
                    out.append(FlagResult(sid, msg, field_key, d))
    return out


def unique_field(project, params, form=None) -> list[FlagResult]:
    """Flag submissions that share a value in a field meant to be unique — a
    duplicate barcode, plot code or household ID that usually means a double-entry
    or a mislabelled record. Every submission carrying a duplicated value is
    flagged so a reviewer can resolve the collision.

    params: {field, ignore_blank?: true, message?}."""
    field_key = params.get("field")
    if not field_key:
        return []
    ignore_blank = params.get("ignore_blank", True)
    by_val: dict = {}
    for sid, val in _field_values(project, form, field_key).items():
        if ignore_blank and val in (None, ""):
            continue
        by_val.setdefault(str(val), []).append(sid)
    out: list[FlagResult] = []
    for val, sids in by_val.items():
        if len(sids) < 2:
            continue
        msg = params.get("message", f"Duplicate {field_key} = {val} ({len(sids)} submissions)")
        for sid in sids:
            out.append(FlagResult(sid, msg, field_key, {"value": val, "count": len(sids)}))
    return out


def reference_match(project, params, form=None) -> list[FlagResult]:
    """Flag submissions whose ID field value is NOT present in a reference
    dataset — an unknown or mistyped sample id, or a record that isn't in the
    sampling frame. (Validates sample IDs across systems.)

    params: {field, dataset (code), message?}."""
    from apps.projects.models import ReferenceDataset

    field_key, code = params.get("field"), params.get("dataset")
    if not (field_key and code):
        return []
    ds = ReferenceDataset.objects.filter(project=project, code=code).first()
    if ds is None:
        return []
    keys = set(ds.rows.values_list("key", flat=True))
    out: list[FlagResult] = []
    for sid, val in _field_values(project, form, field_key).items():
        v = str(val).strip()
        if v and v not in keys:
            msg = params.get("message", f"{field_key} “{v}” is not in reference “{ds.name}”")
            out.append(FlagResult(sid, msg, field_key, {"value": v, "dataset": code}))
    return out


def reference_compare(project, params, form=None) -> list[FlagResult]:
    """Cross-check a submitted value against the matching reference row — e.g. a
    field measurement vs the laboratory result for the same sample. Joins on the
    sample id, then compares the field to a reference column. (Lab–field
    consistency check.) Unmatched ids are left to reference_match.

    params: {key_field, dataset, ref_column, field, compare?: eq, tol?: 0, message?}."""
    from apps.projects.models import ReferenceDataset

    field_key = params.get("field")
    code = params.get("dataset")
    key_field = params.get("key_field")
    ref_column = params.get("ref_column")
    if not (field_key and code and key_field and ref_column):
        return []
    ds = ReferenceDataset.objects.filter(project=project, code=code).first()
    if ds is None:
        return []
    ref = {r.key: (r.data or {}).get(ref_column) for r in ds.rows.all()}
    compare = params.get("compare", "eq")
    tol = float(params.get("tol", 0) or 0)
    ids = _field_values(project, form, key_field)     # sid -> join id
    vals = _field_values(project, form, field_key)    # sid -> field value
    out: list[FlagResult] = []
    for sid, jid in ids.items():
        rid = str(jid).strip()
        if rid not in ref:
            continue  # no lab record for this id — reference_match handles unknowns
        expected, actual = ref[rid], vals.get(sid)
        if actual in (None, "") or expected in (None, ""):
            continue
        a, e = _to_float(actual), _to_float(expected)
        if a is not None and e is not None:
            ok = _CMP.get(compare, _CMP["eq"])(a, e, tol)
        else:
            ok = str(actual).strip() == str(expected).strip()
        if not ok:
            msg = params.get(
                "message",
                f"{field_key} = {actual} disagrees with lab {ref_column} = {expected} (id {rid})")
            out.append(FlagResult(sid, msg, field_key,
                                  {"value": actual, "expected": expected, "id": rid}))
    return out


def _sub_qs(project, form):
    qs = Submission.objects.filter(project=project)
    return qs.filter(form=form) if form is not None else qs


def geo_duplicate(project, params, form=None) -> list[FlagResult]:
    """Data-integrity / curbstoning signal: submissions from DIFFERENT households at
    the same GPS point — an enumerator who never actually moved. Submissions are
    snapped onto a small grid; any cell holding more than one household flags every
    submission in it. (Same household revisited across events is fine.)

    params: {precision?: 4 (decimal places; 4 ≈ 11 m at the equator), message?}."""
    precision = int(params.get("precision", 4))
    cells: dict[tuple, list] = {}
    for s in _sub_qs(project, form).filter(
        lat__isnull=False, lon__isnull=False
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


def submission_speed(project, params, form=None) -> list[FlagResult]:
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
    for s in _sub_qs(project, form).filter(
        enumerator__isnull=False, ona_submission_time__isnull=False
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


def photo_reuse(project, params, form=None) -> list[FlagResult]:
    """Data-integrity / curbstoning signal: the same photo (identical image bytes)
    submitted for DIFFERENT households — a fabricated visit reusing an earlier
    picture. Relies on `Submission.media_hashes` (populated by the media-hashing
    task); a hash shared by two or more households flags every submission carrying
    it. Same household reusing an image across its own events is ignored.

    params: {message?}."""
    by_hash: dict[str, list] = {}
    for s in _sub_qs(project, form).filter(
        collection_unit__isnull=False
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

def event_sequence(project, params, form=None) -> list[FlagResult]:
    """Flag households where an event was submitted while an earlier one is
    missing. (R: event N filled but event N-1 missing -> "Check submission events".)

    Project-wide by design — the event timeline spans forms — so `form` is ignored."""
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


def date_window(project, params, today: date | None = None, *, form=None) -> list[FlagResult]:
    """Flag overdue events: an expected event whose target date has passed but was
    never submitted. Drives the same schedule that colours the dashboard grid.

    Project-wide by design (the schedule spans forms) — `form` is ignored."""
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
