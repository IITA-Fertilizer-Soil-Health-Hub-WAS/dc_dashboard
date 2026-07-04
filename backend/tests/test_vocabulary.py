"""Terminag vocabulary import + the missing-terms report.

Uses a tiny in-repo fixture (not the network) so it's deterministic offline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.vocabulary.importer import import_from_dir, match_terms
from apps.vocabulary.models import VocabularyValue, VocabularyVariable

pytestmark = pytest.mark.django_db

VARIABLES_CSV = (
    "name,type,unit,required,vocabulary,multiple_allowed,valid_min,valid_max,NAok,description,notes,obo\n"
    "depth,numeric,cm,no,,no,0,300,yes,soil sample depth,,\n"
    "soil_ph,numeric,,no,,no,2,11,yes,soil pH,,OBO_1\n"
    "crop,character,,yes,crop,no,,,no,the crop grown,,\n"
    'planting_date,date,,no,,no,,,yes,"date planted",,\n'
)
VALUES_CROP_CSV = (
    "name,sciname,altname,is_preferred,group\n"
    "maize,Zea mays,corn,yes,cereals\n"
    "potato,Solanum tuberosum,,yes,roots\n"
)


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "variables").mkdir()
    (tmp_path / "values").mkdir()
    (tmp_path / "variables" / "variables_soil.csv").write_text(VARIABLES_CSV, encoding="utf-8")
    (tmp_path / "values" / "values_crop.csv").write_text(VALUES_CROP_CSV, encoding="utf-8")
    return tmp_path


def test_import_parses_variables_and_values(tmp_path):
    report = import_from_dir(_fixture(tmp_path))
    assert report.variables == 4 and report.values == 2

    depth = VocabularyVariable.objects.get(name="depth")
    assert depth.data_type == "numeric" and depth.unit == "cm"
    assert depth.valid_min == 0.0 and depth.valid_max == 300.0
    assert depth.category == "soil"

    crop_var = VocabularyVariable.objects.get(name="crop")
    assert crop_var.required is True and crop_var.value_list == "crop"

    maize = VocabularyValue.objects.get(list_name="crop", name="maize")
    assert maize.extra.get("sciname") == "Zea mays"  # unmodelled columns kept


def test_import_is_idempotent(tmp_path):
    _fixture(tmp_path)
    import_from_dir(tmp_path)
    import_from_dir(tmp_path)  # re-run
    assert VocabularyVariable.objects.count() == 4
    assert VocabularyValue.objects.filter(list_name="crop").count() == 2


def test_match_terms_reports_missing(tmp_path):
    import_from_dir(_fixture(tmp_path))
    # normalisation: "Soil pH" -> soil_ph (match), "depth (cm)" -> depth (match).
    res = match_terms(["depth (cm)", "Soil pH", "planting date", "rainfall", "widget"])
    assert set(res.matched) == {"depth (cm)", "Soil pH", "planting date"}
    assert res.missing == ["rainfall", "widget"]
    assert 0.5 < res.coverage < 0.7


def test_match_terms_empty():
    res = match_terms([])
    assert res.matched == {} and res.missing == [] and res.coverage == 0.0


def test_daily_sync_task_imports(monkeypatch, tmp_path, settings):
    """The Celery task clones + imports; here we stub the clone to a local dir."""
    from apps.vocabulary import importer, tasks
    from apps.vocabulary.models import VocabularyVariable

    _fixture(tmp_path)
    monkeypatch.setattr(importer, "sync_from_repo",
                        lambda url: importer.import_from_dir(tmp_path))
    settings.TERMINAG_REPO_URL = "https://example/terminag.git"
    result = tasks.sync_terminag_task()
    assert result["ok"] and result["variables"] == 4
    assert VocabularyVariable.objects.filter(name="depth").exists()


def test_daily_sync_task_is_fail_soft(monkeypatch, settings):
    from apps.vocabulary import importer, tasks

    def boom(url):
        raise importer.VocabularySyncError("clone failed: network down")
    monkeypatch.setattr(importer, "sync_from_repo", boom)
    result = tasks.sync_terminag_task()
    assert result["ok"] is False and "network down" in result["error"]


def test_vocabulary_browse(client, django_user_model):
    from django.urls import reverse

    VocabularyVariable.objects.create(name="soil_ph", category="soil", data_type="numeric")
    VocabularyVariable.objects.create(name="rainfall", category="weather", data_type="numeric")
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    client.force_login(admin)
    # Full list, then a filtered search.
    assert b"soil_ph" in client.get(reverse("console:vocabulary")).content
    filtered = client.get(reverse("console:vocabulary"), {"q": "rain"}).content
    assert b"rainfall" in filtered and b"soil_ph" not in filtered


def test_vocabulary_browse_blocked_for_member(client, django_user_model):
    from django.urls import reverse

    u = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    client.force_login(u)
    assert client.get(reverse("console:vocabulary")).status_code == 403
