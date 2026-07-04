"""Custom console forms — where the generic ModelForm needs a smarter widget."""
from __future__ import annotations

from django import forms

from apps.accounts.models import User
from apps.projects.models import Project


class OwnerSelect(forms.Select):
    """A <select> whose options each carry the candidate's institution, so the
    picker can be filtered live to the project's institution (data-depends) and
    made searchable (data-searchable) — see the combobox JS in base.html."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        inst = getattr(value, "instance", None)  # the User, on real choices
        if inst is not None and getattr(inst, "organization_id", None):
            option["attrs"]["data-org"] = str(inst.organization_id)
        return option


class ProjectAdminForm(forms.ModelForm):
    """Project create/edit. The owner is a specific existing user, chosen from a
    searchable picker scoped to the project's institution."""

    class Meta:
        model = Project
        fields = [
            "code", "name", "description", "organization", "owner", "country",
            "unit_type", "is_active", "allow_access_requests", "countries",
            "enid_patterns", "hhid_patterns", "plugin_path", "timezone",
            "household_label",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        owner = self.fields["owner"]
        # Only real people who belong to an institution are eligible.
        owner.queryset = User.objects.filter(
            organization__isnull=False
        ).order_by("full_name", "email")
        # Every project must be owned by a specific user — required at creation and
        # enforced on edit, so any legacy owner-less project gets one when touched.
        owner.required = True
        # Show a human name (searchable), not just the email.
        owner.label_from_instance = lambda u: (
            f"{u.full_name} · {u.email}" if u.full_name else u.email
        )
        owner.widget = OwnerSelect(attrs={
            "data-searchable": "1",
            "data-depends": "organization",   # narrows to the chosen institution
            "data-placeholder": "Search a user by name or email…",
        })
        owner.widget.choices = owner.choices  # rebind after swapping the widget

    def clean(self):
        cleaned = super().clean()
        owner, org = cleaned.get("owner"), cleaned.get("organization")
        if owner and org and owner.organization_id and owner.organization_id != org.id:
            self.add_error("owner", "The owner must belong to the project's institution.")
        return cleaned
