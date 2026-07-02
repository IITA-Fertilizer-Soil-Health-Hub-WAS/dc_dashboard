"""Export one institution's entire dataset as a loadable fixture.

This is the "promote to its own deployment / database" path (the realistic form
of database-per-tenant given Django's cross-database-FK limits): dump everything
one organization owns, then ``loaddata`` it into a fresh single-tenant instance
backed by that institution's own database. Because all primary keys are UUIDs,
the import never collides.

    python manage.py export_organization shh > shh.json
    # on the new instance:  python manage.py loaddata shh.json

Pass --prune-to-fixture nothing here; this only reads. It does not delete the
source data — decommissioning the source org is a separate, deliberate step.
"""
from __future__ import annotations

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError

from apps.usecases.models import Organization


def _collect(org):
    """Gather every object owned by an organization, parents before children."""
    from apps.accounts.models import User
    from apps.fieldwork.models import CollectionUnit
    from apps.rbac.models import UseCaseMembership
    from apps.review.models import Review, ReviewActionLog
    from apps.submissions.models import Enumerator, Submission, SubmissionValue
    from apps.usecases.models import (
        Country,
        Crop,
        DataSource,
        EventScheduleItem,
        FieldMapping,
        FormDefinition,
        Region,
        Trial,
        UseCase,
    )
    from apps.validation.models import ValidationFlag, ValidationRule

    ucs = UseCase.objects.filter(organization=org)
    forms = FormDefinition.objects.filter(use_case__in=ucs)
    subs = Submission.objects.filter(use_case__in=ucs)

    objs: list = [org]
    objs += list(Region.objects.filter(organization=org))
    objs += list(Country.objects.filter(region__organization=org))
    objs += list(ucs)
    objs += list(DataSource.objects.filter(use_case__in=ucs))
    objs += list(Crop.objects.filter(use_case__in=ucs))
    objs += list(Trial.objects.filter(use_case__in=ucs))
    objs += list(forms)
    objs += list(FieldMapping.objects.filter(form__in=forms))
    objs += list(EventScheduleItem.objects.filter(use_case__in=ucs))
    objs += list(ValidationRule.objects.filter(use_case__in=ucs))
    # Identity + access (only this org's people and the grants over its scopes).
    objs += list(User.objects.filter(organization=org))
    objs += list(
        UseCaseMembership.objects.filter(use_case__in=ucs)
        | UseCaseMembership.objects.filter(country__region__organization=org)
        | UseCaseMembership.objects.filter(region__organization=org)
    )
    # Field data.
    objs += list(Enumerator.objects.filter(use_case__in=ucs))
    objs += list(CollectionUnit.objects.filter(use_case__in=ucs))
    objs += list(subs)
    objs += list(SubmissionValue.objects.filter(submission__in=subs))
    objs += list(Review.objects.filter(submission__in=subs))
    objs += list(ReviewActionLog.objects.filter(submission__in=subs))
    objs += list(ValidationFlag.objects.filter(submission__in=subs))
    return objs


class Command(BaseCommand):
    help = "Export an organization's full dataset as a JSON fixture (for a separate deployment)."

    def add_arguments(self, parser):
        parser.add_argument("code", help="Organization code to export.")
        parser.add_argument("--indent", type=int, default=None, help="Pretty-print indent.")

    def handle(self, *args, **options):
        org = Organization.objects.filter(code=options["code"]).first()
        if org is None:
            raise CommandError(f"Unknown organization code: {options['code']}")
        objs = _collect(org)
        data = serializers.serialize("json", objs, indent=options["indent"])
        self.stdout.write(data)
        self.stderr.write(
            self.style.SUCCESS(f"Exported {len(objs)} objects for '{org.code}'.")
        )
