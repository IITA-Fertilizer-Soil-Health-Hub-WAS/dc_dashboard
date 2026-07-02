"""Auto-dispatch a registration Job when a plot is elected.

Electing a candidate promotes it to the trial's CollectionUnit; this wires that
unit into the project's standing "Plot registration" job so the coordinator has a
single place to assign an enumerator. The enumerator is only pinged once the plot
is field-ready (its farmer anchor is captured — see `notifications.notify_plot_ready`),
which keeps registration behind the containment gate. See project memory:
plot-election governance.
"""
from __future__ import annotations

REGISTRATION_JOB_NAME = "Plot registration"


def _registration_form(use_case):
    """Best form to register a farmer on: household reg, else enumerator reg, else
    validation, else whatever the project has. May be None (job carries no form)."""
    from apps.usecases.models import FormDefinition

    forms = use_case.forms.all()
    for role in (
        FormDefinition.Role.HH_REG,
        FormDefinition.Role.ENUM_REG,
        FormDefinition.Role.VALIDATION,
    ):
        f = forms.filter(role=role).first()
        if f is not None:
            return f
    return forms.first()


def registration_job(use_case):
    """The project's standing auto registration job — created on first election,
    reused thereafter. Backfills the form if it was missing when first created."""
    from apps.fieldwork.models import Job

    job, created = Job.objects.get_or_create(
        use_case=use_case,
        name=REGISTRATION_JOB_NAME,
        defaults={"status": Job.Status.ACTIVE, "form": _registration_form(use_case)},
    )
    if not created and job.form is None:
        form = _registration_form(use_case)
        if form is not None:
            job.form = form
            job.save(update_fields=["form", "updated_at"])
    return job


def dispatch_registration_job(use_case, unit, actor=None):
    """Add `unit` to the project's registration job (idempotent). Returns the job.
    Enumerator is left unset — the coordinator assigns on the job screen, or an
    'assign all' sweep picks it up."""
    from apps.fieldwork.models import UnitAssignment

    job = registration_job(use_case)
    UnitAssignment.objects.get_or_create(job=job, unit=unit)
    return job
