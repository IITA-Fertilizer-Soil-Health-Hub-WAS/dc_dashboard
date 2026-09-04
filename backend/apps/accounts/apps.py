from __future__ import annotations

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        # Make the Auth0/OIDC discovery fetch resilient (cache + retry + fallback)
        # so a transient blip on a cold container's first login can't 500 it.
        try:
            from .oidc_hardening import apply

            apply()
        except Exception:  # noqa: BLE001 — never block startup on the hardening patch
            import logging

            logging.getLogger(__name__).warning(
                "OIDC discovery hardening not applied", exc_info=True
            )
