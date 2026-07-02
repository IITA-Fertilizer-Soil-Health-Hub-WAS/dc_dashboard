"""Field-work notifications. Email failures must never break the field action."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify_plot_ready(unit) -> None:
    """Ping the enumerators assigned to a plot that its farmer anchor is captured
    and the plot is ready to register. No-op when nobody is assigned yet."""
    from apps.fieldwork.models import UnitAssignment

    emails = {
        a.enumerator.email
        for a in UnitAssignment.objects.filter(unit=unit).select_related("enumerator")
        if a.enumerator and a.enumerator.email
    }
    if not emails:
        return
    uc = unit.use_case
    subject = f"[{uc.code}] Plot {unit.code} is ready to register"
    body = (
        f"The farmer-field anchor for plot {unit.code} ({uc.name}) has been "
        f"captured, so the plot is now ready. You can register the farmer there.\n\n"
        f"Open Fieldbase to see your assigned plots."
    )
    try:
        send_mail(
            subject, body,
            getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@fieldbase.local"),
            sorted(emails), fail_silently=True,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to send plot-ready notification")
