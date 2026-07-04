"""Turn a project's DataSource into "how to collect this form" info.

The per-form overview shows the collection server URL and an ODK Collect
configuration QR (the zlib+base64 settings blob ODK Collect scans under
Configure via QR code). We deliberately encode only the server URL — never a
project token — so the QR is safe to display; the collector still authenticates.
"""
from __future__ import annotations

import base64
import json
import zlib

import segno
from django.conf import settings


def collect_server_url(project) -> str:
    """Best-effort OpenRosa/collection server URL a phone enters, per backend."""
    ds = getattr(project, "data_source", None)
    if ds is None:
        return ""
    base = (ds.base_url or "").rstrip("/")
    cfg = ds.config or {}
    pid = cfg.get("project_id")
    if ds.backend == "ONA" and base and pid:
        return f"{base}/projects/{pid}"
    if ds.backend == "KOBO":
        return (cfg.get("kc_url") or getattr(settings, "KOBO_BASE_URL", "")).rstrip("/")
    if ds.backend == "ODK_CENTRAL":
        # The hub's ODK Central deployment is the default; a project may override
        # by setting its own base_url on the DataSource.
        return base or getattr(settings, "ODK_CENTRAL_BASE_URL", "").rstrip("/")
    return base  # ONA base without a project id


def collect_qr_data_uri(server_url: str, project_name: str = "") -> str:
    """An ODK Collect 'Configure via QR code' image as a data: URI (inline SVG)."""
    if not server_url:
        return ""
    payload = {"general": {"server_url": server_url}, "admin": {}}
    if project_name:
        payload["project"] = {"name": project_name}
    blob = base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
    return segno.make(blob, error="m").svg_data_uri(scale=4, border=2, dark="#0d5c3f")
