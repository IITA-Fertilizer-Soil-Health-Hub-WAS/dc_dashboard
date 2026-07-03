"""ONA / ODK API client (replaces okapi.R `ona_data_get`).

Pulls form submissions from the ONA REST API with token auth and pagination.
The R app fetched every record per form each day; we do the same but page
through results and let the engine dedupe by `_uuid` + content hash.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
from django.conf import settings


class OnaError(RuntimeError):
    pass


class OnaClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
        page_size: int = 1000,
    ) -> None:
        self.base_url = (base_url or settings.ONA_BASE_URL).rstrip("/")
        self.token = token if token is not None else settings.ONA_TOKEN
        self.timeout = timeout
        self.page_size = page_size

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise OnaError("ONA_TOKEN is not configured")
        return {"Authorization": f"Token {self.token}", "Accept": "application/json"}

    def iter_data(self, form_id: int) -> Iterator[dict[str, Any]]:
        """Yield every submission record for a form, paging via start/limit."""
        url = f"{self.base_url}/api/v1/data/{form_id}.json"
        start = 0
        with httpx.Client(timeout=self.timeout) as client:
            while True:
                resp = client.get(
                    url,
                    headers=self._headers(),
                    params={"start": start, "limit": self.page_size},
                )
                if resp.status_code != 200:
                    raise OnaError(
                        f"ONA form {form_id} returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                batch = resp.json()
                if not batch:
                    break
                yield from batch
                if len(batch) < self.page_size:
                    break
                start += self.page_size

    def get_data(self, form_id: int) -> list[dict[str, Any]]:
        return list(self.iter_data(form_id))

    def list_forms(self) -> list[dict[str, Any]]:
        """List forms the token can access — for discovering a new project's forms.

        Returns simplified dicts: {formid, title, num_of_submissions, last_submission}.
        """
        url = f"{self.base_url}/api/v1/forms.json"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=self._headers())
        if resp.status_code != 200:
            raise OnaError(f"ONA forms listing returned HTTP {resp.status_code}: {resp.text[:200]}")
        forms = []
        for f in resp.json():
            forms.append(
                {
                    "formid": f.get("formid"),
                    "title": f.get("title"),
                    "num_of_submissions": f.get("num_of_submissions"),
                    "last_submission": f.get("last_submission_time"),
                }
            )
        return forms

    def list_projects(self) -> list[dict[str, Any]]:
        """List ONA projects (each maps to a project here) with their forms.

        Returns: [{projectid, name, forms: [{formid, title}]}].
        """
        url = f"{self.base_url}/api/v1/projects.json"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=self._headers())
        if resp.status_code != 200:
            raise OnaError(f"ONA projects listing returned HTTP {resp.status_code}: {resp.text[:200]}")
        projects = []
        for p in resp.json():
            forms = [
                {"formid": f.get("formid"), "title": f.get("name") or f.get("title")}
                for f in (p.get("forms") or [])
            ]
            projects.append({
                "projectid": p.get("projectid"),
                "name": p.get("name"),
                "forms": forms,
            })
        return projects

    def sample_fields(self, form_id: int) -> list[str]:
        """Return the field paths present in the latest submission of a form, to
        help author field mappings without hand-typing ONA paths."""
        for record in self.iter_data(form_id):
            return sorted(record.keys())
        return []
