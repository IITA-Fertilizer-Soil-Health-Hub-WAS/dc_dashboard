"""Shared write-back for ODK/OpenRosa-family servers (ONA, ODK Central, Kobo…).

Editing an ODK submission is a standard, server-agnostic flow:

1. fetch the original instance XML,
2. change the edited field elements,
3. set a fresh ``meta/instanceID`` and put the old one in ``meta/deprecatedID``,
4. re-submit the edited XML.

Only steps 1 and 4 (the HTTP transport) differ per server, so this base class
implements the generic parts (2 + 3 + orchestration) and each concrete backend
supplies ``_fetch_instance_xml`` / ``_submit_edited_xml``.
"""
from __future__ import annotations

import uuid as uuidlib
from typing import Any
from xml.etree import ElementTree as ET

from .base import CollectionBackend, WriteResult


def _local(tag: str) -> str:
    """Local tag name without XML namespace (``{ns}name`` -> ``name``)."""
    return tag.rsplit("}", 1)[-1]


def _find_by_path(root: ET.Element, path: str) -> ET.Element | None:
    """Descend a '/'-separated path, matching elements by local name only
    (namespace-agnostic, so it works across ODK servers)."""
    node = root
    for part in [p for p in path.split("/") if p]:
        match = next((c for c in list(node) if _local(c.tag) == part), None)
        if match is None:
            return None
        node = match
    return node if node is not root else None


def _find_child(node: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in list(node) if _local(c.tag) == name), None)


def build_edited_instance(
    original_xml: str, path_changes: dict[str, Any], new_instance_id: str | None = None
) -> tuple[str, str | None]:
    """Return (edited_xml, old_instance_id).

    `path_changes` maps a server field path (e.g. ``intro/enumerator_id``) to its
    new value. Generic: no ONA-specific assumptions beyond the ODK instance shape.
    """
    root = ET.fromstring(original_xml)

    for path, value in path_changes.items():
        el = _find_by_path(root, path)
        if el is not None:
            el.text = "" if value is None else str(value)

    # Bump the instance id and record the previous one as deprecated (ODK edit).
    old_instance_id = None
    meta = _find_child(root, "meta")
    if meta is not None:
        iid = _find_child(meta, "instanceID")
        if iid is not None:
            old_instance_id = iid.text
            dep = _find_child(meta, "deprecatedID")
            if dep is None:
                dep = ET.SubElement(meta, "deprecatedID")
            dep.text = old_instance_id
            iid.text = new_instance_id or f"uuid:{uuidlib.uuid4()}"

    return ET.tostring(root, encoding="unicode"), old_instance_id


class OdkBackend(CollectionBackend):
    """Base for ODK/OpenRosa servers. Subclasses implement the two endpoints."""

    def _resolve_paths(self, submission, changes: dict[str, Any]) -> dict[str, Any]:
        """Translate canonical field changes (ENID, HHID, …) to the server's field
        paths using the form's FieldMappings — so write-back is config-driven too."""
        mapping = {
            m.target_field: (m.source_paths[0] if m.source_paths else None)
            for m in submission.form.mappings.all()
        }
        resolved: dict[str, Any] = {}
        for field_key, value in changes.items():
            path = mapping.get(field_key)
            if path:
                resolved[path] = value
        return resolved

    def _fetch_instance_xml(self, form_id, data_id) -> str:
        raise NotImplementedError

    def _submit_edited_xml(self, form_id, xml: str) -> str | None:
        raise NotImplementedError

    def push_edit(self, submission, changes: dict[str, Any]) -> WriteResult:
        data_id = submission.ona_submission_id
        if not data_id:
            return WriteResult(ok=False, message="No source record id to edit")

        path_changes = self._resolve_paths(submission, changes)
        if not path_changes:
            return WriteResult(ok=False, message="No edited fields are mapped to the source form")

        try:
            original = self._fetch_instance_xml(submission.form.ona_form_id, data_id)
            edited_xml, old_iid = build_edited_instance(original, path_changes)
            remote_id = self._submit_edited_xml(submission.form.ona_form_id, edited_xml)
        except Exception as exc:  # network / server / parse errors
            return WriteResult(ok=False, message=f"Write-back failed: {exc}")

        return WriteResult(ok=True, message="Edited submission accepted by source",
                           remote_id=remote_id or old_iid)
