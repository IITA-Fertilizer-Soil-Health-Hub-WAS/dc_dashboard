from __future__ import annotations

from django.apps import AppConfig


class ConfigAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.config_admin"
