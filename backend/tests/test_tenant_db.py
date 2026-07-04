"""At-rest encryption of secret columns + the opt-in per-tenant DB router."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from django.db import connection, connections
from django.test import override_settings

from apps.common.fields import EncryptedCharField
from apps.projects.db_routing import TenantRouter, ensure_tenant_connection, set_active_tenant
from apps.projects.models import Organization

pytestmark = pytest.mark.django_db

KEY = Fernet.generate_key().decode()


# ---- encryption ----
@override_settings(FIELD_ENCRYPTION_KEY=KEY)
def test_encrypted_field_round_trips():
    f = EncryptedCharField()
    stored = f.get_prep_value("postgres://u:p@h/db")
    assert stored.startswith("enc::") and "postgres" not in stored     # ciphertext
    assert f.from_db_value(stored, None, None) == "postgres://u:p@h/db"  # decrypts


def test_encrypted_field_passthrough_without_key():
    with override_settings(FIELD_ENCRYPTION_KEY=""):
        f = EncryptedCharField()
        assert f.get_prep_value("plain") == "plain"                     # dev: stored as-is


@override_settings(FIELD_ENCRYPTION_KEY=KEY)
def test_database_url_is_encrypted_at_rest():
    org = Organization.objects.create(
        code="acme", name="Acme", database_url="postgres://u:secret@h:5432/db"
    )
    org.refresh_from_db()
    assert org.database_url == "postgres://u:secret@h:5432/db"          # plaintext to app code
    with connection.cursor() as cur:                                    # ciphertext in the column
        cur.execute("SELECT database_url FROM projects_organization WHERE code = %s", ["acme"])
        raw = cur.fetchone()[0]
    assert raw.startswith("enc::") and "secret" not in raw


# ---- router ----
def test_router_is_noop_when_disabled():
    from apps.submissions.models import Submission

    r = TenantRouter()
    assert r.db_for_read(Submission) is None
    assert r.db_for_write(Submission) is None


@override_settings(TENANT_DB_ROUTING=True)
def test_router_routes_tenant_apps_only():
    from apps.accounts.models import User
    from apps.submissions.models import Submission

    r = TenantRouter()
    set_active_tenant("tenant_x")
    try:
        assert r.db_for_read(Submission) == "tenant_x"     # tenant app → tenant DB
        assert r.db_for_read(User) is None                 # shared app → default
        assert r.allow_migrate("tenant_x", "submissions") is True
        assert r.allow_migrate("tenant_x", "accounts") is False
        assert r.allow_migrate("default", "submissions") is None
    finally:
        set_active_tenant(None)


def test_ensure_tenant_connection():
    assert ensure_tenant_connection(Organization(code="a", database_alias="default")) is None
    org = Organization(code="b", database_url="sqlite:////tmp/tenant_b.sqlite3")
    try:
        alias = ensure_tenant_connection(org)
        assert alias == "tenant_b"
        assert "tenant_b" in connections.databases
        assert connections.databases["tenant_b"]["ATOMIC_REQUESTS"] is False  # defaults filled
    finally:
        connections.databases.pop("tenant_b", None)  # don't leak to other tests
