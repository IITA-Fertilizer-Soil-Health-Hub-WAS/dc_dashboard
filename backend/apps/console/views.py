"""Generic, registry-driven CRUD views rendered inside the app shell."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.forms import modelform_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .registry import REGISTRY, Managed, grouped


class StaffMixin(UserPassesTestMixin):
    """Console is staff-only (Platform Admins). RBAC for project data lives in
    the dashboards; the console manages configuration and access."""

    def test_func(self) -> bool:
        u = self.request.user
        return bool(u.is_authenticated and u.is_active and u.is_staff)


class ManageMixin(UserPassesTestMixin):
    """Staff, or a coordinator who manages at least one project. Views using this
    MUST scope their own querysets to the coordinator's projects when not staff."""

    def test_func(self) -> bool:
        u = self.request.user
        if not (u.is_authenticated and u.is_active):
            return False
        if u.is_staff:
            return True
        from apps.rbac.permissions import can_manage_access

        return can_manage_access(u)


class GeoManagerMixin(UserPassesTestMixin):
    """Platform Admin or a Regional/Country Coordinator — the roles allowed to
    design and publish forms to the collection server. Non-staff users MUST have
    their project choices scoped to what they can see (visible_projects)."""

    def test_func(self) -> bool:
        u = self.request.user
        if not (u.is_authenticated and u.is_active):
            return False
        from .registry import is_geo_manager

        return is_geo_manager(u)


def _managed(key: str) -> Managed:
    m = REGISTRY.get(key)
    if m is None:
        raise Http404(f"Unknown console section: {key}")
    return m


def _column_label(model, fname: str) -> str:
    try:
        return model._meta.get_field(fname).verbose_name.title()
    except (FieldDoesNotExist, AttributeError):
        return fname.replace("_", " ").title()


def _cell(obj, fname: str):
    # Prefer human-readable choice display when available.
    display = getattr(obj, f"get_{fname}_display", None)
    value = display() if callable(display) else getattr(obj, fname, None)
    if isinstance(value, bool):
        return {"kind": "bool", "value": value}
    if value in (None, ""):
        return {"kind": "empty", "value": "—"}
    return {"kind": "text", "value": str(value)}


def _base_ctx(m: Managed) -> dict:
    return {"m": m, "groups": grouped(), "console_key": m.key}


def _console_page_ctx(key: str) -> dict:
    """Shell context for a custom (non-CRUD) console page."""
    return {"groups": grouped(), "console_key": key}


class ConsoleListView(UserPassesTestMixin, View):
    """List view — staff see everything; coordinators see a scoped subset of their
    projects' config & field data; ordinary members see read-only field data."""

    def test_func(self) -> bool:
        from .registry import console_key_allowed

        return console_key_allowed(self.request.user, self.kwargs.get("key"))

    def get(self, request, key):
        from .registry import ORG_FILTER_PATHS, PROJECT_FILTER_PATHS, console_can_edit

        m = _managed(key)
        is_staff = request.user.is_staff
        qs = m.model._default_manager.all()
        if m.ordering:
            qs = qs.order_by(*m.ordering)
        q = (request.GET.get("q") or "").strip()
        if q and m.search_fields:
            cond = Q()
            for f in m.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)

        path = PROJECT_FILTER_PATHS.get(key)
        # Non-staff only ever see rows belonging to their own projects:
        # coordinators to the projects they coordinate, ordinary members to the
        # projects they belong to (read-only field data). Geography/crops sections
        # are scoped to the Regional/Country Coordinator's own institution.
        if not is_staff:
            from apps.rbac.permissions import can_manage_access, visible_projects

            from .registry import GEO_CONSOLE_KEYS, is_geo_manager

            if key in GEO_CONSOLE_KEYS and is_geo_manager(request.user):
                opath = ORG_FILTER_PATHS.get(key)
                org_id = getattr(request.user, "organization_id", None)
                qs = qs.filter(**{opath: org_id}) if (opath and org_id) else qs.none()
            elif can_manage_access(request.user):
                uc_ids = _coordinator_uc_ids(request.user)
                qs = qs.filter(**{f"{path}__in": uc_ids}) if path else qs.none()
            else:
                uc_ids = list(visible_projects(request.user).values_list("id", flat=True))
                qs = qs.filter(**{f"{path}__in": uc_ids}) if path else qs.none()

        # Workspace scope: a ?project=<code> filter (within what's allowed above)
        # narrows the list to one project — used by the project-workspace sidebar.
        ws_code = (request.GET.get("project") or "").strip()
        if ws_code and path:
            qs = qs.filter(**{f"{path}__code": ws_code})

        # Hub operator's per-institution filter (staff only).
        from apps.projects.models import Organization

        org_path = ORG_FILTER_PATHS.get(key)
        orgs = list(Organization.objects.all()) if (org_path and is_staff) else []
        org_code = (request.GET.get("org") or "").strip()
        if org_path and org_code and is_staff:
            qs = qs.filter(**{f"{org_path}__code": org_code})

        page = Paginator(qs, 30).get_page(request.GET.get("page"))
        rows = [
            {
                "pk": obj.pk,
                "cells": [_cell(obj, f) for f in m.list_display],
                # Only offer actions that make sense for this row's current
                # state (e.g. no Approve on an already-active user).
                "actions": [
                    a for a in m.actions if a.applies is None or a.applies(obj)
                ],
            }
            for obj in page
        ]
        ctx = _base_ctx(m) | {
            "columns": [_column_label(m.model, f) for f in m.list_display],
            "rows": rows,
            "page": page,
            "q": q,
            "count": qs.count(),
            "org_options": orgs if len(orgs) > 1 else [],
            "org_filter": org_code,
            # Staff and coordinators may mutate (coordinators only their own,
            # scoped projects); read-only sections are never editable.
            "can_edit": console_can_edit(request.user, key),
        }
        return render(request, "console/list.html", ctx)


def _coordinator_uc_ids(user):
    from apps.rbac.permissions import grantable_scopes

    return list(grantable_scopes(user)["projects"].values_list("id", flat=True))


def _editable_projects(user):
    """Projects a user may load data into: all for staff, their own for a coordinator."""
    from apps.projects.models import Project

    if user.is_staff:
        return Project.objects.filter(is_active=True).order_by("code")
    return Project.objects.filter(id__in=_coordinator_uc_ids(user)).order_by("code")


class ImportCollectionUnitsView(UserPassesTestMixin, View):
    """Bulk-import a project's collection units (plots / farmers-households) from
    CSV. Staff for any project; a coordinator only for their own."""

    def test_func(self) -> bool:
        from .registry import console_can_edit

        return console_can_edit(self.request.user, "collection-units")

    def _ctx(self, request, **extra):
        ctx = {"groups": grouped(), "console_key": "collection-units",
               "projects": _editable_projects(request.user)}
        ctx.update(extra)
        return ctx

    def get(self, request):
        return render(request, "console/import_units.html", self._ctx(request))

    def post(self, request):
        from apps.fieldwork.imports import import_collection_units

        uc = _editable_projects(request.user).filter(pk=request.POST.get("project")).first()
        upload = request.FILES.get("csv")
        if uc is None or upload is None:
            return render(request, "console/import_units.html",
                          self._ctx(request, error="Pick a project and choose a CSV file."))
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return render(request, "console/import_units.html",
                          self._ctx(request, error="The file must be UTF-8 CSV."))

        report = import_collection_units(uc, text)
        if report.errors:
            return render(request, "console/import_units.html",
                          self._ctx(request, error=" ".join(report.errors)))
        messages.success(
            request,
            f"Imported units into {uc.code}: {report.created} created, "
            f"{report.updated} updated, {report.skipped} skipped.",
        )
        return redirect("console:list", key="collection-units")


def _scoped_get(user, m, key, pk):
    """Fetch an object — staff: any; Regional/Country Coordinator: geography &
    crops within their institution; other coordinators: within their projects."""
    if user.is_staff:
        return get_object_or_404(m.model, pk=pk)
    from .registry import GEO_CONSOLE_KEYS, ORG_FILTER_PATHS, PROJECT_FILTER_PATHS, is_geo_manager

    if key in GEO_CONSOLE_KEYS and is_geo_manager(user):
        opath = ORG_FILTER_PATHS.get(key)
        org_id = getattr(user, "organization_id", None)
        if not opath or not org_id:
            raise Http404("Not available.")
        return get_object_or_404(m.model, pk=pk, **{opath: org_id})
    path = PROJECT_FILTER_PATHS.get(key)
    if path is None:
        raise Http404("Not available.")
    return get_object_or_404(m.model, pk=pk, **{f"{path}__in": _coordinator_uc_ids(user)})


