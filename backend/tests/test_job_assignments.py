"""Feature B, Stage B3: assign enumerators to job units + 'My assignments'."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.fieldwork.models import CollectionUnit, Job, UnitAssignment
from apps.fieldwork.services import project_enumerators
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="UC", name="UC", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    job = Job.objects.create(project=uc, name="Round 1", form=form, target_count=3)
    units = [CollectionUnit.objects.create(project=uc, code=f"HH{i}") for i in range(3)]
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    en = django_user_model.objects.create_user("en@x.org", "pw", full_name="Enid",
                                               is_active=True, organization=org)
    Membership.objects.create(user=en, project=uc, role=Role.ENUMERATOR)
    return {"uc": uc, "job": job, "units": units, "coord": coord, "en": en, "org": org}


def test_project_enumerators_lists_enumerator_role(world):
    pool = list(project_enumerators(world["uc"]))
    assert world["en"] in pool
    assert world["coord"] not in pool  # coordinator is not an enumerator


def test_assign_unit_to_enumerator(client, world):
    client.force_login(world["coord"])
    resp = client.post(reverse("console:job_assignments", args=[world["job"].pk]),
                       {"unit": str(world["units"][0].pk), "enumerator": str(world["en"].pk)})
    assert resp.status_code == 302
    a = UnitAssignment.objects.get(job=world["job"], unit=world["units"][0])
    assert a.enumerator == world["en"]
    assert world["en"] in world["job"].assignees  # derived from the assignment


def test_assign_all_remaining(client, world):
    client.force_login(world["coord"])
    client.post(reverse("console:job_assignments", args=[world["job"].pk]),
                {"action": "assign_all", "enumerator": str(world["en"].pk)})
    assert UnitAssignment.objects.filter(job=world["job"]).count() == 3


def test_remove_assignment(client, world):
    a = UnitAssignment.objects.create(job=world["job"], unit=world["units"][0],
                                      enumerator=world["en"])
    client.force_login(world["coord"])
    client.post(reverse("console:job_assignments", args=[world["job"].pk]),
                {"action": "remove", "assignment": str(a.pk)})
    assert not UnitAssignment.objects.filter(pk=a.pk).exists()


def test_assignments_scoped_to_own_project(client, django_user_model, world):
    """A coordinator can't open a job in a project they don't coordinate."""
    other_uc = Project.objects.create(code="OTHER", name="Other", organization=world["org"])
    other_job = Job.objects.create(project=other_uc, name="Other Job")
    client.force_login(world["coord"])
    assert client.get(reverse("console:job_assignments",
                              args=[other_job.pk])).status_code == 404


def test_my_assignments_lists_for_enumerator(client, world):
    UnitAssignment.objects.create(job=world["job"], unit=world["units"][0],
                                  enumerator=world["en"])
    client.force_login(world["en"])
    resp = client.get(reverse("dashboards:my_assignments"))
    assert resp.status_code == 200
    assert b"Round 1" in resp.content
    assert b"HH0" in resp.content


def test_assign_selected_bulk(client, world):
    """The assignment screen bulk-assigns exactly the ticked plots to the chosen
    enumerator; unticked plots stay out."""
    client.force_login(world["coord"])
    client.post(reverse("console:job_assignments", args=[world["job"].pk]),
                {"action": "assign_selected", "enumerator": str(world["en"].pk),
                 "units": [str(world["units"][0].pk), str(world["units"][1].pk)]})
    assigned = UnitAssignment.objects.filter(job=world["job"])
    assert assigned.count() == 2
    assert not assigned.filter(unit=world["units"][2]).exists()
    assert set(assigned.values_list("enumerator_id", flat=True)) == {world["en"].pk}


def test_assignment_editor_lists_plots(client, world):
    """The one-screen editor offers the project's plots as a multi-select."""
    client.force_login(world["coord"])
    resp = client.get(reverse("console:job_new") + f"?project={world['uc'].code}")
    assert resp.status_code == 200
    assert b'name="units" multiple' in resp.content
    assert b"HH0" in resp.content and b"HH2" in resp.content


