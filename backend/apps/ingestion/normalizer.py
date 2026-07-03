"""Generic field normalizer — the config-driven replacement for the per-use-case
rename()/coalesce()/separate()/mutate() blocks in dataprocessing.R.

Given a FormDefinition's FieldMapping rows and one raw ONA record, produce a flat
dict of canonical fields. ONA returns group paths as flat slash-separated keys
(e.g. "intro/event"), so a source path is a direct dict lookup.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from apps.projects.models import FieldMapping


def _first_non_null(record: dict, paths: list[str]) -> Any:
    for p in paths:
        val = record.get(p)
        if val not in (None, ""):
            return val
    return None


def _parse_date(value: Any) -> str | None:
    """Parse common ONA date/datetime strings to an ISO date string."""
    if value in (None, ""):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[: len(fmt) + 4], fmt).date().isoformat()
        except ValueError:
            continue
    # Last resort: take the leading YYYY-MM-DD if present.
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def _resolve_crop(value: Any, alias_map: dict[str, str]) -> Any:
    """Map a raw crop value to its canonical name via the alias map."""
    if value in (None, ""):
        return None
    return alias_map.get(str(value), value)


def normalize_record(
    mappings: list[FieldMapping],
    record: dict,
    crop_alias_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply all mappings to one raw record. Returns canonical field -> value."""
    alias_map = crop_alias_map or {}
    out: dict[str, Any] = {}

    for m in mappings:
        t = m.transform
        if t == FieldMapping.Transform.CONST:
            out[m.target_field] = m.transform_args.get("value")
            continue

        raw = _first_non_null(record, m.source_paths)

        if t == FieldMapping.Transform.DIRECT:
            out[m.target_field] = raw
        elif t == FieldMapping.Transform.COALESCE:
            out[m.target_field] = raw  # _first_non_null already coalesced sources
        elif t == FieldMapping.Transform.DATE_PARSE:
            out[m.target_field] = _parse_date(raw)
        elif t == FieldMapping.Transform.LOOKUP:
            out[m.target_field] = _resolve_crop(raw, alias_map)
        elif t == FieldMapping.Transform.REGEX_SUB:
            pattern = m.transform_args.get("from", "")
            repl = m.transform_args.get("to", "")
            out[m.target_field] = re.sub(pattern, repl, str(raw)) if raw is not None else None
        elif t == FieldMapping.Transform.SPLIT_GEOPOINT:
            # ONA geopoint = "lat lon alt err"; split into named components.
            into = m.transform_args.get("into", ["LAT", "LON", "ALT", "ERR"])
            parts = str(raw).split() if raw else []
            for i, name in enumerate(into):
                out[name] = parts[i] if i < len(parts) else None
        else:  # pragma: no cover - defensive
            out[m.target_field] = raw

    return out


def build_crop_alias_map(project) -> dict[str, str]:
    """Map every crop alias (and canonical name) -> canonical name for LOOKUPs."""
    alias_map: dict[str, str] = {}
    for crop in project.crops.all():
        alias_map[crop.name] = crop.name
        for alias in crop.aliases:
            alias_map[alias] = crop.name
    return alias_map