def _restrict_form_to_scope(form, user):
    """Limit a form's foreign-key choices so a coordinator can never attach a row
    outside their authority — their own projects, and their own institution's
    organization/region/country (for Regional/Country Coordinators)."""
    if user.is_staff:
        return
    from apps.projects.models import Country, Organization, Project, Region

    uc_ids = _coordinator_uc_ids(user)
    org_id = getattr(user, "organization_id", None)
    for field in form.fields.values():
        qs = getattr(field, "queryset", None)
        if qs is None:
            continue
        model = qs.model
        if model is Project:
            field.queryset = qs.filter(id__in=uc_ids)
        elif model is Organization and org_id:
            field.queryset = qs.filter(id=org_id)
        elif model is Region and org_id:
            field.queryset = qs.filter(organization_id=org_id)
        elif model is Country and org_id:
            field.queryset = qs.filter(region__organization_id=org_id)
        elif any(f.name == "project" for f in model._meta.fields):
            field.queryset = qs.filter(project_id__in=uc_ids)


def _default_project(form, request):
    """Pre-select a new row's Project to the workspace the coordinator is in — the
    ?project= carried by every sidebar console link, else the active-project
    session. Only applies when the form still offers that project as a choice."""
    field = form.fields.get("project")
    if field is None or getattr(field, "queryset", None) is None:
        return
    code = request.GET.get("project") or request.session.get("active_project")
    if not code:
        return
    uc = field.queryset.filter(code=code).first()
    if uc is not None:
        form.initial.setdefault("project", uc.pk)