def test_create_assignment_with_multiple_plots(client, world):
    """Creating one assignment over several selected plots makes a Job with a
    UnitAssignment per plot, all linked to the chosen enumerator."""
    client.force_login(world["coord"])
    resp = client.post(
        reverse("console:job_new") + f"?project={world['uc'].code}",
        {"project": world["uc"].code, "name": "Round 2", "form": str(world["job"].form_id or ""),
         "enumerator": str(world["en"].pk),
         "units": [str(world["units"][0].pk), str(world["units"][1].pk)]},
    )
    assert resp.status_code == 302
    job = Job.objects.get(project=world["uc"], name="Round 2")
    assert job.assignments.count() == 2                       # one per selected plot
    assert set(job.assignments.values_list("enumerator_id", flat=True)) == {world["en"].pk}
    assert world["en"] in job.assignees
    assert job.target_count == 2                              # auto = plots selected
    # The third plot was not selected, so it stays out of the job.
    assert not UnitAssignment.objects.filter(job=job, unit=world["units"][2]).exists()


def test_edit_assignment_syncs_plot_set(client, world):
    """Editing an assignment adds newly-ticked plots and drops unticked ones."""
    from apps.fieldwork.models import Job as _Job
    job = _Job.objects.create(project=world["uc"], name="Round 3")
    UnitAssignment.objects.create(job=job, unit=world["units"][0], enumerator=world["en"])
    client.force_login(world["coord"])
    # Re-submit with a different plot selected (drop unit0, add unit2).
    client.post(reverse("console:job_edit", args=[job.pk]),
                {"project": world["uc"].code, "name": "Round 3",
                 "units": [str(world["units"][2].pk)]})
    codes = set(job.assignments.values_list("unit__code", flat=True))
    assert codes == {"HH2"}


def test_my_assignments_header_uses_project_unit_noun(client, world):
    """Bold naming reaches the enumerator's own pages: the assignments table
    heads the unit column with the project's own noun, not a generic 'Unit'."""
    world["uc"].unit_label = "Plot"
    world["uc"].save()
    UnitAssignment.objects.create(job=world["job"], unit=world["units"][0],
                                  enumerator=world["en"])
    client.force_login(world["en"])
    body = client.get(reverse("dashboards:my_assignments")).content.decode()
    assert '<th scope="col">Plot</th>' in body


def test_my_assignments_only_mine(client, django_user_model, world):
    other = django_user_model.objects.create_user("o2@x.org", "pw", is_active=True)
    UnitAssignment.objects.create(job=world["job"], unit=world["units"][0], enumerator=other)
    client.force_login(world["en"])  # has no assignments
    resp = client.get(reverse("dashboards:my_assignments"))
    assert b"HH0" not in resp.content  # not assigned to me


def test_job_editor_rejects_malformed_date(client, world):
    """A hand-crafted POST with a bad date re-renders the form with an error
    instead of 500-ing on save() — and creates no Job."""
    client.force_login(world["coord"])
    before = Job.objects.count()
    resp = client.post(
        reverse("console:job_new") + f"?project={world['uc'].code}",
        {"project": world["uc"].code, "name": "Bad dates",
         "start_date": "not-a-date", "units": [str(world["units"][0].pk)]},
    )
    assert resp.status_code == 200          # re-rendered, not a crash
    assert b"YYYY-MM-DD" in resp.content    # the validation message
    assert Job.objects.count() == before    # nothing persisted


def test_job_editor_accepts_valid_date(client, world):
    client.force_login(world["coord"])
    resp = client.post(
        reverse("console:job_new") + f"?project={world['uc'].code}",
        {"project": world["uc"].code, "name": "Good dates",
         "start_date": "2026-03-01", "deadline": "2026-04-01",
         "units": [str(world["units"][0].pk)]},
    )
    assert resp.status_code == 302
    job = Job.objects.get(name="Good dates")
    assert str(job.start_date) == "2026-03-01" and str(job.deadline) == "2026-04-01"
