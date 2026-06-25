from __future__ import annotations

from django.apps import AppConfig


class ReviewConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.review"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (connect signal handlers)
