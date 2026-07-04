"""Auto-provisioning: mirror platform accounts onto the collection server.

Covers the backend `provision_account` contract (unsupported default + the three
real backends' happy paths against mocked HTTP), the fail-soft service that
records a CollectorAccount, and the gated signals firing on user creation and a
project grant.
"""
from __future__ import annotations

import pytest

from apps.ingestion import provisioning
from apps.ingestion.backends.base import CollectionBackend, ProvisionResult
from apps.ingestion.backends.kobo import KoboBackend
from apps.ingestion.backends.odkcentral import OdkCentralBackend
from apps.ingestion.backends.ona import OnaBackend
from apps.projects.models import DataSource, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import CollectorAccount

pytestmark = pytest.mark.django_db


# --- HTTP mock supporting GET + POST with per-call status codes --------------
class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._p = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._p


class _FakeClient:
    """Replays a queue of (method, _Resp) and records the requests it received."""

    def __init__(self, seq, calls):
        self._seq = seq
        self._calls = calls

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _next(self, method, url):
        self._calls.append((method, url))
        return next(self._seq)

    def get(self, url, *a, **k):
        return self._next("GET", url)

    def post(self, url, *a, **k):
        return self._next("POST", url)


def _patch(monkeypatch, module_name, responses):
    calls: list = []
    import apps.ingestion.backends as pkg
    target = getattr(pkg, module_name)
    monkeypatch.setattr(target.httpx, "Client", _FakeClient(iter(responses), calls))
    return calls


# --- backend contract --------------------------------------------------------
def test_base_backend_reports_unsupported():
    r = CollectionBackend().provision_account(username="u")
    assert r.ok is False and "does not support" in r.message


def test_all_three_backends_advertise_provisioning():
    for cls in (OnaBackend, OdkCentralBackend, KoboBackend):
        assert cls.supports_provisioning is True


def test_odk_central_creates_user_and_assigns_role(monkeypatch):
    calls = _patch(monkeypatch, "odkcentral", [
        _Resp(200, {"id": 42}),  # POST /v1/users
        _Resp(200, {}),          # POST assignments/formfill/42
    ])
    b = OdkCentralBackend(base_url="https://c.example", token="t", config={"project_id": "7"})
    r = b.provision_account(username="jo", email="jo@x.org", full_name="Jo Q",
                            remote_project_id="7")
    assert r.ok and r.remote_id == "42" and r.username == "jo@x.org" and r.secret
    assert calls[0][0] == "POST" and calls[0][1].endswith("/v1/users")
    assert "/assignments/formfill/42" in calls[1][1]


def test_odk_central_links_existing_user(monkeypatch):
    calls = _patch(monkeypatch, "odkcentral", [
        _Resp(409, text="email conflict"),               # POST /v1/users -> taken
        _Resp(200, [{"id": 9, "email": "jo@x.org"}]),    # GET /v1/users?q= lookup
        _Resp(200, {}),                                  # role assignment
    ])
    b = OdkCentralBackend(base_url="https://c.example", token="t", config={"project_id": "7"})
    r = b.provision_account(username="jo", email="jo@x.org", remote_project_id="7")
    assert r.ok and r.already_existed and r.remote_id == "9" and r.secret == ""


def test_ona_creates_profile_and_shares(monkeypatch):
    calls = _patch(monkeypatch, "ona", [
        _Resp(201, {"username": "jo"}),  # POST /api/v1/profiles
        _Resp(204, {}),                  # POST /projects/7/share
    ])
    b = OnaBackend(base_url="https://api.ona", token="t")
    r = b.provision_account(username="Jo@x.org", email="jo@x.org", full_name="Jo Q",
                            remote_project_id="7")
    assert r.ok and r.username == "jo" and r.secret
    assert "/profiles" in calls[0][1] and "/projects/7/share" in calls[1][1]


def test_ona_existing_username_is_soft(monkeypatch):
    _patch(monkeypatch, "ona", [
        _Resp(400, text='{"username": ["already exists"]}'),  # taken
        _Resp(204, {}),                                       # share still applied
    ])
    b = OnaBackend(base_url="https://api.ona", token="t")
    r = b.provision_account(username="jo@x.org", email="jo@x.org", remote_project_id="7")
    assert r.ok and r.already_existed and r.secret == ""


def test_kobo_shares_asset(monkeypatch):
    calls = _patch(monkeypatch, "kobo", [
        _Resp(201, {}),  # view_asset
        _Resp(201, {}),  # add_submissions
    ])
    b = KoboBackend(base_url="https://kf.kobo", token="t")
    r = b.provision_account(username="jo@x.org", remote_project_id="aXYZ")
    assert r.ok and r.username == "jo"
    assert all("permission-assignments" in url for _, url in calls)


