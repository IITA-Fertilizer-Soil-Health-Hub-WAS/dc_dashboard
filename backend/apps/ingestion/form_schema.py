"""Turn a collection server's form definition (ODK/ONA form.json) into a flat
schema — an ordered list of {path, label, group, type} — so submissions can be
rendered with human question labels grouped by section, instead of raw ODK
field paths. (Adapted from SDMT's labelled QC view.)
"""
from __future__ import annotations

_GROUP_TYPES = {"group", "repeat"}


def pick_label(label, default: str = "") -> str:
    """A label may be a plain string or a {language: text} map (multi-language)."""
    if isinstance(label, str):
        return label.strip()
    if isinstance(label, dict) and label:
        first = next(iter(label.values()))
        return str(first).strip()
    return default


def flatten_children(children, prefix: str = "", group_label: str = "") -> list[dict]:
    """Recursively flatten an ODK/ONA form's `children` tree into leaf questions,
    building the ODK path (group/subgroup/name) and carrying the nearest group's
    label as the section."""
    out: list[dict] = []
    for child in children or []:
        name = child.get("name")
        if not name:
            continue
        ctype = child.get("type", "")
        label = pick_label(child.get("label"))
        path = f"{prefix}{name}" if prefix else name
        if ctype in _GROUP_TYPES:
            out.extend(flatten_children(
                child.get("children", []), prefix=f"{path}/",
                group_label=label or group_label,
            ))
        else:
            out.append({
                "path": path,
                "label": label or name,
                "group": group_label,
                "type": ctype,
            })
    return out


def parse_form_json(form_json: dict) -> list[dict]:
    """The top-level entry: an ODK/ONA form.json → flat field schema."""
    return flatten_children((form_json or {}).get("children", []))


def label_map(schema: list[dict]) -> dict:
    """path → {label, group} for quick lookup when rendering a submission."""
    return {f["path"]: {"label": f.get("label") or f["path"], "group": f.get("group", "")}
            for f in (schema or []) if f.get("path")}


def sync_use_case_schemas(use_case) -> dict:
    """Fetch + cache each form's field schema for one use case, so submissions
    render with human question labels. Returns {form_server_ref: field_count};
    a backend that doesn't support schema fetch (returns []) leaves the form as-is.
    """
    from apps.ingestion.backends.registry import get_backend_for

    backend = get_backend_for(use_case)
    result: dict = {}
    for form in use_case.forms.all():
        ref = form.server_ref
        if not ref:
            continue
        try:
            schema = backend.get_form_schema(ref)
        except Exception as exc:  # keep going across forms; report per-form
            result[ref] = f"error: {exc}"
            continue
        if schema:
            form.field_schema = schema
            form.save(update_fields=["field_schema"])
        result[ref] = len(schema)
    return result
