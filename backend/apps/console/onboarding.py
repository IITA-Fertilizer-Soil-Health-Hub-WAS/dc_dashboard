"""Helpers for the form-based onboarding wizard.

Maps ONA's structure to ours: an ONA *project* becomes a UseCase; each ONA *form*
in it becomes a FormDefinition (an "entry" to the project). The wizard collects
fields and assembles the same config dict the YAML importer consumes, so there's
one code path into the database (apps.config_admin.loader.import_config).
"""
from __future__ import annotations

from typing import Any

# Canonical fields the engine understands, shown as mapping rows in the wizard.
CANONICAL_TARGETS = [
    {"key": "USERID", "label": "Platform UserID (collector)", "transform": "DIRECT",
     "required": False},
    {"key": "ENID", "label": "Enumerator ID", "transform": "DIRECT", "required": True},
    {"key": "HHID", "label": "Household / Plot ID", "transform": "DIRECT", "required": True},
    {"key": "event_key", "label": "Event", "transform": "DIRECT", "required": True},
    {"key": "Crop", "label": "Crop", "transform": "LOOKUP", "required": False},
    {"key": "Trial", "label": "Trial", "transform": "DIRECT", "required": False},
    {"key": "GEO", "label": "GPS point (lat/lon)", "transform": "SPLIT_GEOPOINT", "required": False},
    {"key": "today", "label": "Submission date", "transform": "DATE_PARSE", "required": False},
]
_TARGET_BY_KEY = {t["key"]: t for t in CANONICAL_TARGETS}


def suggest_target(field_path: str) -> str | None:
    """Guess which canonical target an ONA field path maps to, by name."""
    f = field_path.lower()
    # Geopoint is checked before HHID so 'household_geopoint' maps to GEO, not HHID.
    if "geopoint" in f or "gps" in f or "geolocation" in f:
        return "GEO"
    # Platform UserID stamped by the mobile app — checked before ENID so a
    # 'user_id'/'collector_id' field doesn't get grabbed as the enumerator id.
    if "userid" in f or "user_id" in f or f.endswith("/uid") or "collector_id" in f:
        return "USERID"
    if "enumerator" in f or "enum_id" in f or f.endswith("/enid") or "enid" in f:
        return "ENID"
    if "household" in f or "barcode" in f or "hhid" in f or "plot" in f or "rep_id" in f:
        return "HHID"
    if f == "event" or f.endswith("/event") or "intro/event" in f or "/event" in f:
        return "event_key"
    if "crop" in f:
        return "Crop"
    if "trial" in f or "treatment" in f:
        return "Trial"
    if f == "today" or f.endswith("/today") or "submission_time" in f or f == "date":
        return "today"
    return None


def suggest_mappings(fields: list[str]) -> dict[str, str]:
    """For each canonical target, pick the first ONA field that matches it."""
    chosen: dict[str, str] = {}
    for field_path in fields:
        target = suggest_target(field_path)
        if target and target not in chosen:
            chosen[target] = field_path
    return chosen


def _csv(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def build_config(post) -> dict[str, Any]:
    """Assemble a use-case config dict from wizard POST data."""
    enid_patterns = _csv(post.get("enid_patterns"))
    hhid_patterns = _csv(post.get("hhid_patterns"))

    data: dict[str, Any] = {
        "use_case": {
            "code": (post.get("code") or "").strip(),
            "name": (post.get("name") or "").strip(),
            "is_active": True,
            "countries": _csv(post.get("countries")),
            "enid_patterns": enid_patterns,
            "hhid_patterns": hhid_patterns,
        },
        "data_source": {
            "backend": post.get("backend") or "ONA",
            "base_url": (post.get("base_url") or "").strip(),
            "token": (post.get("token") or "").strip(),
        },
        "crops": [{"name": c} for c in _csv(post.get("crops"))],
        "trials": [{"name": t} for t in _csv(post.get("trials"))],
        "stages": _csv(post.get("stages")) or ["Validation"],
        "forms": [],
        "event_schedule": [],
        "validation_rules": [],
    }

    # Forms (entries to the project) with their auto-suggested mappings.
    form_count = int(post.get("form_count") or 0)
    for i in range(form_count):
        fid = post.get(f"form-{i}-id")
        if not fid:
            continue
        # Rows rendered from a discovered project carry 'present'; if such a row's
        # include checkbox is unticked, skip it. Manual rows (no 'present') include.
        if post.get(f"form-{i}-present") and not post.get(f"form-{i}-include"):
            continue
        role = post.get(f"form-{i}-role") or "VALIDATION"
        mappings = []
        for t in CANONICAL_TARGETS:
            src = (post.get(f"map-{i}-{t['key']}") or "").strip()
            if not src:
                continue
            m: dict[str, Any] = {"target": t["key"], "source": [src], "transform": t["transform"]}
            if t["key"] == "GEO":
                m["transform_args"] = {"into": ["LAT", "LON", "ALT", "ERR"]}
            mappings.append(m)
        data["forms"].append({"ona_form_id": int(fid), "role": role, "mappings": mappings})

    # Event schedule generated from "number of events" + "interval days".
    num_events = int(post.get("num_events") or 0)
    interval = int(post.get("interval_days") or 14)
    for k in range(1, num_events + 1):
        if k == 1:
            data["event_schedule"].append(
                {"event_key": "Event1", "sequence": 1, "anchor": "SITE_SELECTION",
                 "offset_days": interval})
        else:
            data["event_schedule"].append(
                {"event_key": f"Event{k}", "sequence": k, "anchor": "EVENT1",
                 "offset_days": (k - 1) * interval})

    # Sensible default validation rules.
    if enid_patterns:
        data["validation_rules"].append(
            {"code": "enid_pattern", "type": "REGEX_ID", "severity": "ERROR",
             "params": {"field": "ENID", "patterns": enid_patterns, "message": "Check ENID"}})
    if hhid_patterns:
        data["validation_rules"].append(
            {"code": "hhid_pattern", "type": "REGEX_ID", "severity": "ERROR",
             "params": {"field": "HHID", "patterns": hhid_patterns, "message": "Check HHID"}})
    data["validation_rules"].append(
        {"code": "event_sequence", "type": "EVENT_SEQUENCE", "severity": "WARNING",
         "params": {"message": "Check submission events"}})
    if data["event_schedule"]:
        data["validation_rules"].append(
            {"code": "event_window", "type": "DATE_WINDOW", "severity": "WARNING",
             "params": {"use_schedule": True}})

    return data
