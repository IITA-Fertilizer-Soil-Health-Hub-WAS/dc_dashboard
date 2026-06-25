"""Abstract base models shared across the project.

Every concrete model uses a UUID primary key (stable, non-guessable, safe to
expose in URLs/APIs) and timestamp tracking.
"""
from __future__ import annotations

import uuid

from django.db import models


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    """Standard base: UUID pk + created/updated timestamps."""

    class Meta:
        abstract = True
