"""KoboToolbox backend.

Kobo's KPI API (v2) is used for discovery + fetch; write-back reuses the shared
ODK edit flow against KoBoCAT (Kobo's OpenRosa server, onadata-derived — same
deprecatedID edit mechanism as ONA). Config keys:

* ``base_url``  — KPI base (default https://kf.kobotoolbox.org)
* ``config.kc_url`` — KoBoCAT/OpenRosa base for write-back (default https://kc.kobotoolbox.org)

Each Kobo survey asset is surfaced as a project with a single form (Kobo has no
ONA-style project grouping).
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from .base import BackendError, ProvisionResult, RemoteForm, RemoteProject
from .odk import OdkBackend


class KoboBackend(OdkBackend):
    type = "KOBO"
    label = "KoboToolbox"
    supports_discovery = True
    supports_writeback = True
    supports_provisioning = True

    def _kpi(self) -> str:
        return (self.base_url or "https://kf.kobotoolbox.org").rstrip("/")

    def _kc(self) -> str:
        return (self.config.get("kc_url") or "https://kc.kobotoolbox.org").rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise BackendError("Kobo API token is not configured")
        return {"Authorization": f"Token {self.token}", "Accept": "application/json"}

    def _get_json(self, url: str) -> Any:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=self._headers())
        if resp.status_code != 200:
            raise BackendError(f"Kobo HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def discover_projects(self) -> list[RemoteProject]:
        data = self._get_json(f"{self._kpi()}/api/v2/assets/?format=json")
        projects = []
        for a in data.get("results", []):
            if a.get("asset_type") != "survey":
                continue
            uid, name = a.get("uid"), a.get("name") or a.get("uid")
            projects.append(RemoteProject(id=uid, name=name, forms=[RemoteForm(id=uid, title=name)]))
        return projects

    def list_forms(self) -> list[RemoteForm]:
        return [f for p in self.discover_projects() for f in p.forms]

    def iter_submissions(self, form_id) -> Iterator[dict[str, Any]]:
        data = self._get_json(f"{self._kpi()}/api/v2/assets/{form_id}/data/?format=json")
        yield from data.get("results", [])

    def fetch_attachment(self, attachment: dict[str, Any]) -> tuple[bytes, str]:
        """Kobo embeds each attachment's `download_url` (on KoBoCAT) in the record;
        fetch it with the API token."""
        url = attachment.get("download_url")
        if not url:
            raise BackendError("Kobo attachment has no download_url")
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"Authorization": f"Token {self.token}"})
        if resp.status_code != 200:
            raise BackendError(f"Kobo attachment HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.content, resp.headers.get("Content-Type", "application/octet-stream")

    # --- write-back via KoBoCAT (OpenRosa) ---
    def _fetch_instance_xml(self, form_id, data_id) -> str:
        url = f"{self._kc()}/api/v1/data/{form_id}/{data_id}.xml"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers={"Authorization": f"Token {self.token}",
                                            "Accept": "application/xml"})
        if resp.status_code != 200:
            raise BackendError(f"Kobo fetch instance HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.text

    def _submit_edited_xml(self, form_id, xml: str) -> str | None:
        url = f"{self._kc()}/api/v1/submissions"
        files = {"xml_submission_file": ("submission.xml", xml.encode(), "application/xml")}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers={"Authorization": f"Token {self.token}"}, files=files)
        if resp.status_code not in (200, 201, 202):
            raise BackendError(f"Kobo submit edit HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    # --- provisioning ---
    # Verify against a live Kobo before enabling AUTO_PROVISION_COLLECTORS.
    def provision_account(
        self, *, username: str, email: str = "", full_name: str = "",
        remote_project_id: str = "",
    ) -> ProvisionResult:
        """Kobo (hosted KPI) has no public API to create arbitrary accounts —
        collectors self-register or a self-hosted admin creates them. What the API
        *does* allow is granting an existing Kobo user access to a survey asset via
        a permission-assignment. So: if a project (asset uid) is given, share it
        with ``username`` (``add_submissions`` + ``view_asset``); account creation
        is reported as a manual step."""
        uname = (username or email or "").split("@")[0]
        if not uname:
            return ProvisionResult(ok=False, message="Kobo needs a username or email")
        if not remote_project_id:
            return ProvisionResult(
                ok=True, username=uname, already_existed=True,
                message="Kobo accounts are self-registered; nothing to create until a survey is shared.",
            )
        user_url = f"{self._kpi()}/api/v2/users/{uname}/"
        assigned = []
        for perm in ("view_asset", "add_submissions"):
            perm_url = f"{self._kpi()}/api/v2/permissions/{perm}/"
            resp = self._post_json(
                f"{self._kpi()}/api/v2/assets/{remote_project_id}/permission-assignments/",
                {"user": user_url, "permission": perm_url},
            )
            if resp.status_code in (200, 201):
                assigned.append(perm)
            elif resp.status_code not in (400, 409):  # 400/409 = already granted / bad user
                raise BackendError(
                    f"Kobo permission HTTP {resp.status_code}: {resp.text[:200]}")
        return ProvisionResult(
            ok=True, remote_id=uname, username=uname,
            url=f"{self._kpi()}/#/forms/{remote_project_id}", already_existed=True,
            message=f"Shared Kobo survey with {uname} ({', '.join(assigned) or 'already had access'}).",
        )

    def _post_json(self, url: str, body: dict):
        headers = {**self._headers(), "Content-Type": "application/json"}
        with httpx.Client(timeout=30.0) as client:
            return client.post(url, headers=headers, json=body)
