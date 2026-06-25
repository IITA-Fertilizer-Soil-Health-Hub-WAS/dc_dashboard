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

from .base import BackendError, RemoteForm, RemoteProject
from .odk import OdkBackend


class OdkCentralBackend(OdkBackend):
    type = "ODK_CENTRAL"
    label = "ODK Central"
    supports_discovery = True
    supports_writeback = True

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
