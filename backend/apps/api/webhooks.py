"""Collection-server webhook → instant re-sync.

ODK Central and ONA can POST here when a submission lands; we treat it purely as
a trigger (not a data source) and enqueue an idempotent re-pull of the project,
so it stays server-agnostic and never double-counts. A shared secret guards the
endpoint and a short debounce collapses bursts into one sync.
"""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.ingestion.tasks import webhook_ingest_task
from apps.usecases.models import UseCase


def _provided_token(request) -> str:
    return (
        request.headers.get("X-Webhook-Token")
        or request.GET.get("token")
        or ""
    )


@csrf_exempt
@require_POST
def collection_webhook(request, code: str):
    """Enqueue a re-sync of `code`'s project. External callers authenticate with
    the shared COLLECTION_WEBHOOK_SECRET (header or ?token=)."""
    secret = settings.COLLECTION_WEBHOOK_SECRET
    if not secret:
        return JsonResponse({"detail": "Webhooks are not enabled."}, status=503)
    if not constant_time_compare(_provided_token(request), secret):
        return JsonResponse({"detail": "Invalid webhook token."}, status=401)

    uc = UseCase.objects.filter(code=code, is_active=True).first()
    if uc is None:
        return JsonResponse({"detail": "Unknown or inactive project."}, status=404)

    # Debounce: collapse a burst of hits for this project into one sync.
    debounce_key = f"webhook-sync:{code}"
    if cache.get(debounce_key):
        return JsonResponse({"status": "already_queued", "code": code}, status=202)
    cache.set(debounce_key, 1, settings.COLLECTION_WEBHOOK_DEBOUNCE_SECONDS)

    webhook_ingest_task.delay(code)
    return JsonResponse({"status": "queued", "code": code}, status=202)
