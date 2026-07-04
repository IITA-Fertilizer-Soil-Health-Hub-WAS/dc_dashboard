"""Model fields with at-rest encryption.

EncryptedCharField transparently encrypts its value in the database with Fernet
(symmetric). App code always sees plaintext; the column holds ciphertext. The key
comes from ``settings.FIELD_ENCRYPTION_KEY`` (a urlsafe base64 32-byte Fernet key,
kept in the environment, never in the DB). With no key set — e.g. local dev — the
value is stored as-is so nothing breaks; production must set a key.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

_PREFIX = "enc::"  # marks an already-encrypted value, so encrypt/decrypt is idempotent


def _fernet():
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


class EncryptedCharField(models.CharField):
    """A CharField whose value is Fernet-encrypted at rest."""

    description = "Fernet-encrypted text"

    def from_db_value(self, value, expression, connection):
        if not value or not value.startswith(_PREFIX):
            return value
        fernet = _fernet()
        if fernet is None:
            return value  # no key to decrypt with — return the raw stored value
        from cryptography.fernet import InvalidToken

        try:
            return fernet.decrypt(value[len(_PREFIX):].encode()).decode()
        except InvalidToken:
            return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value or value.startswith(_PREFIX):
            return value
        fernet = _fernet()
        if fernet is None:
            return value  # dev without a key: store plaintext
        return _PREFIX + fernet.encrypt(value.encode()).decode()
