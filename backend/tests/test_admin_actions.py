"""Use-case config actions (export-to-YAML, validate) — now console actions."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.test import RequestFactory

from apps.config_admin.loader import import_config, load_yaml
from apps.console.actions import uc_export, uc_validate
from apps.projects.models import Project

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.PROJECT_CONFIG_DIR) / "sns-rwanda.yaml"


def _request():
    return RequestFactory().post("/manage/projects/")


def test_export_yaml_action_round_trips():
    import_config(load_yaml(SNS_PATH))
    uc = Project.objects.get(code="SNS-RWANDA")
    resp = uc_export(_request(), uc)
    assert resp["Content-Type"] == "application/x-yaml"
    parsed = yaml.safe_load(resp.content)
    assert parsed["project"]["code"] == "SNS-RWANDA"
    assert len(parsed["forms"]) == 3


def test_validate_action_reports_ok():
    import_config(load_yaml(SNS_PATH))
    uc = Project.objects.get(code="SNS-RWANDA")
    assert "OK" in uc_validate(_request(), uc)
