"""ODK Central backend.

ODK Central groups forms under numeric projects (maps cleanly to our project ==
use case). Discovery + fetch use the REST/OData API; write-back reuses the shared
ODK edit flow (Central accepts edited submissions with a deprecatedID via the
OpenRosa submission endpoint). Auth uses a bearer token (App User / session).

Config:
* ``base_url`` — Central base, e.g. https://central.example.org
* ``config.project_id`` — required for fetch/write-back endpoints
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from .base import BackendError, PublishResult, RemoteForm, RemoteProject
from .odk import OdkBackend

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class OdkCentralBackend(OdkBackend):
    type = "ODK_CENTRAL"
    label = "ODK Central"
    supports_discovery = True
    supports_writeback = True
    supports_publish = True

    def _base(self) -> str:
        return (self.base_url or "").rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise BackendError("ODK Central token is not configured")
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def _project_id(self):
        pid = self.config.get("project_id")
        if not pid:
            raise BackendError("ODK Central requires config.project_id")
        return pid

    def _get_json(self, path: str) -> Any:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{self._base()}{path}", headers=self._headers())
        if resp.status_code != 200:
            raise BackendError(f"ODK Central HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def discover_projects(self) -> list[RemoteProject]:
        projects = []
        for p in self._get_json("/v1/projects"):
            pid = p.get("id")
            forms = self._get_json(f"/v1/projects/{pid}/forms")
            remote_forms = [RemoteForm(id=str(f.get("xmlFormId")), title=f.get("name") or "")
                            for f in forms]
            projects.append(RemoteProject(id=str(pid), name=p.get("name") or str(pid),
                                          forms=remote_forms))
        return projects

    def list_forms(self) -> list[RemoteForm]:
        forms = self._get_json(f"/v1/projects/{self._project_id()}/forms")
        return [RemoteForm(id=str(f.get("xmlFormId")), title=f.get("name") or "") for f in forms]

    def iter_submissions(self, form_id) -> Iterator[dict[str, Any]]:
        # OData feed: /v1/projects/{pid}/forms/{fid}.svc/Submissions
        path = f"/v1/projects/{self._project_id()}/forms/{form_id}.svc/Submissions"
        yield from self._get_json(path).get("value", [])

    # --- write-back ---
    def _fetch_instance_xml(self, form_id, data_id) -> str:
        path = f"/v1/projects/{self._project_id()}/forms/{form_id}/submissions/{data_id}.xml"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{self._base()}{path}",
                              headers={"Authorization": f"Bearer {self.token}",
                                       "Accept": "application/xml"})
        if resp.status_code != 200:
            raise BackendError(f"Central fetch instance HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.text

    def _submit_edited_xml(self, form_id, xml: str) -> str | None:
        path = f"/v1/projects/{self._project_id()}/submission"
        files = {"xml_submission_file": ("submission.xml", xml.encode(), "application/xml")}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{self._base()}{path}",
                               headers={"Authorization": f"Bearer {self.token}"}, files=files)
        if resp.status_code not in (200, 201, 202):
            raise BackendError(f"Central submit edit HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    # --- publish ---
    def publish_form(self, xlsx: bytes, *, form_id: str = "", title: str = "") -> PublishResult:
        """Convert + publish an XLSForm in one call:
        ``POST /v1/projects/{pid}/forms?publish=true`` with the .xlsx body.
        Central runs pyxform server-side; a conversion error returns HTTP 400."""
        pid = self._project_id()
        path = f"/v1/projects/{pid}/forms?publish=true&ignoreWarnings=true"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": XLSX_MEDIA}
        if form_id:
            headers["X-XlsForm-FormId-Fallback"] = form_id
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(f"{self._base()}{path}", headers=headers, content=xlsx)
        except Exception as exc:
            return PublishResult(ok=False, message=f"Could not reach ODK Central: {exc}")

        if resp.status_code not in (200, 201):
            return PublishResult(ok=False, message=_central_error(resp))

        data = resp.json()
        xml_form_id = str(data.get("xmlFormId") or form_id)
        return PublishResult(
            ok=True,
            server_form_id=xml_form_id,
            version=str(data.get("version") or ""),
            title=data.get("name") or title,
            url=f"{self._base()}/#/projects/{pid}/forms/{xml_form_id}",
            message="Form published to ODK Central.",
        )


def _central_error(resp) -> str:
    """Best-effort human message from a Central error response."""
    try:
        body = resp.json()
        msg = body.get("message") or ""
        details = body.get("details") or {}
        warnings = details.get("warnings") or details.get("error") or ""
        return f"ODK Central rejected the form (HTTP {resp.status_code}): {msg} {warnings}".strip()
    except Exception:
        return f"ODK Central HTTP {resp.status_code}: {resp.text[:200]}"
