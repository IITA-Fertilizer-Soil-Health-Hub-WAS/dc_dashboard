"""Config engine tests: YAML imports faithfully and round-trips DB <-> YAML."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.conf import settings

from apps.config_admin.loader import (
    ConfigError,
    dump_yaml,
    export_config,
    import_config,
    load_yaml,
)
from apps.projects.models import EventScheduleItem, FieldMapping, Project
from apps.validation.models import ValidationRule

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.PROJECT_CONFIG_DIR) / "sns-rwanda.yaml"


def test_import_sns_rwanda_from_file():
    uc = import_config(load_yaml(SNS_PATH))
    assert uc.code == "SNS-RWANDA"
    assert uc.enid_patterns == ["^RSENRW"]
    assert uc.forms.count() == 3
    assert uc.schedule.count() == 7
    assert uc.crops.count() == 3
    assert uc.rules.count() == 4

    # Event offsets ported exactly from support_fun.R.
    e1 = uc.schedule.get(event_key="Event1")
    assert e1.anchor == EventScheduleItem.Anchor.SITE_SELECTION
    assert e1.offset_days == 14
    e4 = uc.schedule.get(event_key="Event4")
    assert e4.offset_days == 64
    assert e4.crop_overrides == {"potato": 57}
    assert e4.target_offset_for_crop("potato") == 57
    assert e4.target_offset_for_crop("rice") == 64

    # Validation rules including ID patterns.
    assert uc.rules.filter(rule_type=ValidationRule.RuleType.REGEX_ID).count() == 2
    coalesce = FieldMapping.objects.filter(
        form__project=uc, transform=FieldMapping.Transform.COALESCE
    )
    assert coalesce.exists()


def test_import_is_idempotent_and_bumps_version():
    data = load_yaml(SNS_PATH)
    uc1 = import_config(data)
    v1 = uc1.config_version
    uc2 = import_config(data)
    # Same single use case, no duplicate children, version incremented.
    assert Project.objects.filter(code="SNS-RWANDA").count() == 1
    assert uc2.config_version == v1 + 1
    assert uc2.forms.count() == 3
    assert uc2.schedule.count() == 7


def test_round_trip_db_to_yaml_to_db():
    original = load_yaml(SNS_PATH)
    uc = import_config(original)

    exported = export_config(uc)
    # Re-import the exported config and confirm structural equality.
    reimported = import_config(exported)
    assert export_config(reimported)["forms"] == exported["forms"]
    assert export_config(reimported)["event_schedule"] == exported["event_schedule"]
    assert export_config(reimported)["validation_rules"] == exported["validation_rules"]

    # dump_yaml produces parseable YAML that imports to the same shape.
    text = dump_yaml(uc)
    assert yaml.safe_load(text)["project"]["code"] == "SNS-RWANDA"


def test_missing_code_raises():
    with pytest.raises(ConfigError):
        import_config({"project": {"name": "no code"}})
