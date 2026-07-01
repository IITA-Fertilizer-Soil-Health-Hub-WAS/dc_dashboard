"""ONA / ODK backend.

Discovery + fetch wrap OnaClient. Write-back uses the shared ODK edit flow
(OdkBackend): fetch the instance XML, edit it, re-submit with a deprecatedID.
Only ONA's two HTTP endpoints live here; the edit logic is server-agnostic.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
from django.conf import settings

from ..ona_client import OnaClient
from .base import PublishResult, RemoteForm, RemoteProject
from .odk import OdkBackend


class OnaBackend(OdkBackend):
    type = "ONA"
    label = "ONA / ODK"
    supports_discovery = True
    supports_writeback = True  # gated globally by settings.WRITEBACK_ENABLED
    supports_publish = True

    def _client(self) -> OnaClient:
        return OnaClient(base_url=self.base_url or None, token=self.token or None)

    def _base(self) -> str:
        return (self.base_url or settings.ONA_BASE_URL).rstrip("/")

    def _token(self) -> str:
        return self.token or settings.ONA_TOKEN

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._token()}"}

    # --- discovery / fetch ---
    def discover_projects(self) -> list[RemoteProject]:
        projects = []
        for p in self._client().list_projects():
            forms = [RemoteForm(id=str(f["formid"]), title=f.get("title") or "")
                     for f in p.get("forms", [])]
            projects.append(RemoteProject(id=str(p.get("projectid")), name=p.get("name") or "", forms=forms))
        return projects

    def list_forms(self) -> list[RemoteForm]:
        return [RemoteForm(id=str(f["formid"]), title=f.get("title") or "")
                for f in self._client().list_forms()]

    def iter_submissions(self, form_id) -> Iterator[dict[str, Any]]:
        yield from self._client().iter_data(int(form_id))

    def sample_fields(self, form_id) -> list[str]:
        return self._client().sample_fields(int(form_id))

    def get_form_schema(self, form_id) -> list[dict[str, Any]]:
        """ONA XForm JSON: GET /api/v1/forms/{id}/form.json → flat field schema."""
        from apps.ingestion.form_schema import parse_form_json

        url = f"{self._base()}/api/v1/forms/{int(form_id)}/form.json"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=self._headers())
        if resp.status_code != 200:
            raise RuntimeError(f"form.json HTTP {resp.status_code}: {resp.text[:200]}")
        return parse_form_json(resp.json())

    def fetch_attachment(self, attachment: dict[str, Any]) -> tuple[bytes, str]:
        """Media bytes for a submission photo: GET /api/v1/files/{id}. We follow
        redirects to the stored object."""
        att_id = attachment.get("id")
        if att_id is None:
            raise RuntimeError("ONA attachment has no file id")
        url = f"{self._base()}/api/v1/files/{int(att_id)}"
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url, headers=self._headers())
        if resp.status_code != 200:
            raise RuntimeError(f"attachment HTTP {resp.status_code}: {resp.text[:200]}")
        ctype = resp.headers.get("Content-Type", "application/octet-stream")
        return resp.content, ctype

    # --- write-back endpoints (ODK edit flow) ---
    def _fetch_instance_xml(self, form_id, data_id) -> str:
        """Original submission as XML: GET /api/v1/data/{form}/{data_id}.xml"""
        url = f"{self._base()}/api/v1/data/{int(form_id)}/{data_id}.xml"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers={**self._headers(), "Accept": "application/xml"})
        if resp.status_code != 200:
            raise RuntimeError(f"fetch instance HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.text

    def _submit_edited_xml(self, form_id, xml: str) -> str | None:
        """Re-submit the edited instance via the OpenRosa endpoint:
        POST /api/v1/submissions with the XML as `xml_submission_file`."""
        url = f"{self._base()}/api/v1/submissions"
        files = {"xml_submission_file": ("submission.xml", xml.encode(), "application/xml")}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=self._headers(), files=files)
        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(f"submit edit HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return str(resp.json().get("id") or resp.json().get("instanceID") or "")
        except Exception:
            return None

    # --- publish ---
    def publish_form(self, xlsx: bytes, *, form_id: str = "", title: str = "") -> PublishResult:
        """Upload + publish an XLSForm: ``POST /api/v1/projects/{pid}/forms`` (or
        ``/api/v1/forms``) with the .xlsx as ``xls_file``. ONA converts server-side."""
        project_id = self.config.get("project_id")
        if project_id:
            url = f"{self._base()}/api/v1/projects/{project_id}/forms"
        else:
            url = f"{self._base()}/api/v1/forms"
        files = {"xls_file": ("form.xlsx", xlsx, XLSX_MEDIA)}
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, headers=self._headers(), files=files)
        except Exception as exc:
            return PublishResult(ok=False, message=f"Could not reach ONA: {exc}")

        if resp.status_code not in (200, 201):
            return PublishResult(ok=False, message=_ona_error(resp))

        data = resp.json()
        formid = str(data.get("formid") or "")
        return PublishResult(
            ok=True,
            server_form_id=formid,
            version=str(data.get("version") or ""),
            title=data.get("title") or title,
            url=f"{self._base()}/{data.get('id_string', '')}".rstrip("/"),
            message="Form published to ONA.",
        )


XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ona_error(resp) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            msg = body.get("text") or body.get("detail") or body.get("xform") or str(body)
        else:
            msg = str(body)
        return f"ONA rejected the form (HTTP {resp.status_code}): {msg}"[:400]
    except Exception:
        return f"ONA HTTP {resp.status_code}: {resp.text[:200]}"
