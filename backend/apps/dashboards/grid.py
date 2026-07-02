"""Event-completion grid — the data-driven replacement for the R color-coded
event table. One row per household, one cell per scheduled event, coloured by the
shared event_status() helper (green/amber/red/purple).
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.submissions.models import Submission
from apps.validation.status import event_status, status_color


def build_event_grid(use_case) -> dict[str, Any]:
    today = timezone.localdate()
    schedule = list(use_case.schedule.all())
    event_keys = [e.event_key for e in schedule]

    subs = list(
        Submission.objects.filter(use_case=use_case).select_related(
            "household", "enumerator", "crop"
        )
    )

    households: dict[Any, dict[str, Any]] = {}
    for s in subs:
        if s.household_id is None:
            continue
        hh = households.setdefault(
            s.household_id,
            {
                "id": s.household_id,
                "hhid": s.household.hhid if s.household else "",
                "enid": s.enumerator.enid if s.enumerator else "",
                "crop": s.crop.name if s.crop else None,
                "site": s.household.site_selection_date if s.household else None,
                "submitted": {},
                "event1": None,
            },
        )
        if s.event_date:
            hh["submitted"][s.event_key] = s.event_date
            if s.event_key == "Event1":
                hh["event1"] = s.event_date
        if s.crop and not hh["crop"]:
            hh["crop"] = s.crop.name

    rows = []
    for info in households.values():
        cells = []
        for item in schedule:
            submitted_date = info["submitted"].get(item.event_key)
            anchor = info["site"] if item.anchor == item.Anchor.SITE_SELECTION else info["event1"]
            st = event_status(
                event_date=submitted_date,
                anchor_date=anchor,
                offset_days=item.target_offset_for_crop(info["crop"]),
                grace_days=item.grace_days,
                today=today,
            )
            cells.append(
                {
                    "event_key": item.event_key,
                    "status": st,
                    "color": status_color(st),
                    "date": submitted_date.isoformat() if submitted_date else "",
                }
            )
        rows.append({"id": info["id"], "hhid": info["hhid"], "enid": info["enid"], "cells": cells})

    rows.sort(key=lambda r: r["hhid"])
    return {"event_keys": event_keys, "rows": rows}
