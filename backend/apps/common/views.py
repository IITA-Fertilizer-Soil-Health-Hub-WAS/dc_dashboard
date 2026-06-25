from __future__ import annotations

from django.db import connection
from django.http import JsonResponse


def healthcheck(request) -> JsonResponse:
    """Liveness + DB readiness probe for containers / load balancers."""
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # pragma: no cover - exercised only on DB outage
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse({"status": "ok" if db_ok else "degraded", "db": db_ok}, status=status)