def test_kobo_no_project_is_selfregister_noop(monkeypatch):
    b = KoboBackend(base_url="https://kf.kobo", token="t")
    r = b.provision_account(username="jo@x.org")
    assert r.ok and r.already_existed and "self-registered" in r.message


# --- service layer -----------------------------------------------------------
class _FakeBackend:
    type = "FAKE"
    label = "Fake"
    supports_provisioning = True

    def __init__(self, result=None, boom=False):
        self._result = result or ProvisionResult(ok=True, remote_id="r1", username="jo")
        self._boom = boom
        self.seen: list = []

    def provision_account(self, **kw):
        self.seen.append(kw)
        if self._boom:
            raise RuntimeError("server down")
        return self._result


@pytest.fixture
def org_project(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    proj = Project.objects.create(code="P1", name="P1", organization=org)
    DataSource.objects.create(project=proj, backend="FAKE", config={"project_id": "77"})
    user = django_user_model.objects.create_user("jo@x.org", "pw", organization=org)
    return {"org": org, "proj": proj, "user": user}


def test_provision_for_project_records_active(monkeypatch, org_project):
    fake = _FakeBackend()
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: fake)
    acct = provisioning.provision_for_project(org_project["user"], org_project["proj"])
    assert acct.status == CollectorAccount.Status.ACTIVE
    assert acct.remote_id == "r1" and acct.provisioned_at is not None
    # The project's remote id flowed through from the DataSource config.
    assert fake.seen[0]["remote_project_id"] == "77"


def test_provision_for_project_is_fail_soft(monkeypatch, org_project):
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: _FakeBackend(boom=True))
    acct = provisioning.provision_for_project(org_project["user"], org_project["proj"])
    assert acct.status == CollectorAccount.Status.FAILED
    assert "server down" in acct.message and acct.provisioned_at is None


def test_unsupported_backend_recorded(monkeypatch, org_project):
    class NoProv:
        type = "NOPE"
        label = "Nope"
        supports_provisioning = False
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: NoProv())
    acct = provisioning.provision_for_project(org_project["user"], org_project["proj"])
    assert acct.status == CollectorAccount.Status.UNSUPPORTED


def test_provision_new_user_one_per_backend(monkeypatch, org_project):
    # Second project in the same org on the SAME backend → still one server-wide row.
    Project.objects.create(code="P2", name="P2", organization=org_project["org"])
    fake = _FakeBackend(ProvisionResult(ok=True, already_existed=True, username="jo"))
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: fake)
    accounts = provisioning.provision_new_user(org_project["user"])
    assert len(accounts) == 1
    assert accounts[0].project_id is None
    assert accounts[0].status == CollectorAccount.Status.LINKED


# --- signals -----------------------------------------------------------------
def test_grant_provisions_when_enabled(monkeypatch, settings, org_project,
                                       django_capture_on_commit_callbacks):
    settings.AUTO_PROVISION_COLLECTORS = True
    fake = _FakeBackend()
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: fake)
    with django_capture_on_commit_callbacks(execute=True):
        Membership.objects.create(user=org_project["user"], project=org_project["proj"],
                                  role=Role.ENUMERATOR)
    acct = CollectorAccount.objects.get(user=org_project["user"], project=org_project["proj"])
    assert acct.status == CollectorAccount.Status.ACTIVE


def test_grant_does_nothing_when_disabled(monkeypatch, settings, org_project,
                                          django_capture_on_commit_callbacks):
    settings.AUTO_PROVISION_COLLECTORS = False
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: _FakeBackend())
    with django_capture_on_commit_callbacks(execute=True):
        Membership.objects.create(user=org_project["user"], project=org_project["proj"],
                                  role=Role.ENUMERATOR)
    assert not CollectorAccount.objects.filter(user=org_project["user"]).exists()


def test_new_user_provisions_when_enabled(monkeypatch, settings, django_user_model,
                                          django_capture_on_commit_callbacks):
    settings.AUTO_PROVISION_COLLECTORS = True
    org = Organization.objects.create(code="o2", name="O2")
    proj = Project.objects.create(code="PX", name="PX", organization=org)
    DataSource.objects.create(project=proj, backend="FAKE", config={})
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: _FakeBackend())
    with django_capture_on_commit_callbacks(execute=True):
        user = django_user_model.objects.create_user("new@x.org", "pw", organization=org)
    assert CollectorAccount.objects.filter(user=user, project__isnull=True).exists()


def test_superuser_is_not_provisioned(monkeypatch, settings, django_user_model,
                                      django_capture_on_commit_callbacks):
    settings.AUTO_PROVISION_COLLECTORS = True
    monkeypatch.setattr(provisioning, "get_backend_for", lambda p: _FakeBackend())
    with django_capture_on_commit_callbacks(execute=True):
        su = django_user_model.objects.create_superuser("root@x.org", "pw")
    assert not CollectorAccount.objects.filter(user=su).exists()
