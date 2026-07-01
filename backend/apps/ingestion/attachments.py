"""Media attachments (photos, audio, signatures, …) carried on a submission.

ODK/ONA records embed an `_attachments` list; each entry names a stored file and
its mimetype, and the answering question's value is that file's basename. This
turns the raw list into review-ready descriptors so reviewers can *see* the
photo next to the answer (adapted from SDMT's media-in-QC view). Bytes are never
stored here — they're streamed on demand through an authenticated proxy view.
"""
from __future__ import annotations

_IMAGE_TYPES = ("image/",)


def _basename(path: str) -> str:
    return (path or "").rsplit("/", 1)[-1]


def parse_attachments(raw_payload: dict) -> list[dict]:
    """Flatten a record's `_attachments` into descriptors:
    {id, name, mimetype, is_image, question} — `question` is the field path whose
    answer references this file (best-effort basename match), else "".
    """
    payload = raw_payload or {}
    attachments = payload.get("_attachments") or []
    if not isinstance(attachments, list):
        return []

    # Map each attachment basename back to the question that referenced it.
    ref_by_name: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, str) and value and _basename(value) == value and "." in value:
            ref_by_name.setdefault(value, key)

    out: list[dict] = []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        name = att.get("name") or _basename(att.get("filename", ""))
        if not name:
            continue
        mimetype = att.get("mimetype") or ""
        out.append({
            "id": att.get("id"),
            "name": name,
            "mimetype": mimetype,
            "is_image": mimetype.startswith(_IMAGE_TYPES),
            "question": ref_by_name.get(name, ""),
            "download_url": att.get("download_url") or "",
        })
    return out


def guess_mimetype(name: str) -> str:
    """Best-effort content type from a filename, for servers (ODK Central) that
    list attachments by name without a mimetype."""
    import mimetypes

    return mimetypes.guess_type(name)[0] or "application/octet-stream"
