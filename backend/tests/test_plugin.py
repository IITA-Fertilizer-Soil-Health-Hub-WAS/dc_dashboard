"""Plugin hook test: BioSSA explodes a nested-repeat record into multiple rows.

Proves the optional Python escape hatch works end-to-end through the generic
engine — the use case is still defined by config; only `normalize` is custom.
"""
from __future__ import annotations

import pytest

from apps.config_admin.loader import import_config
from apps.ingestion.sync import sync_use_case
from apps.submissions.models import Submission
from tests.test_ingestion import FakeOnaClient

pytestmark = pytest.mark.django_db

BIOSSA_CONFIG = {
    "use_case": {
        "code": "BioSSA",
        "name": "BioSSA",
        "plugin": "plugins.biossa:BioSSAPlugin",
        "enid_patterns": ["^BS"],
        "hhid_patterns": ["^BS"],
        "household_label": "Plot Number",
    },
    "crops": [{"name": "banana"}, {"name": "cassava"}],
    "stages": ["Research"],
    "forms": [
        {
            "ona_form_id": 801786,
            "role": "VALIDATION",
            "mappings": [
                {"target": "ENID", "source": ["intro/enumerator_ID"], "transform": "DIRECT"},
                {"target": "event_key", "source": ["intro/event"], "transform": "DIRECT"},
                {"target": "today", "source": ["today"], "transform": "DATE_PARSE"},
            ],
        }
    ],
    "event_schedule": [{"event_key": "Event1", "sequence": 1, "anchor": "SITE_SELECTION", "offset_days": 14}],
    "validation_rules": [],
}


def test_plugin_explodes_nested_plots():
    uc = import_config(BIOSSA_CONFIG)
    assert uc.plugin_path == "plugins.biossa:BioSSAPlugin"

    record = {
        "_uuid": "biossa-rec-1",
        "_id": 1,
        "intro/enumerator_ID": "BSEN001",
        "intro/event": "Event1",
        "today": "2026-02-01",
        "group/plots": [
            {"plot/HHID": "BSPLOT-A", "plot/crop": "banana", "plot/event": "Event1", "plot/date": "2026-02-01"},
            {"plot/HHID": "BSPLOT-B", "plot/crop": "cassava", "plot/event": "Event1", "plot/date": "2026-02-02"},
            {"plot/HHID": "BSPLOT-C", "plot/crop": "banana", "plot/event": "Event1", "plot/date": "2026-02-03"},
        ],
    }
    sync_use_case(uc, client=FakeOnaClient({801786: [record]}))

    # One submission per nested plot, each with a distinct uuid.
    subs = Submission.objects.filter(use_case=uc)
    assert subs.count() == 3
    uuids = set(subs.values_list("ona_uuid", flat=True))
    assert uuids == {"biossa-rec-1:BSPLOT-A", "biossa-rec-1:BSPLOT-B", "biossa-rec-1:BSPLOT-C"}


def test_plugin_passthrough_when_no_nested_repeat():
    uc = import_config(BIOSSA_CONFIG)
    flat = {
        "_uuid": "flat-1", "intro/enumerator_ID": "BSEN001",
        "intro/event": "Event1", "today": "2026-02-01",
    }
    sync_use_case(uc, client=FakeOnaClient({801786: [flat]}))
    assert Submission.objects.filter(use_case=uc).count() == 1
