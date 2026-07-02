"""Reused-photo curbstoning check (+ the media hashing that feeds it) and the
enumerator self-service scorecard."""
from __future__ import annotations

import hashlib

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.media_hash import hash_submission_media
from apps.submissions.models import Enumerator, Household, Submission
from apps.usecases.models import FormDefinition, Organization, UseCase
from apps.validation.engine import run_for_use_case
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    return {"uc": uc, "form": form, "org": org}


def _sub(world, uuid, **kw):
    return Submission.objects.create(
        use_case=world["uc"], form=world["form"], ona_uuid=uuid, content_hash=uuid, **kw)


# --- PHOTO_REUSE rule --------------------------------------------------------

def test_photo_reuse_flags_shared_image_across_households(world):
    uc = world["uc"]
    h1 = Household.objects.create(use_case=uc, hhid="H1")
    h2 = Household.objects.create(use_case=uc, hhid="H2")
    h3 = Household.objects.create(use_case=uc, hhid="H3")
    _sub(world, "a", household=h1, media_hashes=["deadbeef"])
    _sub(world, "b", household=h2, media_hashes=["deadbeef"])   # same photo, other farmer
    _sub(world, "c", household=h3, media_hashes=["c0ffee"])     # unique

    ValidationRule.objects.create(
        use_case=uc, code="photo", rule_type=ValidationRule.RuleType.PHOTO_REUSE)
    run_for_use_case(uc)

    flagged = set(ValidationFlag.objects.filter(status="OPEN").values_list("submission__ona_uuid", flat=True))
    assert flagged == {"a", "b"}


def test_photo_reuse_ignores_same_household(world):
    uc = world["uc"]
    h1 = Household.objects.create(use_case=uc, hhid="H1")
    _sub(world, "e1", household=h1, media_hashes=["shared"])
    _sub(world, "e2", household=h1, media_hashes=["shared"])  # same HH across events
    ValidationRule.objects.create(
        use_case=uc, code="photo", rule_type=ValidationRule.RuleType.PHOTO_REUSE)
    run_for_use_case(uc)
    assert ValidationFlag.objects.filter(status="OPEN").count() == 0


# --- media hashing -----------------------------------------------------------

class _FakeBackend:
    """Stand-in collection backend that serves two attachments for any submission."""
    def list_attachments(self, submission):
        return [
            {"name": "photo.jpg", "is_image": True},
            {"name": "notes.txt", "is_image": False},   # skipped (not an image)
        ]

    def fetch_attachment(self, att):
        return b"the-photo-bytes", "image/jpeg"


def test_hash_submission_media_stores_image_sha256_only(world):
    sub = _sub(world, "m1")
    hashes = hash_submission_media(sub, backend=_FakeBackend())
    expected = hashlib.sha256(b"the-photo-bytes").hexdigest()
    assert hashes == [expected]        # only the image, not the .txt
    sub.refresh_from_db()
    assert sub.media_hashes == [expected]
    assert sub.media_hashed_at is not None   # marked processed


def test_hash_use_case_media_only_new_skips_processed(world, monkeypatch):
    """The recurring task must not re-fetch already-processed submissions — even
    media-less ones (marked via media_hashed_at, not by having hashes)."""
    from apps.ingestion import media_hash as mh

    calls = {"n": 0}

    def fake_hash(submission, backend=None):
        calls["n"] += 1
        submission.media_hashed_at = timezone.now()
        submission.save(update_fields=["media_hashed_at"])
        return []

    monkeypatch.setattr(mh, "hash_submission_media", fake_hash)
    _sub(world, "s1")
    _sub(world, "s2")
    first = mh.hash_use_case_media(world["uc"], only_new=True)
    assert first.processed == 2 and calls["n"] == 2
    second = mh.hash_use_case_media(world["uc"], only_new=True)  # nothing new
    assert second.processed == 0 and calls["n"] == 2


# --- enumerator self-service scorecard ---------------------------------------

def test_my_performance_shows_own_score_and_rank(client, world, django_user_model):
    uc = world["uc"]
    user = django_user_model.objects.create_user(
        "e@x.org", "pw", is_active=True, organization=world["org"])
    me = Enumerator.objects.create(use_case=uc, enid="E-ME", user=user)
    other = Enumerator.objects.create(use_case=uc, enid="E-OTHER")
    today = timezone.localdate()
    _sub(world, "mine1", enumerator=me, event_date=today)
    _sub(world, "mine2", enumerator=me, event_date=today)
    _sub(world, "theirs", enumerator=other, event_date=today)

    client.force_login(user)
    resp = client.get(reverse("dashboards:my_performance"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "PROJ-A" in body
    assert "of 2" in body           # ranked among the 2 enumerators on the project


def test_my_performance_empty_without_identity(client, world, django_user_model):
    user = django_user_model.objects.create_user(
        "n@x.org", "pw", is_active=True, organization=world["org"])
    client.force_login(user)
    resp = client.get(reverse("dashboards:my_performance"))
    assert resp.status_code == 200
    assert "no enumerator identity" in resp.content.decode().lower()
