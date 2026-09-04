"""Make the Auth0 / OIDC discovery fetch resilient.

allauth fetches the provider's ``.well-known/openid-configuration`` **live on every
login** (per adapter instance, no caching) and calls ``raise_for_status()``, so a
transient network blip — e.g. when a freshly-deployed cold container handles its
first login — turns into a 500 on the callback. We saw exactly that after a deploy.

This patches ``OpenIDConnectOAuth2Adapter.openid_config`` to:
  * cache the document per worker (so it isn't re-fetched on every request),
  * fetch with a timeout and a couple of retries (rides out a brief blip), and
  * fall back to the last good copy if a later fetch fails, instead of erroring
    the user out.

The patch is applied from ``AccountsConfig.ready()``; a failure to apply is logged
but never blocks startup.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_TTL = 3600          # re-fetch the discovery doc at most hourly
_RETRIES = 3         # attempts per fetch before giving up
_BACKOFF = 0.5       # seconds, linear backoff between attempts
_TIMEOUT = 8         # seconds per HTTP request (allauth set none)

# {provider_id: (config_dict, monotonic_fetched_at)} — shared across threads in a
# worker; last good copy is kept even past the TTL for the failure fallback.
_cache: dict = {}


def _resilient_openid_config(self):
    from allauth.socialaccount.adapter import get_adapter

    pid = self.provider_id
    now = time.monotonic()
    cached = _cache.get(pid)
    if cached and (now - cached[1]) < _TTL:
        return cached[0]

    server_url = self.get_provider().server_url
    last_exc = None
    for attempt in range(_RETRIES):
        try:
            with get_adapter().get_requests_session() as sess:
                resp = sess.get(server_url, timeout=_TIMEOUT)
                resp.raise_for_status()
                cfg = resp.json()
            _cache[pid] = (cfg, now)
            return cfg
        except Exception as exc:  # noqa: BLE001 — any transport/HTTP error is retryable
            last_exc = exc
            if attempt < _RETRIES - 1:
                time.sleep(_BACKOFF * (attempt + 1))

    # Every attempt failed. Serve the last good copy (even if stale) rather than
    # 500 the login; only raise if we've never fetched it successfully.
    if cached:
        logger.warning("OIDC discovery fetch failed for %s; serving cached copy: %s",
                       pid, last_exc)
        return cached[0]
    raise last_exc


def apply() -> None:
    from allauth.socialaccount.providers.openid_connect.views import (
        OpenIDConnectOAuth2Adapter,
    )

    OpenIDConnectOAuth2Adapter.openid_config = property(_resilient_openid_config)
