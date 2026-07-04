from __future__ import annotations

from django.apps import AppConfig


class IngestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ingestion"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (connect auto-provisioning handlers)
