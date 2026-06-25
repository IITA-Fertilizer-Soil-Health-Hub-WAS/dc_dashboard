"""Create a Review row for every new submission so it enters the workflow."""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.submissions.models import Submission

from .models import Review


@receiver(post_save, sender=Submission, dispatch_uid="create_review_for_submission")
def create_review(sender, instance: Submission, created: bool, **kwargs) -> None:
    if created:
        Review.objects.get_or_create(submission=instance)