class ConsoleFormView(UserPassesTestMixin, View):
    """Create/edit — staff for any section; a coordinator for their own
    projects' configuration & field data, scoped on both the object and the
    foreign-key choices."""

    def test_func(self) -> bool:
        from .registry import console_can_edit

        return console_can_edit(self.request.user, self.kwargs.get("key"))

    def _form_class(self, m: Managed):
        if m.form_class is not None:
            return m.form_class
        return modelform_factory(m.model, fields=m.form_fields or "__all__")

    def get(self, request, key, pk=None):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        instance = _scoped_get(request.user, m, key, pk) if pk else None
        form = self._form_class(m)(instance=instance)
        _restrict_form_to_scope(form, request.user)
        if instance is None:
            _default_project(form, request)
        return render(request, "console/form.html", _base_ctx(m) | {"form": form, "instance": instance})

    def post(self, request, key, pk=None):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        instance = _scoped_get(request.user, m, key, pk) if pk else None
        form = self._form_class(m)(request.POST, instance=instance)
        _restrict_form_to_scope(form, request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            # Stamp who granted a membership, when not already set.
            if hasattr(obj, "granted_by_id") and not obj.granted_by_id:
                obj.granted_by = request.user
            obj.save()
            form.save_m2m()
            messages.success(request, f"{m.model._meta.verbose_name.title()} saved.")
            return redirect("console:list", key=key)
        return render(request, "console/form.html", _base_ctx(m) | {"form": form, "instance": instance})


class PublishFormView(GeoManagerMixin, View):
    """Design & publish: an Admin or Regional/Country Coordinator uploads an
    XLSForm and publishes it to a project's collection server; on success the
    form is recorded and ready to grant + collect. Non-staff users may only
    publish to projects they can see (their region/country)."""

    def _projects(self, request):
        from apps.projects.models import Project

        if request.user.is_staff:
            return Project.objects.filter(is_active=True).order_by("code")
        from apps.rbac.permissions import visible_projects

        return visible_projects(request.user).filter(is_active=True).order_by("code")

    def _ctx(self, request, **extra):
        from apps.projects.models import FormDefinition

        ctx = {
            "groups": grouped(),
            "console_key": "forms",
            "projects": self._projects(request),
            "roles": FormDefinition.Role.choices,
        }
        ctx.update(extra)
        return ctx

    def get(self, request):
        return render(request, "console/publish_form.html", self._ctx(request))

    def post(self, request):
        from apps.ingestion.publishing import publish_xlsform

        # Scope the target to what this user may publish to (a coordinator can't
        # publish into another region's project by posting its id).
        uc = self._projects(request).filter(pk=request.POST.get("project")).first()
        upload = request.FILES.get("xlsform")
        role = request.POST.get("role") or "VALIDATION"
        if uc is None or upload is None:
            return render(request, "console/publish_form.html",
                          self._ctx(request, error="Pick a project and choose an XLSForm file."))

        form, result = publish_xlsform(
            uc, upload.read(), filename=upload.name, role=role,
            title=(request.POST.get("title") or "").strip(),
        )
        if not result.ok:
            return render(request, "console/publish_form.html",
                          self._ctx(request, error=result.message))

        messages.success(
            request,
            f"Published “{form.title or form.server_ref}” to {uc.code}. "
            f"Grant coordinators access, then “Sync now” once data starts arriving.",
        )
        return redirect("console:list", key="forms")


# ---------------------------------------------------------------------------
# In-app form builder (Tier 2): author a form spec, generate an XLSForm, publish.
# ---------------------------------------------------------------------------
def _builder_projects(request):
    from apps.projects.models import Project

    if request.user.is_staff:
        return Project.objects.filter(is_active=True).order_by("code")
    from apps.rbac.permissions import visible_projects

    return visible_projects(request.user).filter(is_active=True).order_by("code")


def _scoped_draft(request, pk):
    from apps.projects.models import FormDraft

    return get_object_or_404(
        FormDraft.objects.filter(project__in=_builder_projects(request)), pk=pk
    )


class FormBuilderListView(GeoManagerMixin, View):
    """Hub: existing drafts + entry points to build a new form or upload one."""

    def get(self, request):
        from apps.projects.models import FormDraft

        drafts = FormDraft.objects.filter(
            project__in=_builder_projects(request)
        ).select_related("project", "created_by").order_by("-updated_at")[:200]
        return render(request, "console/form_builder_list.html",
                      {"groups": grouped(), "console_key": "forms", "drafts": drafts})


class FormDraftEditView(GeoManagerMixin, View):
    """Create or edit a draft: the question editor. Saves the posted spec JSON."""

    def _ctx(self, request, draft=None, **extra):
        from apps.projects.models import FormDefinition
        from apps.vocabulary.models import VocabularyVariable

        ctx = {
            "groups": grouped(),
            "console_key": "forms",
            "projects": _builder_projects(request),
            "roles": FormDefinition.Role.choices,
            "draft": draft,
            "posted": {"title": "", "spec": ""},
            "vocab": list(
                VocabularyVariable.objects.values("name", "data_type", "unit",
                                                  "valid_min", "valid_max", "value_list")
            ),
        }
        ctx.update(extra)
        return ctx

    def get(self, request, pk=None):
        draft = _scoped_draft(request, pk) if pk else None
        return render(request, "console/form_builder_edit.html", self._ctx(request, draft))

    def post(self, request, pk=None):
        import json

        from apps.ingestion.xlsform import XlsFormError, build_xlsform
        from apps.projects.models import FormDraft
        from apps.vocabulary.importer import match_terms

        draft = _scoped_draft(request, pk) if pk else None
        uc = _builder_projects(request).filter(pk=request.POST.get("project")).first()
        title = (request.POST.get("title") or "").strip()
        try:
            spec = json.loads(request.POST.get("spec") or "{}")
        except json.JSONDecodeError:
            spec = {}
        if uc is None or not title or not spec.get("questions"):
            return render(request, "console/form_builder_edit.html", self._ctx(
                request, draft, error="Pick a project, give a title, and add at least one question.",
                posted={"title": title, "spec": request.POST.get("spec") or ""}))

        spec.setdefault("settings", {})
        spec["settings"].setdefault("form_title", title)
        # Dry-run the generation so bad specs are caught before saving.
        try:
            build_xlsform(spec)
        except XlsFormError as exc:
            return render(request, "console/form_builder_edit.html", self._ctx(
                request, draft, error=f"Form isn't valid yet: {exc}",
                posted={"title": title, "spec": request.POST.get("spec") or ""}))

        names = [q.get("name") for q in spec["questions"]
                 if (q.get("type") or "text") not in {
                     "begin_group", "end_group", "begin_repeat", "end_repeat"}]
        missing = match_terms(names).missing

        if draft is None:
            draft = FormDraft(project=uc, created_by=request.user)
        draft.project = uc
        draft.title = title
        draft.form_id = (request.POST.get("form_id") or "").strip()
        draft.role = request.POST.get("role") or "VALIDATION"
        draft.spec = spec
        draft.missing_terms = missing
        draft.save()
        messages.success(request, f"Saved draft “{draft.title}”"
                                  + (f" — {len(missing)} term(s) not in the vocabulary." if missing else "."))
        if request.POST.get("action") == "publish":
            return redirect("console:form_publish_draft", pk=draft.pk)
        return redirect("console:form_edit", pk=draft.pk)


class FormDraftPublishView(GeoManagerMixin, View):
    """Generate the XLSForm from a draft and push it to the project's server."""

    def post(self, request, pk):
        from django.utils import timezone

        from apps.ingestion.publishing import publish_xlsform
        from apps.ingestion.xlsform import XlsFormError, build_xlsform

        draft = _scoped_draft(request, pk)
        try:
            xlsx = build_xlsform(draft.spec)
        except XlsFormError as exc:
            messages.error(request, f"Couldn't generate the form: {exc}")
            return redirect("console:form_edit", pk=draft.pk)

        form, result = publish_xlsform(
            draft.project, xlsx, filename=f"{draft.form_id or 'form'}.xlsx",
            role=draft.role, title=draft.title,
        )
        if not result.ok:
            messages.error(request, f"Publish failed: {result.message}")
            return redirect("console:form_edit", pk=draft.pk)

        draft.status = draft.Status.PUBLISHED
        draft.published_form = form
        draft.published_at = timezone.now()
        draft.save(update_fields=["status", "published_form", "published_at", "updated_at"])
        messages.success(request, f"Published “{draft.title}” to {draft.project.code}.")
        return redirect("console:list", key="forms")


class FormDraftDeleteView(GeoManagerMixin, View):
    def post(self, request, pk):
        draft = _scoped_draft(request, pk)
        draft.delete()
        messages.success(request, "Draft deleted.")
        return redirect("console:form_builder")


class FormOverviewView(ManageMixin, View):
    """A per-form landing (ONA-style): health stats + trend + how a field worker
    collects it (server URL + ODK Collect QR). Open to staff and coordinators who
    manage the form's project (scoped below); reachable from Manage → Forms."""

    ROLE_RELATION = {
        "ENUM_REG": "Registers enumerators",
        "HH_REG": "Registers households / clients",
        "VALIDATION": "Collects validation data",
        "NOT": "Nutrient-omission trial data",
        "INTERCROP": "Intercropping data",
        "EXTRA": "Extra data",
    }

    def get(self, request, pk):
        from datetime import date, timedelta

        from django.db.models import Max
        from django.utils import timezone

        from apps.kpi.builder import _spark_svg
        from apps.kpi.models import FormKpiDaily
        from apps.projects.models import FormDefinition
        from apps.submissions.models import Submission

        from .collect import collect_qr_data_uri, collect_server_url

        forms = FormDefinition.objects.select_related("project", "project__data_source")
        if not request.user.is_staff:
            forms = forms.filter(project__in=_builder_projects(request))
        form = get_object_or_404(forms, pk=pk)

        subs = Submission.objects.filter(form=form)
        total = subs.count()
        contributors = subs.filter(enumerator__isnull=False).values("enumerator").distinct().count()
        last = subs.aggregate(m=Max("ingested_at"))["m"]

        since = timezone.localdate() - timedelta(days=30)
        rows = (FormKpiDaily.objects.filter(form=form, date__gte=since)
                .order_by("date").values("date", "submissions"))
        points = [{"label": r["date"].isoformat(), "value": r["submissions"] or 0} for r in rows]
        spark = _spark_svg([p["value"] for p in points]) if points else ""

        server_url = collect_server_url(form.project)
        return render(request, "console/form_overview.html", {
            "groups": grouped(), "console_key": "forms", "form": form,
            "total": total, "contributors": contributors, "last": last,
            "spark_svg": spark, "points_n": len(points),
            "relation": self.ROLE_RELATION.get(form.role, form.get_role_display()),
            "server_url": server_url,
            "qr": collect_qr_data_uri(server_url, form.project.name) if server_url else "",
        })


class VocabularyBrowseView(GeoManagerMixin, View):
    """Read-only browse of the Terminag controlled vocabulary — so a form
    designer can see the standard variable names and their constraints."""

    def get(self, request):
        from apps.vocabulary.models import VocabularyVariable

        q = (request.GET.get("q") or "").strip()
        category = (request.GET.get("category") or "").strip()
        qs = VocabularyVariable.objects.all()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if category:
            qs = qs.filter(category=category)

        categories = list(
            VocabularyVariable.objects.order_by("category")
            .values_list("category", flat=True).distinct()
        )
        page = Paginator(qs.order_by("category", "name"), 100).get_page(request.GET.get("page"))
        return render(request, "console/vocabulary.html", {
            "groups": grouped(), "console_key": "forms",
            "page": page, "q": q, "category": category, "categories": categories,
            "total": VocabularyVariable.objects.count(),
        })


class FormAIDraftView(GeoManagerMixin, View):
    """Tier 3: upload/paste a protocol, let the AI draft a form into the builder
    for review. Human-in-the-loop — the draft is never auto-published."""

    def _ctx(self, request, **extra):
        from apps.ingestion import form_ai

        ctx = {
            "groups": grouped(),
            "console_key": "forms",
            "projects": _builder_projects(request),
            "ai_enabled": form_ai.is_enabled(),
        }
        ctx.update(extra)
        return ctx

    def get(self, request):
        return render(request, "console/form_ai.html", self._ctx(request))

    def post(self, request):
        from django.utils import timezone

        from apps.ingestion import form_ai
        from apps.ingestion.protocol_text import ProtocolError, extract_text
        from apps.ingestion.xlsform import XlsFormError, build_xlsform
        from apps.projects.models import FormDraft
        from apps.vocabulary.importer import match_terms

        uc = _builder_projects(request).filter(pk=request.POST.get("project")).first()
        title = (request.POST.get("title") or "").strip()
        if uc is None or not title:
            return render(request, "console/form_ai.html",
                          self._ctx(request, error="Pick a project and give the form a title."))

        # Text from a pasted box or an uploaded protocol file.
        text = (request.POST.get("protocol_text") or "").strip()
        upload = request.FILES.get("protocol_file")
        if upload is not None and not text:
            try:
                text = extract_text(upload.name, upload.read())
            except ProtocolError as exc:
                return render(request, "console/form_ai.html", self._ctx(request, error=str(exc)))
        if not text:
            return render(request, "console/form_ai.html",
                          self._ctx(request, error="Paste the protocol text or upload a file."))

        try:
            spec = form_ai.draft_spec(text)
            spec.setdefault("settings", {})["form_title"] = title
            build_xlsform(spec)  # validate the AI output before saving
        except (form_ai.FormAIError, XlsFormError) as exc:
            return render(request, "console/form_ai.html", self._ctx(request, error=str(exc)))

        names = [q.get("name") for q in spec["questions"]
                 if (q.get("type") or "text") not in {
                     "begin_group", "end_group", "begin_repeat", "end_repeat"}]
        draft = FormDraft.objects.create(
            project=uc, title=title, spec=spec, created_by=request.user,
            source=FormDraft.Source.AI, missing_terms=match_terms(names).missing,
        )
        messages.success(request, "Drafted from the protocol — review and edit before publishing.")
        return redirect("console:form_edit", pk=draft.pk)


class OnboardProjectView(StaffMixin, View):
    """Onboard a new project to monitor, end to end, from inside the app:

    1. Define the project (paste/upload a YAML config, or start from a template).
    2. It is created with its forms, mappings, schedule and rules.
    3. Hit "Sync now" on the project to pull ONA submissions and start monitoring.

    Also surfaces ONA form discovery so you can see which forms the token can reach.
    """

    TEMPLATE_YAML = (
        "project:\n"
        "  code: MY-PROJECT\n"
        "  name: My Project\n"
        "  is_active: true\n"
        "  countries: [Country]\n"
        "  enid_patterns: ['^EN']\n"
        "  hhid_patterns: ['^HH']\n"
        "crops:\n  - {name: maize}\n"
        "stages: [Validation]\n"
        "trials:\n  - {name: Fertilizer Recommendation, code: FR}\n"
        "forms:\n"
        "  - ona_form_id: 000000\n"
        "    role: VALIDATION\n"
        "    mappings:\n"
        "      - {target: ENID, source: ['intro/enumerator_id'], transform: DIRECT}\n"
        "      - {target: HHID, source: ['intro/household_id'], transform: DIRECT}\n"
        "      - {target: event_key, source: ['intro/event'], transform: DIRECT}\n"
        "event_schedule:\n"
        "  - {event_key: Event1, sequence: 1, anchor: SITE_SELECTION, offset_days: 14}\n"
        "validation_rules:\n"
        "  - {code: enid_pattern, type: REGEX_ID, severity: ERROR,\n"
        "     params: {field: ENID, patterns: ['^EN'], message: 'Check ENID'}}\n"
    )

    def _discover_forms(self):
        from apps.ingestion.backends.registry import build_backend

        try:
            return build_backend().list_forms(), None
        except Exception as exc:  # network/transport issues
            return [], f"Could not reach the server: {exc}"

    def get(self, request):
        forms, discover_error = self._discover_forms()
        return render(request, "console/onboard.html", {
            "groups": grouped(),
            "console_key": "projects",
            "yaml_template": self.TEMPLATE_YAML,
            "discovered_forms": forms,
            "discover_error": discover_error,
            "yaml_text": request.GET.get("yaml", ""),
        })

    def post(self, request):
        from apps.config_admin.loader import ConfigError, import_config, validate_config

        raw = request.POST.get("yaml") or ""
        if "file" in request.FILES:
            raw = request.FILES["file"].read().decode("utf-8", "replace")

        import yaml as _yaml

        problems: list[str] = []
        uc = None
        try:
            data = _yaml.safe_load(raw)
            if not isinstance(data, dict):
                problems = ["Config must be a YAML mapping (project: ...)."]
            else:
                problems = validate_config(data)
                if not problems:
                    from apps.config_admin.loader import check_duplicate_import
                    dup = check_duplicate_import(data)
                    if dup and request.POST.get("confirm_duplicate") != "1":
                        problems = dup + [
                            "Add a 'confirm_duplicate' field (or use the guided "
                            "wizard) to onboard anyway."
                        ]
                    else:
                        uc = import_config(data)
        except _yaml.YAMLError as exc:
            problems = [f"Invalid YAML: {exc}"]
        except ConfigError as exc:
            problems = [str(exc)]

        if uc is not None:
            messages.success(
                request,
                f"Project “{uc.code}” onboarded — {uc.forms.count()} form(s). "
                f"Use “Sync now” to pull submissions.",
            )
            return redirect("console:list", key="projects")

        forms, discover_error = self._discover_forms()
        return render(request, "console/onboard.html", {
            "groups": grouped(),
            "console_key": "projects",
            "yaml_template": self.TEMPLATE_YAML,
            "discovered_forms": forms,
            "discover_error": discover_error,
            "yaml_text": raw,
            "problems": problems,
        })


def _backend_from_request(request):
    """Build a CollectionBackend from the server creds in the request (backend
    type, base_url, token), defaulting to the globally-configured ONA."""
    from apps.ingestion.backends.registry import build_backend

    src = request.POST if request.method == "POST" else request.GET
    return build_backend(
        src.get("backend") or "ONA",
        base_url=(src.get("base_url") or "").strip(),
        token=(src.get("token") or "").strip(),
    )


class WizardView(StaffMixin, View):
    """Form-based onboarding: a *project* on a collection server becomes a use
    case; its *forms* become the entries. Auto-suggests mappings, then imports."""

    def _ctx(self, request, **extra):
        from django.conf import settings

        from apps.accounts.models import User
        from apps.ingestion.backends.registry import BACKEND_CHOICES
        from apps.projects.models import Country, Crop, FormDefinition, Organization

        from .onboarding import CANONICAL_TARGETS

        # Per-backend default server URLs the wizard prefills as a placeholder so
        # coordinators don't type the hub's ODK Central address each time.
        backend_defaults = {
            "ODK_CENTRAL": getattr(settings, "ODK_CENTRAL_BASE_URL", ""),
            "ONA": getattr(settings, "ONA_BASE_URL", "https://api.ona.io"),
            "KOBO": getattr(settings, "KOBO_BASE_URL", ""),
        }

        # Existing crops offered as pick-from chips (crops are per-project, so the
        # catalogue is the distinct set of names already in use anywhere).
        existing_crops = sorted(
            {c for c in Crop.objects.values_list("name", flat=True) if c},
            key=str.lower,
        )
        # No network here — projects are discovered asynchronously (see
        # WizardProjectsView) so the wizard opens instantly.
        ctx = {
            "groups": grouped(),
            "console_key": "projects",
            "roles": FormDefinition.Role.choices,
            "backends": BACKEND_CHOICES,
            "targets": CANONICAL_TARGETS,
            "organizations": Organization.objects.filter(is_active=True),
            # Owner candidates for the searchable picker — any existing account
            # (org-less ones included, since org is only set at first grant).
            "owner_candidates": User.objects.all().order_by("full_name", "email"),
            # Pick countries from the geo registry (drives the coordinator
            # hierarchy) and crops from what already exists — no free typing.
            "existing_countries": Country.objects.select_related("region").order_by("name"),
            "existing_crops": existing_crops,
            "backend_defaults": backend_defaults,
        }
        ctx.update(extra)
        # Re-check the chips the user had ticked when redisplaying after an error.
        posted = extra.get("posted")
        if posted is not None:
            getlist = getattr(posted, "getlist", lambda k: [])
            ctx["posted_countries"] = getlist("countries")
            ctx["posted_crops"] = getlist("crops")
        return ctx

    def get(self, request):
        return render(request, "console/wizard.html", self._ctx(request))

    def post(self, request):
        from apps.config_admin.loader import (
            ConfigError,
            check_duplicate_import,
            import_config,
            validate_config,
        )

        from .onboarding import build_config

        try:
            data = build_config(request.POST)
            problems = validate_config(data)
            # Every project must be owned by a specific existing user.
            if not (request.POST.get("owner") or "").strip():
                problems = ["Choose an owner for this project."] + problems
            if not problems:
                # Guard against onboarding the same collection-server project twice
                # under a different name. The user can override for genuine cases.
                dup = check_duplicate_import(data)
                if dup and request.POST.get("confirm_duplicate") != "1":
                    return render(request, "console/wizard.html",
                                  self._ctx(request, dup_warnings=dup, posted=request.POST))
                uc = import_config(data)
                # Import each form's name + full field list now, so the rule
                # builder (and anything field-aware) has them from the start.
                try:
                    from apps.ingestion.form_schema import sync_project_schemas
                    sync_project_schemas(uc)
                except Exception:
                    pass
                messages.success(
                    request,
                    f"Project “{uc.code}” onboarded — {uc.forms.count()} form(s). "
                    f"Use “Sync now” to pull submissions.",
                )
                return redirect("console:list", key="projects")
        except (ConfigError, ValueError) as exc:
            problems = [str(exc)]
        return render(request, "console/wizard.html",
                      self._ctx(request, problems=problems, posted=request.POST))


class WizardProjectsView(StaffMixin, View):
    """HTMX: discover projects on the selected server (loaded after the page so
    the wizard opens instantly)."""

    def get(self, request):
        import hashlib

        from django.core.cache import cache

        src = request.GET
        key = "wizard_projects:" + hashlib.sha256(
            f"{src.get('backend')}|{src.get('base_url')}|{src.get('token')}".encode()
        ).hexdigest()
        # The "Find projects" button forces a fresh fetch; auto-load uses the cache.
        projects, error = None, None
        if request.GET.get("refresh") != "1":
            cached = cache.get(key)
            if cached is not None:
                projects, error = cached.get("projects"), cached.get("discover_error")
        if projects is None and error is None:
            projects, error = [], None
            try:
                projects = _backend_from_request(request).discover_projects()
            except NotImplementedError:
                error = "This backend doesn't support discovery — enter details manually."
            except Exception as exc:
                error = f"Could not reach the server: {exc}"
            if not error:
                cache.set(key, {"projects": projects, "discover_error": error}, 300)  # 5 min
        # Mark which discovered projects are already onboarded (fresh each render).
        self._annotate_onboarded(projects or [])
        return render(request, "console/_wizard_projects.html",
                      {"projects": projects or [], "discover_error": error})

    def _annotate_onboarded(self, projects):
        """Set `onboarded_as` on each RemoteProject to the code of a Fieldbase
        project already mirroring it — by server project id, else by shared form
        id — so the wizard can warn before any form is picked."""
        from apps.projects.models import DataSource, FormDefinition

        ds_pids: dict = {}
        for ds in DataSource.objects.exclude(config={}).select_related("project"):
            pid = (ds.config or {}).get("project_id")
            if pid:
                ds_pids.setdefault(str(pid), ds.project.code)
        form_owner: dict = {}
        for f in FormDefinition.objects.select_related("project"):
            for k in filter(None, [str(f.ona_form_id or "") or "", f.server_form_id or ""]):
                form_owner.setdefault(k, f.project.code)
        for p in projects:
            owner = ds_pids.get(str(p.id))
            if not owner:
                for rf in getattr(p, "forms", []) or []:
                    if str(rf.id) in form_owner:
                        owner = form_owner[str(rf.id)]
                        break
            p.onboarded_as = owner


class FieldDiscoveryView(StaffMixin, View):
    """HTMX: given a form id + block index, return mapping rows with the form's
    fields and auto-suggested selections (via the selected backend)."""

    def post(self, request):
        from .onboarding import CANONICAL_TARGETS, suggest_mappings

        index = request.POST.get("index", "0")
        form_id = (request.POST.get("form_id") or "").strip()
        fields: list[str] = []
        error = None
        if form_id:
            try:
                fields = _backend_from_request(request).sample_fields(form_id)
            except Exception as exc:
                error = f"Could not reach the server: {exc}"
        suggested = suggest_mappings(fields)
        return render(request, "console/_mapping_rows.html", {
            "index": index,
            "fields": fields,
            "targets": CANONICAL_TARGETS,
            "suggested": suggested,
            "error": error,
        })


class ConsoleActionView(StaffMixin, View):
    """Run a per-row action (e.g. Sync now, Approve). Returns the action's
    HttpResponse (downloads) or flashes its message and returns to the list."""

    def post(self, request, key, pk, slug):
        m = _managed(key)
        action = next((a for a in m.actions if a.slug == slug), None)
        if action is None:
            raise Http404(f"Unknown action: {slug}")
        obj = get_object_or_404(m.model, pk=pk)
        result = action.fn(request, obj)
        from django.http import HttpResponse

        if isinstance(result, HttpResponse):
            return result
        messages.success(request, result or "Done.")
        return redirect("console:list", key=key)


class ConsoleDeleteView(UserPassesTestMixin, View):
    def test_func(self) -> bool:
        from .registry import console_can_edit

        return console_can_edit(self.request.user, self.kwargs.get("key"))

    def get(self, request, key, pk):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        obj = _scoped_get(request.user, m, key, pk)
        return render(request, "console/delete.html", _base_ctx(m) | {"obj": obj})

    def post(self, request, key, pk):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        obj = _scoped_get(request.user, m, key, pk)
        label = str(obj)
        obj.delete()
        messages.success(request, f"Deleted “{label}”.")
        return redirect("console:list", key=key)


class WriteBackQueueView(ManageMixin, View):
    """Operational queue: submissions whose reviewer edits still need to reach the
    source server. Retry one or flush all PENDING/FAILED. Coordinators see and
    act on only their own projects' queue."""

    def _queue(self, request):
        from apps.submissions.models import Submission

        status = Submission.WriteBackStatus
        qs = Submission.objects.filter(writeback_status__in=[status.PENDING, status.FAILED])
        if not request.user.is_staff:
            qs = qs.filter(project_id__in=_coordinator_uc_ids(request.user))
        return qs.select_related("project", "enumerator", "collection_unit").order_by(
            "writeback_status", "-updated_at"
        )

    def get(self, request):
        from django.conf import settings

        qs = self._queue(request)
        ctx = _console_page_ctx("writeback") | {
            "rows": qs[:300],
            "pending": qs.filter(writeback_status="PENDING").count(),
            "failed": qs.filter(writeback_status="FAILED").count(),
            "enabled": getattr(settings, "WRITEBACK_ENABLED", False),
        }
        return render(request, "console/writeback.html", ctx)

    def post(self, request):
        from apps.ingestion.tasks import writeback_submission_task

        qs = self._queue(request)  # already scoped to the user's projects
        action = request.POST.get("action")
        if action == "flush":
            ids = list(qs.values_list("pk", flat=True))
            for pk in ids:
                writeback_submission_task.delay(str(pk))
            messages.success(request, f"Queued write-back for {len(ids)} submission(s).")
        elif action == "retry":
            pk = request.POST.get("submission_id")
            # Only act on a submission inside the user's scoped queue.
            if pk and qs.filter(pk=pk).exists():
                writeback_submission_task.delay(str(pk))
                messages.success(request, "Write-back retried.")
        return redirect("console:writeback")


def _csv_list(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


class FormMappingsView(StaffMixin, View):
    """Inline editor for one form's field mappings (add / edit / delete rows)."""

    def _form(self, pk):
        from apps.projects.models import FormDefinition

        return get_object_or_404(FormDefinition.objects.select_related("project"), pk=pk)

    def _ctx(self, form):
        from apps.projects.models import FieldMapping

        return _console_page_ctx("forms") | {
            "form": form,
            "mappings": form.mappings.all().order_by("order", "target_field"),
            "transforms": FieldMapping.Transform.choices,
        }

    def get(self, request, pk):
        return render(request, "console/form_mappings.html", self._ctx(self._form(pk)))

    def post(self, request, pk):
        from apps.projects.models import FieldMapping

        form = self._form(pk)

        if request.POST.get("action") == "import_csv":
            return self._import_csv(request, form)

        # Update or delete existing mappings.
        for m in list(form.mappings.all()):
            if request.POST.get(f"map-{m.pk}-delete"):
                m.delete()
                continue
            target = (request.POST.get(f"map-{m.pk}-target") or "").strip()
            if not target:
                continue
            m.target_field = target
            m.source_paths = _csv_list(request.POST.get(f"map-{m.pk}-source"))
            m.transform = request.POST.get(f"map-{m.pk}-transform") or "DIRECT"
            m.required = bool(request.POST.get(f"map-{m.pk}-required"))
            m.order = int(request.POST.get(f"map-{m.pk}-order") or 0)
            m.save()
        # Create any new rows.
        i, created = 0, 0
        while f"new-{i}-target" in request.POST:
            target = (request.POST.get(f"new-{i}-target") or "").strip()
            if target:
                FieldMapping.objects.create(
                    form=form, target_field=target,
                    source_paths=_csv_list(request.POST.get(f"new-{i}-source")),
                    transform=request.POST.get(f"new-{i}-transform") or "DIRECT",
                    required=bool(request.POST.get(f"new-{i}-required")),
                    order=int(request.POST.get(f"new-{i}-order") or 0),
                )
                created += 1
            i += 1
        messages.success(request, f"Mappings saved{f' (+{created} new)' if created else ''}.")
        return redirect("console:form_mappings", pk=pk)

    def _import_csv(self, request, form):
        """Bulk-create mappings from CSV. Columns: target, source, transform,
        required, order. Multiple source paths in one cell are separated by ';'."""
        import csv
        import io

        from apps.projects.models import FieldMapping

        raw = request.POST.get("csv") or ""
        if "csv_file" in request.FILES:
            raw = request.FILES["csv_file"].read().decode("utf-8", "replace")
        if not raw.strip():
            messages.error(request, "No CSV provided.")
            return redirect("console:form_mappings", pk=form.pk)

        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)
        # Skip an optional header row.
        if rows and rows[0] and rows[0][0].strip().lower() in {"target", "target_field"}:
            rows = rows[1:]

        created = 0
        for row in rows:
            if not row or not row[0].strip():
                continue
            cols = (row + ["", "", "", ""])[:5]
            target, source, transform, required, order = (c.strip() for c in cols)
            FieldMapping.objects.create(
                form=form,
                target_field=target,
                source_paths=[s.strip() for s in source.split(";") if s.strip()],
                transform=(transform or "DIRECT").upper(),
                required=required.lower() in {"1", "true", "yes", "y"},
                order=int(order) if order.isdigit() else 0,
            )
            created += 1
        messages.success(request, f"Imported {created} mapping(s) from CSV.")
        return redirect("console:form_mappings", pk=form.pk)


class JobAssignmentsView(UserPassesTestMixin, View):
    """Assign collection units (and an enumerator each) to a job. Staff for any;
    a coordinator only for jobs in their own projects."""

    def test_func(self) -> bool:
        from .registry import console_can_edit

        return console_can_edit(self.request.user, "jobs")

    def _job(self, request, pk):
        return _scoped_get(request.user, _managed("jobs"), "jobs", pk)

    def _ctx(self, job):
        from apps.fieldwork.models import CollectionUnit
        from apps.fieldwork.services import (
            job_enumerator_progress,
            job_progress,
            project_enumerators,
        )

        taken = job.assignments.values_list("unit_id", flat=True)
        return _console_page_ctx("jobs") | {
            "job": job,
            "can_edit": True,  # reaching this view already requires edit rights
            "assignments": job.assignments.select_related("unit", "enumerator")
            .prefetch_related("unit__submissions").all(),
            "available_units": CollectionUnit.objects.filter(project=job.project)
            .exclude(id__in=taken).order_by("code"),
            "enumerators": project_enumerators(job.project),
            "progress": job_progress(job),
            "enum_progress": job_enumerator_progress(job),
        }

    def get(self, request, pk):
        return render(request, "console/job_assignments.html", self._ctx(self._job(request, pk)))

    def post(self, request, pk):
        from apps.accounts.models import User
        from apps.fieldwork.models import CollectionUnit, UnitAssignment

        job = self._job(request, pk)
        action = request.POST.get("action")
        enum = User.objects.filter(pk=request.POST.get("enumerator")).first()

        if action == "close_job":
            job.close(request.user, note=(request.POST.get("closure_note") or "").strip())
            messages.success(request, f"Job {job.name} closed.")
        elif action == "reopen_job":
            job.status = job.Status.ACTIVE
            job.closed_at = job.closed_by = None
            job.closure_note = ""
            job.save(update_fields=["status", "closed_at", "closed_by", "closure_note", "updated_at"])
            messages.success(request, f"Job {job.name} reopened.")
        elif action == "remove":
            UnitAssignment.objects.filter(job=job, pk=request.POST.get("assignment")).delete()
        elif action == "assign_all":
            units = CollectionUnit.objects.filter(project=job.project).exclude(
                assignments__job=job)
            UnitAssignment.objects.bulk_create(
                [UnitAssignment(job=job, unit=u, enumerator=enum) for u in units])
            if enum:
                job.assigned_to.add(enum)
            messages.success(request, f"Assigned {len(units)} unit(s).")
        else:  # add one
            unit = CollectionUnit.objects.filter(
                project=job.project, pk=request.POST.get("unit")).first()
            if unit:
                UnitAssignment.objects.get_or_create(
                    job=job, unit=unit, defaults={"enumerator": enum})
                if enum:
                    job.assigned_to.add(enum)
        return redirect("console:job_assignments", pk=job.pk)


class PlotElectionQueueView(ManageMixin, View):
    """The coordinator's election backlog for a project: one row per trial, with its
    candidate plots and which (if any) is elected. Scoped to editable projects."""

    def get(self, request):
        from apps.fieldwork.anchor_form import anchor_form_for, pending_anchor_trials
        from apps.fieldwork.election import election_progress, trial_rows

        projects = _editable_projects(request.user)
        uc = projects.filter(code=request.GET.get("project")).first() or projects.first()
        ctx = {"projects": projects, "uc": uc, "rows": [], "progress": None,
               "anchor_form": None, "pending_anchors": 0}
        if uc is not None:
            ctx["rows"] = trial_rows(uc)
            ctx["progress"] = election_progress(uc)
            ctx["anchor_form"] = anchor_form_for(uc)
            ctx["pending_anchors"] = len(pending_anchor_trials(uc))
        return render(request, "console/plot_election.html", ctx)

    def post(self, request):
        """Coordinator anchor-form actions: publish the field micro-form, or pull
        captured anchors back onto the units."""
        from django.urls import reverse

        from apps.fieldwork.anchor_form import apply_anchor_submissions, publish_anchor_form

        projects = _editable_projects(request.user)
        uc = get_object_or_404(projects, code=request.POST.get("project"))
        action = request.POST.get("action")
        if action == "publish_anchor_form":
            form, result = publish_anchor_form(uc)
            if result.ok:
                messages.success(request, f"Anchor form published to the server ({result.title}).")
            else:
                messages.error(request, f"Could not publish anchor form: {result.message}")
        elif action == "sync_anchors":
            stats = apply_anchor_submissions(uc, request.user)
            messages.success(
                request,
                f"Anchor sync: {stats.captured} captured, {stats.outside} outside boundary, "
                f"{stats.skipped} skipped.",
            )
        return redirect(f"{reverse('console:plot_election')}?project={uc.code}")


class PlotElectionView(ManageMixin, View):
    """Elect one candidate plot for a single trial (or flag no-valid-plot)."""

    def _uc(self, request, code):
        return get_object_or_404(_editable_projects(request.user), code=code)

    def get(self, request, code, trial_key):
        from apps.dashboards.charts import candidate_plots_map_html
        from apps.fieldwork.models import CandidatePlot

        uc = self._uc(request, code)
        cands = list(CandidatePlot.objects.filter(project=uc, trial_key=trial_key))
        if not cands:
            raise Http404("No candidates for this trial.")
        elected = next((c for c in cands if c.status == CandidatePlot.Status.ELECTED), None)
        return render(request, "console/plot_elect.html", {
            "uc": uc, "trial_key": trial_key, "candidates": cands,
            "map_html": candidate_plots_map_html(cands),
            "elected": elected,
            "unit": elected.collection_unit if elected else None,
        })

    def post(self, request, code, trial_key):
        from django.urls import reverse

        from apps.fieldwork.anchor import capture_anchor
        from apps.fieldwork.election import elect_candidate, mark_no_valid_plot
        from apps.fieldwork.models import CandidatePlot

        uc = self._uc(request, code)
        note = (request.POST.get("note") or "").strip()
        queue_url = f"{reverse('console:plot_election')}?project={uc.code}"
        elect_url = redirect("console:plot_elect", code=uc.code, trial_key=trial_key)
        if request.POST.get("action") == "capture_anchor":
            elected = CandidatePlot.objects.filter(
                project=uc, trial_key=trial_key, status=CandidatePlot.Status.ELECTED
            ).select_related("collection_unit").first()
            if elected is None or elected.collection_unit is None:
                messages.error(request, "Elect a plot before capturing its anchor.")
                return elect_url
            ok, msg = capture_anchor(request.user, elected.collection_unit,
                                     request.POST.get("lat"), request.POST.get("lon"))
            (messages.success if ok else messages.error)(request, msg)
            return elect_url
        if request.POST.get("action") == "no_valid_plot":
            n = mark_no_valid_plot(request.user, uc, trial_key, note=note)
            messages.success(request, f"Trial {trial_key}: flagged no valid plot ({n} candidates).")
            return redirect(queue_url)
        chosen = CandidatePlot.objects.filter(
            project=uc, trial_key=trial_key, pk=request.POST.get("candidate")).first()
        if chosen is None:
            messages.error(request, "Pick a candidate to elect.")
            return redirect("console:plot_elect", code=uc.code, trial_key=trial_key)
        if chosen.role == CandidatePlot.Role.BACKUP and not note:
            messages.error(request, "A reason is required when electing the backup plot.")
            return redirect("console:plot_elect", code=uc.code, trial_key=trial_key)
        elect_candidate(request.user, chosen, note=note)
        messages.success(request, f"Trial {trial_key}: elected plot {chosen.candidate_ref}.")
        return redirect(queue_url)


# ---------------------------------------------------------------------------
# Guided validation-rule builder — replaces raw JSON `params` with a form-scoped
# form: pick a form, pick its fields from dropdowns, set the check with plain
# controls. The client assembles `params`; the server validates and stores it.
# ---------------------------------------------------------------------------

def _form_field_choices(form) -> list[dict]:
    """Every field a rule can target on a form, as {key, label}: the imported form
    schema (all questions, with human labels), plus mapped canonical fields and any
    field key seen in submitted data. Ordered by label."""
    from apps.projects.models import FieldMapping
    from apps.submissions.models import SubmissionValue

    import re

    def clean(label, path):
        text = re.sub(r"<[^>]+>", "", str(label or ""))          # strip any HTML
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return path
        return text if len(text) <= 80 else text[:77] + "…"

    labels: dict = {}
    for f in (form.field_schema or []):
        path = f.get("path")
        # Skip display-only notes — they carry no data to check.
        if path and f.get("type") != "note":
            labels.setdefault(path, clean(f.get("label"), path))
    for t in FieldMapping.objects.filter(form=form).values_list("target_field", flat=True):
        if t:
            labels.setdefault(t, t)
    for k in (SubmissionValue.objects.filter(submission__form=form)
              .values_list("field_key", flat=True).distinct()):
        if k:
            labels.setdefault(k, k)
    return [{"key": k, "label": lbl}
            for k, lbl in sorted(labels.items(), key=lambda kv: str(kv[1]).lower())]


class RuleBuilderView(ManageMixin, View):
    """Create / edit a ValidationRule with a guided UI instead of JSON params."""

    def _rule(self, request, pk):
        from apps.validation.models import ValidationRule
        return get_object_or_404(
            ValidationRule.objects.filter(project__in=_builder_projects(request)), pk=pk
        )

    def _project(self, request):
        code = (request.GET.get("project") or request.POST.get("project")
                or request.session.get("active_project"))
        return _builder_projects(request).filter(code=code).first()

    def _ctx(self, request, project, rule=None, error=None, posted=None):
        from apps.projects.models import ReferenceDataset
        from apps.validation.models import ValidationRule

        forms = list(project.forms.all().order_by("title", "server_form_id"))
        fields_by_form = {str(f.id): _form_field_choices(f) for f in forms}
        datasets = {
            d.code: {"name": d.name, "columns": d.columns, "key_field": d.key_field}
            for d in ReferenceDataset.objects.filter(project=project)
        }
        # Rule types offered in the builder (PLUGIN is code-only, so it's excluded).
        types = [(v, lbl) for v, lbl in ValidationRule.RuleType.choices if v != "PLUGIN"]
        return {
            "console_key": "validation-rules", "groups": grouped(),
            "project": project, "rule": rule, "forms": forms,
            "fields_by_form": fields_by_form, "datasets": datasets,
            "rule_types": types,
            "severities": ValidationRule.Severity.choices,
            "rule_params": rule.params if rule else {},
            "error": error, "posted": posted or {},
        }

    def get(self, request, pk=None):
        rule = self._rule(request, pk) if pk else None
        project = rule.project if rule else self._project(request)
        if project is None:
            messages.error(request, "Pick a project first.")
            return redirect("console:list", key="validation-rules")
        return render(request, "console/rule_builder.html", self._ctx(request, project, rule))

    def post(self, request, pk=None):
        import json

        from django.urls import reverse
        from django.utils.text import slugify

        from apps.projects.models import FormDefinition
        from apps.validation.models import ValidationRule

        rule = self._rule(request, pk) if pk else None
        project = rule.project if rule else self._project(request)
        if project is None:
            messages.error(request, "Pick a project first.")
            return redirect("console:list", key="validation-rules")

        code = slugify(request.POST.get("code", "").strip())[:64]
        rule_type = request.POST.get("rule_type", "")
        severity = request.POST.get("severity") or ValidationRule.Severity.WARNING
        form_id = request.POST.get("form") or None
        enabled = request.POST.get("is_enabled") == "on"
        try:
            params = json.loads(request.POST.get("params") or "{}")
            if not isinstance(params, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            params = {}

        valid_types = {v for v, _ in ValidationRule.RuleType.choices}
        error = None
        if not code:
            error = "Give the rule a short name."
        elif rule_type not in valid_types:
            error = "Choose a rule type."
        form_obj = None
        if form_id:
            form_obj = FormDefinition.objects.filter(project=project, pk=form_id).first()
            if form_obj is None:
                error = "That form isn't part of this project."
        # A duplicate code within the project (excluding self) collides on save.
        dup = ValidationRule.objects.filter(project=project, code=code)
        if rule:
            dup = dup.exclude(pk=rule.pk)
        if not error and dup.exists():
            error = f"A rule named “{code}” already exists in this project."

        if error:
            ctx = self._ctx(request, project, rule, error=error, posted=request.POST)
            return render(request, "console/rule_builder.html", ctx)

        obj = rule or ValidationRule(project=project)
        obj.code = code
        obj.rule_type = rule_type
        obj.severity = severity
        obj.form = form_obj
        obj.params = params
        obj.is_enabled = enabled
        obj.auto_flag_state = True
        obj.save()
        messages.success(request, f"Rule “{code}” saved.")
        return redirect(f"{reverse('console:list', args=['validation-rules'])}?project={project.code}")


class RuleSchemaSyncView(ManageMixin, View):
    """Import / refresh every form's name and full field list from the collection
    server, so the builder's pickers offer all fields (by their labels)."""

    def post(self, request):
        from django.urls import reverse

        from apps.ingestion.form_schema import sync_project_schemas

        code = request.POST.get("project") or request.session.get("active_project")
        project = _builder_projects(request).filter(code=code).first()
        if project is None:
            messages.error(request, "Pick a project first.")
            return redirect("console:list", key="validation-rules")
        try:
            result = sync_project_schemas(project)
            fields = sum(v for v in result.values() if isinstance(v, int))
            messages.success(
                request,
                f"Imported {fields} field(s) across {len(result)} form(s) from the server.")
        except Exception as exc:
            messages.error(request, f"Couldn't reach the collection server: {exc}")
        back = request.POST.get("next") or f"{reverse('console:rule_new')}?project={project.code}"
        return redirect(back)


class RuleTestView(ManageMixin, View):
    """Preview how many current submissions a (possibly unsaved) rule would flag."""

    def post(self, request):
        import json

        from django.http import JsonResponse

        from apps.projects.models import FormDefinition
        from apps.submissions.models import Submission
        from apps.validation.engine import _run_rule
        from apps.validation.models import ValidationRule

        code = request.POST.get("project") or request.session.get("active_project")
        project = _builder_projects(request).filter(code=code).first()
        if project is None:
            return JsonResponse({"error": "Pick a project first."}, status=400)
        try:
            params = json.loads(request.POST.get("params") or "{}")
            if not isinstance(params, dict):
                params = {}
        except (ValueError, json.JSONDecodeError):
            params = {}
        form = None
        if request.POST.get("form"):
            form = FormDefinition.objects.filter(
                project=project, pk=request.POST["form"]).first()
        rule = ValidationRule(project=project, form=form,
                              rule_type=request.POST.get("rule_type", ""),
                              params=params, severity="WARNING")
        subs = list(Submission.objects.filter(project=project).select_related("collection_unit"))
        try:
            results = _run_rule(rule, subs)
        except Exception as exc:
            return JsonResponse({"error": f"Couldn't run the rule: {exc}"})
        flagged = {r.submission_id for r in results}
        scope = len([s for s in subs if form is None or s.form_id == form.id])
        return JsonResponse({
            "count": len(flagged), "scope": scope,
            "samples": [r.message for r in results[:3]],
        })


class ReferenceDatasetsView(ManageMixin, View):
    """List a project's reference datasets and import new ones from CSV — the
    sampling frames / lab results / lookups used to reconcile field data."""

    def _project(self, request):
        code = (request.GET.get("project") or request.POST.get("project")
                or request.session.get("active_project"))
        return _builder_projects(request).filter(code=code).first()

    def get(self, request, error=None, posted=None):
        from apps.projects.models import ReferenceDataset

        project = self._project(request)
        if project is None:
            messages.error(request, "Pick a project first.")
            return redirect("console:list", key="projects")
        datasets = ReferenceDataset.objects.filter(project=project).order_by("code")
        return render(request, "console/reference_datasets.html", {
            "console_key": "validation-rules", "groups": grouped(),
            "project": project, "datasets": datasets,
            "kinds": ReferenceDataset.Kind.choices, "error": error, "posted": posted or {},
        })

    def post(self, request):
        from apps.projects.reference import import_reference_csv

        project = self._project(request)
        if project is None:
            messages.error(request, "Pick a project first.")
            return redirect("console:list", key="projects")
        from django.utils.text import slugify

        f = request.FILES.get("file")
        code = slugify(request.POST.get("code", "").strip())[:64]
        name = (request.POST.get("name") or code).strip()[:120]
        kind = request.POST.get("kind") or "LOOKUP"
        key_field = (request.POST.get("key_field") or "").strip()
        if not (f and code and key_field):
            return self.get(request, error="Choose a CSV file, a name, and the key column.",
                            posted=request.POST)
        try:
            text = f.read().decode("utf-8-sig")
            ds = import_reference_csv(project, code=code, name=name, kind=kind,
                                      key_field=key_field, text=text)
        except (ValueError, UnicodeDecodeError) as exc:
            return self.get(request, error=str(exc), posted=request.POST)
        messages.success(request, f"Imported “{ds.name}” — {ds.row_count} row(s).")
        return redirect(f"{reverse('console:reference_datasets')}?project={project.code}")


class ReferenceDeleteView(ManageMixin, View):
    def post(self, request, pk):
        from apps.projects.models import ReferenceDataset

        ds = get_object_or_404(
            ReferenceDataset.objects.filter(project__in=_builder_projects(request)), pk=pk)
        code = ds.project.code
        ds.delete()
        messages.success(request, "Reference dataset removed.")
        return redirect(f"{reverse('console:reference_datasets')}?project={code}")


class ReferenceCoverageView(ManageMixin, View):
    """Reconcile a reference dataset against submissions: coverage %, planned
    samples never submitted (missing), and submitted ids not in the frame."""

    def get(self, request, pk):
        from apps.projects.models import ReferenceDataset
        from apps.projects.reference import reconcile

        ds = get_object_or_404(
            ReferenceDataset.objects.filter(project__in=_builder_projects(request)), pk=pk)
        field_key = request.GET.get("field") or ""
        result = reconcile(ds, field_key) if field_key else None
        fields, seen = [], set()
        for form in ds.project.forms.all():
            for c in _form_field_choices(form):
                if c["key"] not in seen:
                    seen.add(c["key"])
                    fields.append(c)
        return render(request, "console/reference_coverage.html", {
            "console_key": "validation-rules", "groups": grouped(),
            "project": ds.project, "ds": ds, "field_key": field_key,
            "result": result, "fields": fields,
        })


class SystemStatusView(StaffMixin, View):
    """Operational visibility: recent sync outcomes + which projects have gone
    quiet — so a failing sync or a project that stopped receiving data can't
    slip by unnoticed."""

    def get(self, request):
        from datetime import timedelta

        from django.utils import timezone

        from apps.ingestion.models import SyncRun
        from apps.projects.models import Project
        from apps.submissions.models import Submission

        cutoff = timezone.now() - timedelta(days=3)
        rows = []
        for p in Project.objects.filter(is_active=True).select_related("organization").order_by("code"):
            last_run = p.sync_runs.order_by("-created_at").first()
            last_sub = (Submission.objects.filter(project=p).order_by("-ingested_at")
                        .values_list("ingested_at", flat=True).first())
            rows.append({
                "p": p, "last_run": last_run, "last_sub": last_sub,
                "stale": last_sub is None or last_sub < cutoff,
            })
        return render(request, "console/system_status.html", {
            "console_key": "system", "groups": grouped(),
            "runs": SyncRun.objects.select_related("project").order_by("-created_at")[:40],
            "rows": rows,
            "stale_count": sum(1 for r in rows if r["stale"]),
            "error_count": SyncRun.objects.filter(status=SyncRun.Status.ERROR).count(),
        })


# ---------------------------------------------------------------------------
# One-page Set up hubs — a project's whole config surface (and the admin's
# tenancy structure) on a single screen, with inline quick-add on the simple
# sections so a coordinator can e.g. add a crop without leaving the page.
# ---------------------------------------------------------------------------

# label, icon, one-line description per setup section.
SETUP_CARD_META: dict[str, tuple[str, str, str]] = {
    "forms": ("Forms", "description", "Survey forms feeding this project."),
    "field-mappings": ("Field mappings", "swap_horiz",
                       "Map raw server fields to canonical fields."),
    "event-schedule": ("Event schedule", "event",
                       "Visit timeline & day offsets that drive the status colours."),
    "crops": ("Crops", "grass", "Crops and their server name aliases."),
    "trials": ("Trials", "science", "Trial / experiment types."),
    "validation-rules": ("Validation rules", "rule",
                         "Checks that flag submissions for review."),
    "rejection-reasons": ("Rejection reasons", "block",
                         "Reasons a reviewer can decline a submission for."),
    "reference-datasets": ("Reference data", "dataset",
                          "Sampling frames, lab results & lookups to reconcile field data against."),
    "plot-election": ("Plot election", "where_to_vote",
                     "Review proposed plots and elect the trial plots."),
    "organizations": ("Institutions", "domain",
                     "Institutions (tenants) that own projects and data."),
    "regions": ("Regions", "public", "Geographic regions a Regional Coordinator oversees."),
    "countries": ("Countries", "flag", "Countries within a region."),
    "projects": ("Projects", "category", "Projects — ONA forms, ID patterns, sync."),
}

# Sections that support inline quick-add, and the minimal fields to ask for.
SETUP_QUICK: dict[str, list[str]] = {
    "crops": ["name"],
    "trials": ["name", "code"],
    "rejection-reasons": ["code", "label"],
    "regions": ["organization", "code", "name"],
    "countries": ["region", "code", "name"],
    "organizations": ["code", "name"],
}
# Quick-add sections whose new row is auto-scoped to the active project.
SETUP_PROJECT_SCOPED: set[str] = {"crops", "trials", "rejection-reasons"}
# Sections whose count is per-project (vs. global tenancy counts).
_SETUP_PROJECT_COUNTED: set[str] = {
    "forms", "event-schedule", "crops", "trials", "validation-rules", "rejection-reasons",
}


def _setup_count(key: str, uc) -> int:
    m = REGISTRY[key]
    qs = m.model.objects.all()
    if key == "field-mappings":
        return qs.filter(form__project=uc).count() if uc else qs.count()
    if key in _SETUP_PROJECT_COUNTED:
        return qs.filter(project=uc).count() if uc else qs.count()
    return qs.count()


def _setup_recent(key: str, uc) -> list[str]:
    m = REGISTRY[key]
    qs = m.model.objects.all()
    if key in SETUP_PROJECT_SCOPED and uc is not None:
        qs = qs.filter(project=uc)
    return [str(o) for o in qs.order_by("-pk")[:8]]


def _setup_quick_fields(key, data=None, errors=None):
    """Descriptors (text / select) for a section's inline quick-add form."""
    m = REGISTRY[key]
    data, errors, out = data or {}, errors or {}, []
    for fname in SETUP_QUICK.get(key, []):
        f = m.model._meta.get_field(fname)
        d = {"name": fname, "label": f.verbose_name.title(),
             "required": not f.blank, "value": data.get(fname, ""),
             "error": errors.get(fname)}
        if f.is_relation:
            rel = f.related_model
            ordering = list(rel._meta.ordering) or ["pk"]
            d["kind"] = "select"
            d["options"] = [(str(o.pk), str(o)) for o in rel.objects.order_by(*ordering)[:500]]
        else:
            d["kind"] = "text"
        out.append(d)
    return out


def build_setup_card(request, key, uc, *, count=None, url=None, new=True,
                     external=False, quick_data=None, quick_errors=None) -> dict:
    """Assemble one setup card (label, count, links, and inline quick-add fields)."""
    from django.urls import reverse

    from .registry import console_can_edit

    label, icon, desc = SETUP_CARD_META.get(key, (key, "tune", ""))
    in_registry = key in REGISTRY
    can_edit = console_can_edit(request.user, key) if in_registry else True
    scope = f"?project={uc.code}" if uc is not None else ""
    if count is None and in_registry:
        count = _setup_count(key, uc)
    if url is None and in_registry:
        url = f"{reverse('console:list', args=[key])}{scope}"
    quick = (_setup_quick_fields(key, quick_data, quick_errors)
             if key in SETUP_QUICK and can_edit else [])
    # Validation rules use the guided builder, not the generic create form.
    if key == "validation-rules" and new and can_edit:
        new_url = f"{reverse('console:rule_new', args=[])}{scope}"
    elif new and not external and can_edit and in_registry:
        new_url = f"{reverse('console:create', args=[key])}{scope}"
    else:
        new_url = None
    return {
        "key": key, "label": label, "icon": icon, "desc": desc,
        "count": count, "done": bool(count), "url": url,
        "new_url": new_url,
        "add_url": (f"{reverse('console:setup_add', args=[key])}{scope}" if quick else None),
        "quick": quick, "items": _setup_recent(key, uc) if quick else [],
    }


def _setup_sections(request, uc, layout):
    """Build visible, permission-filtered card sections from a layout spec.

    layout: list of (title, icon, desc, [(key, kwargs), ...]).
    """
    from .registry import console_key_allowed

    out = []
    for title, icon, desc, entries in layout:
        cards = []
        for key, kw in entries:
            if key in REGISTRY and not console_key_allowed(request.user, key):
                continue  # user can't view this section — hide the card
            cards.append(build_setup_card(request, key, uc, **kw))
        if cards:
            out.append({"title": title, "icon": icon, "desc": desc, "cards": cards})
    return out


def _setup_render(request, *, uc, sections, title, subtitle):
    counted = [c for s in sections for c in s["cards"] if c["count"] is not None]
    return render(request, "console/setup.html", {
        "uc": uc, "sections": sections, "console_key": "setup",
        "hub_title": title, "hub_subtitle": subtitle,
        "done_count": sum(1 for c in counted if c["done"]),
        "total_count": len(counted),
    })


class SetupHubView(ManageMixin, View):
    """A project's whole setup surface on one page — grouped cards with live
    counts, inline quick-add, and deep links to the full editors."""

    def get(self, request):
        from django.urls import reverse

        projects = _builder_projects(request)
        code = request.GET.get("project") or request.session.get("active_project")
        uc = projects.filter(code=code).first() or projects.first()
        if uc is None:
            return _setup_render(request, uc=None, sections=[],
                                 title="Set up", subtitle="")
        plot_url = f"{reverse('console:plot_election')}?project={uc.code}"
        layout = [
            ("Instrument", "description",
             "What is collected, and how raw server fields map to your dataset.",
             [("forms", {}), ("field-mappings", {"new": False})]),
            ("Schedule & crops", "event", "The visit timeline and the crops under trial.",
             [("event-schedule", {}), ("crops", {}), ("trials", {})]),
            ("Plots", "where_to_vote", "Elect which GIS-proposed plots become collection units.",
             [("plot-election", {"count": None, "url": plot_url, "external": True})]),
            ("Quality rules", "rule",
             "Automatic checks, and the reasons a reviewer can decline for.",
             [("validation-rules", {}), ("rejection-reasons", {})]),
            ("Reference data", "dataset",
             "External tables to reconcile against — sampling frames, lab results, lookups.",
             [("reference-datasets", {
                 "count": uc.reference_datasets.count(),
                 "url": f"{reverse('console:reference_datasets')}?project={uc.code}",
                 "external": True})]),
        ]
        return _setup_render(request, uc=uc, sections=_setup_sections(request, uc, layout),
                             title="Set up", subtitle=uc.name)


class AdminSetupHubView(StaffMixin, View):
    """The hub operator's tenancy structure on one page: institutions, geography
    and projects, with inline quick-add for the geography."""

    def get(self, request):
        layout = [
            ("Institutions & geography", "domain",
             "The tenants and the region → country hierarchy their projects hang off.",
             [("organizations", {}), ("regions", {}), ("countries", {})]),
            ("Projects", "category", "Every project across the platform.",
             [("projects", {"new": False})]),
        ]
        return _setup_render(request, uc=None,
                             sections=_setup_sections(request, None, layout),
                             title="Set up", subtitle="Institutions & structure")


def _apply_setup_defaults(key, obj, uc):
    """Fill the fields the quick-add form intentionally doesn't ask for."""
    if key == "rejection-reasons":
        from apps.review.models import RejectionReason
        obj.is_active = True
        if not obj.order:
            last = RejectionReason.objects.filter(project=uc).order_by("-order").first()
            obj.order = (last.order + 1) if last else 1
    elif key == "organizations":
        obj.is_active = True
        if not getattr(obj, "database_alias", ""):
            obj.database_alias = "default"


class SetupAddView(ManageMixin, View):
    """HTMX endpoint: create one row from a card's inline quick-add form and
    return the refreshed card (updated count + recent entries)."""

    def post(self, request, key):
        from .registry import console_can_edit

        if key not in SETUP_QUICK:
            raise Http404("Not a quick-add section.")
        if not console_can_edit(request.user, key):
            raise PermissionDenied("You cannot edit this section.")

        uc = None
        if key in SETUP_PROJECT_SCOPED:
            code = request.GET.get("project") or request.session.get("active_project")
            uc = _builder_projects(request).filter(code=code).first()
            if uc is None:
                raise Http404("No project in scope.")

        m = REGISTRY[key]
        form = modelform_factory(m.model, fields=SETUP_QUICK[key])(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            if key in SETUP_PROJECT_SCOPED:
                obj.project = uc
            _apply_setup_defaults(key, obj, uc)
            obj.save()
            form.save_m2m()
            card = build_setup_card(request, key, uc)
            return render(request, "console/_setup_card.html", {"c": card, "added": True})

        errors = {f: " ".join(e) for f, e in form.errors.items()}
        card = build_setup_card(request, key, uc, quick_data=request.POST,
                                quick_errors=errors)
        return render(request, "console/_setup_card.html", {"c": card, "form_error": True})
