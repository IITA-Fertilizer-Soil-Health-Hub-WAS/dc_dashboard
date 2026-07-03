"""Generic ODK write-back: instance-XML editing + push_edit orchestration.

The XML-editing core is server-agnostic and fully deterministic, so it's tested
directly; the ONA HTTP transport is mocked.
"""
from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from apps.ingestion.backends.base import WriteResult
from apps.ingestion.backends.odk import OdkBackend, build_edited_instance
from apps.projects.models import FieldMapping, FormDefinition, Project

pytestmark = pytest.mark.django_db

INSTANCE_XML = (
    '<data id="myform">'
    "<intro><enumerator_id>EN1</enumerator_id><event>Event1</event></intro>"
    "<crop>maize</crop>"
    "<meta><instanceID>uuid:OLD-123</instanceID></meta>"
    "</data>"
)


def test_build_edited_instance_changes_value_and_deprecates():
    xml, old_iid = build_edited_instance(
        INSTANCE_XML, {"intro/enumerator_id": "EN1-FIXED"}, new_instance_id="uuid:NEW-999"
    )
    root = ET.fromstring(xml)
    assert old_iid == "uuid:OLD-123"
    # edited value applied
    assert root.find("intro/enumerator_id").text == "EN1-FIXED"
    # untouched value preserved
    assert root.find("crop").text == "maize"
    # new instanceID set, old one deprecated (ODK edit semantics)
    assert root.find("meta/instanceID").text == "uuid:NEW-999"
    assert root.find("meta/deprecatedID").text == "uuid:OLD-123"


def test_build_edited_instance_ignores_unknown_path():
    xml, _ = build_edited_instance(INSTANCE_XML, {"does/not/exist": "x"}, new_instance_id="uuid:N")
    assert ET.fromstring(xml).find("intro/enumerator_id").text == "EN1"  # unchanged


class FakeOdk(OdkBackend):
    """Concrete ODK backend with mocked transport, to test orchestration."""

    supports_writeback = True

    def __init__(self):
        super().__init__()
        self.submitted_xml = None

    def _fetch_instance_xml(self, form_id, data_id):
        return INSTANCE_XML

    def _submit_edited_xml(self, form_id, xml):
        self.submitted_xml = xml
        return "remote-1"


def _submission_with_mapping():
    uc = Project.objects.create(code="UC", name="UC")
    form = FormDefinition.objects.create(project=uc, ona_form_id=10,
                                         role=FormDefinition.Role.VALIDATION)
    FieldMapping.objects.create(form=form, target_field="ENID",
                                source_paths=["intro/enumerator_id"])
    from apps.submissions.models import Submission
    return Submission.objects.create(project=uc, form=form, ona_uuid="u1",
                                     content_hash="h", ona_submission_id=555)


def test_push_edit_translates_and_submits():
    sub = _submission_with_mapping()
    backend = FakeOdk()
    result = backend.push_edit(sub, {"ENID": "EN1-FIXED"})
    assert isinstance(result, WriteResult) and result.ok
    # canonical ENID was translated to its source path and written into the XML
    root = ET.fromstring(backend.submitted_xml)
    assert root.find("intro/enumerator_id").text == "EN1-FIXED"
    assert root.find("meta/deprecatedID").text == "uuid:OLD-123"


def test_push_edit_no_source_id():
    sub = _submission_with_mapping()
    sub.ona_submission_id = None
    result = OdkBackendNoop().push_edit(sub, {"ENID": "X"})
    assert not result.ok and "id" in result.message.lower()


def test_push_edit_unmapped_field_is_skipped():
    sub = _submission_with_mapping()
    # 'NOTES' isn't mapped to any source path -> nothing to write
    result = FakeOdk().push_edit(sub, {"NOTES": "hello"})
    assert not result.ok and "mapped" in result.message.lower()


class OdkBackendNoop(OdkBackend):
    supports_writeback = True
