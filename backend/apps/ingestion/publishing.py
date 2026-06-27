"""Publish an uploaded XLSForm to a use case's collection server, then record it.

Ties the backend `publish_form` primitive (Stage A1) to a FormDefinition: on a
successful server-side conversion + publish, create/refresh the form row, store
the uploaded XLSForm, and stamp the publish metadata. Server-agnostic — the
server-specific work lives behind CollectionBackend.
"""
from __future__ import annotations

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.usecases.models import FormDefinition

from .backends.base import PublishResult
from .backends.registry import get_backend_for


def publish_xlsform(
    use_case, xlsx: bytes, *, filename: str, role: str, title: str = ""
) -> tuple[FormDefinition | None, PublishResult]:
    """Push an XLSForm to the use case's server and record the resulting form."""
    backend = get_backend_for(use_case)
    if not getattr(backend, "supports_publish", False):
        return None, PublishResult(
            ok=False, message=f"{backend.label or backend.type} does not support publishing."
        )

    result = backend.publish_form(xlsx, title=title)
    if not result.ok:
        return None, result

    server_id = result.server_form_id or ""
    ona_id = int(server_id) if server_id.isdigit() else None
    form, _ = FormDefinition.objects.update_or_create(
        use_case=use_case,
        server_form_id=server_id,
        defaults={
            "ona_form_id": ona_id,
            "title": result.title or title,
            "role": role,
            "version": result.version,
            "publish_status": FormDefinition.PublishStatus.PUBLISHED,
            "published_at": timezone.now(),
        },
    )
    form.xlsform.save(filename, ContentFile(xlsx), save=True)
    return form, result
