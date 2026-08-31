"""The printable enumerator guide carries the Regional Hub letterhead."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_enumerator_guide_has_hub_letterhead(client, django_user_model):
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    client.force_login(admin)
    body = client.get(reverse("console:enumerator_guide")).content.decode()
    assert "Enumerator quick guide" in body                       # the guide renders
    assert "img/regional-hub-logo" in body                        # Hub emblem present
    assert "Fertilizer and Soil Health Hub for West Africa" in body  # emblem alt
    assert "West Africa &amp; the Sahel" in body                  # letterhead caption
