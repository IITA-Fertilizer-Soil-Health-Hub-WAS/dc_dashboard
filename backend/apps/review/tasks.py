"""Celery tasks for the review workflow."""
from __future__ import annotations

from celery import shared_task


@shared_task(name="review.send_review_digests")
def send_review_digests_task() -> int:
    from .digests import send_review_digests

    return send_review_digests()
