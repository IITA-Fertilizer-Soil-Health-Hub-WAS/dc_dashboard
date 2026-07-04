"""Auto-provision collectors onto the collection server on account/grant events.

Two triggers, both gated by ``AUTO_PROVISION_COLLECTORS`` (OFF by default):

* a new **User** → a server-wide account on each backend their org operates,
* a new project-scoped **Membership** → the per-project account + project share.

Provisioning runs after the DB transaction commits (so the row is durable and a
slow server call doesn't hold the transaction open) and is fail-soft — the
outcome is recorded on a ``CollectorAccount``; an error never breaks the signal.
Superusers (hub operators, not field collectors) are skipped.
"""
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.rbac.models import Membership

from . import provisioning


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="provision_new_user")
def _on_user_created(sender, instance, created, **kwargs):
    if not (created and provisioning.is_enabled()):
        return
    if instance.is_superuser:
        return
    user = instance
    transaction.on_commit(lambda: provisioning.provision_new_user(user))


@receiver(post_save, sender=Membership, dispatch_uid="provision_on_grant")
def _on_membership_granted(sender, instance, created, **kwargs):
    if not (created and provisioning.is_enabled()):
        return
    membership = instance

    def run():
        for project in _projects_for(membership):
            provisioning.provision_for_project(membership.user, project)

    transaction.on_commit(run)


def _projects_for(membership: Membership):
    """The projects a membership grants access to on the server: the project
    itself, or every active project cascaded from a country/region grant."""
    from apps.projects.models import Project

    if membership.project_id:
        return [membership.project]
    if membership.country_id:
        return list(Project.objects.filter(country_id=membership.country_id, is_active=True))
    if membership.region_id:
        return list(Project.objects.filter(country__region_id=membership.region_id, is_active=True))
    return []
