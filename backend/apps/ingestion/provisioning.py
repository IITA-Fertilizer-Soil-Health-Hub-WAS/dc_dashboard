"""Mirror platform accounts onto collection servers.

When ``AUTO_PROVISION_COLLECTORS`` is on, the platform keeps the collection tool
(ODK Central, ONA, Kobo) in step with its own accounts so a collector never has
to be set up twice:

* **on user creation** — create a sign-in account on every backend the user's
  organization already operates (a "server-wide" ``CollectorAccount`` with no
  project), and
* **on a project grant** — create/link the account on that project's backend and
  share the project with it (a per-project ``CollectorAccount``).

Both are driven by signals (see ``signals.py``); this module holds the logic so it
is unit-testable with a fake backend and callable from a management command.

Everything here fails soft: a backend error is caught and recorded on the
``CollectorAccount`` as ``FAILED`` — provisioning must never block user creation
or an access grant. The feature is OFF by default; enable it per environment only
after verifying each backend against a live/sandbox server.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.ingestion.backends.base import BackendError, ProvisionResult
from apps.ingestion.backends.registry import get_backend_for
from apps.submissions.models import CollectorAccount

log = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(getattr(settings, "AUTO_PROVISION_COLLECTORS", False))


def _remote_project_id(project) -> str:
    """The backend's own id for the project (ODK Central/ONA numeric project id),
    read from its DataSource config. Empty when the backend doesn't group by
    project (Kobo uses the asset uid, resolved per form elsewhere)."""
    ds = getattr(project, "data_source", None)
    if ds is None:
        return ""
    return str((ds.config or {}).get("project_id") or "")


def _record(user, project, backend_type: str, result: ProvisionResult,
            *, status: str) -> CollectorAccount:
    acct, _ = CollectorAccount.objects.update_or_create(
        user=user, project=project,
        defaults={
            "backend": backend_type,
            "remote_id": result.remote_id,
            "username": result.username,
            "status": status,
            "message": result.message[:2000],
            "provisioned_at": timezone.now() if result.ok else None,
        },
    )
    return acct


def provision_for_project(user, project) -> CollectorAccount:
    """Create/link ``user``'s account on ``project``'s backend and share the
    project with it. Idempotent and fail-soft; returns the CollectorAccount row."""
    backend = get_backend_for(project)
    backend_type = getattr(backend, "type", "") or "UNKNOWN"
    if not getattr(backend, "supports_provisioning", False):
        return _record(user, project, backend_type,
                       ProvisionResult(ok=False, message=f"{backend.label} has no provisioning."),
                       status=CollectorAccount.Status.UNSUPPORTED)
    try:
        result = backend.provision_account(
            username=user.email, email=user.email, full_name=user.full_name,
            remote_project_id=_remote_project_id(project),
        )
    except (BackendError, Exception) as exc:  # noqa: BLE001 — never let this bubble
        log.warning("Provisioning %s for %s on %s failed: %s", user, project, backend_type, exc)
        return _record(user, project, backend_type,
                       ProvisionResult(ok=False, message=str(exc)),
                       status=CollectorAccount.Status.FAILED)
    status = _status_for(result)
    _surface_secret(user, project, result)
    return _record(user, project, backend_type, result, status=status)


def provision_new_user(user) -> list[CollectorAccount]:
    """On user creation, create a server-wide account on each distinct backend the
    user's organization already operates, so their sign-in exists ahead of any
    project grant. No org / no configured backends → nothing to do."""
    org = getattr(user, "organization", None)
    if org is None:
        return []
    seen: set[str] = set()
    accounts: list[CollectorAccount] = []
    # One representative project per backend type in the org — enough to reach the
    # server; the server-wide account (project=None) is created once per backend.
    for project in org.projects.select_related("data_source").all():
        backend = get_backend_for(project)
        btype = getattr(backend, "type", "") or "UNKNOWN"
        if btype in seen:
            continue
        seen.add(btype)
        if not getattr(backend, "supports_provisioning", False):
            continue
        try:
            result = backend.provision_account(
                username=user.email, email=user.email, full_name=user.full_name,
            )
        except (BackendError, Exception) as exc:  # noqa: BLE001
            log.warning("Server-wide provisioning for %s on %s failed: %s", user, btype, exc)
            accounts.append(_record(user, None, btype, ProvisionResult(ok=False, message=str(exc)),
                                    status=CollectorAccount.Status.FAILED))
            continue
        _surface_secret(user, None, result)
        accounts.append(_record(user, None, btype, result, status=_status_for(result)))
    return accounts


def _status_for(result: ProvisionResult) -> str:
    if not result.ok:
        return CollectorAccount.Status.FAILED
    if result.already_existed:
        return CollectorAccount.Status.LINKED
    return CollectorAccount.Status.ACTIVE


def _surface_secret(user, project, result: ProvisionResult) -> None:
    """The one-time password/token a server generates is never stored in
    cleartext. When present, log it once (INFO) so an operator can retrieve it
    from the audit log and hand it to the collector, then it's gone."""
    if result.ok and result.secret:
        scope = project.code if project is not None else "(server-wide)"
        log.info("Collector credential for %s @ %s: username=%s secret=%s (store securely; "
                 "not persisted)", user.email, scope, result.username, result.secret)
