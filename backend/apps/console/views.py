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
    """Console is staff-only (Platform Admins). RBAC for use-case data lives in
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
        from .registry import ORG_FILTER_PATHS, USECASE_FILTER_PATHS, console_can_edit

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

        path = USECASE_FILTER_PATHS.get(key)
        # Non-staff only ever see rows belonging to their own projects:
        # coordinators to the projects they coordinate, ordinary members to the
        # projects they belong to (read-only field data).
        if not is_staff:
            from apps.rbac.permissions import can_manage_access, visible_use_cases

            if can_manage_access(request.user):
                uc_ids = _coordinator_uc_ids(request.user)
            else:
                uc_ids = list(visible_use_cases(request.user).values_list("id", flat=True))
            qs = qs.filter(**{f"{path}__in": uc_ids}) if path else qs.none()

        # Workspace scope: a ?use_case=<code> filter (within what's allowed above)
        # narrows the list to one project — used by the project-workspace sidebar.
        ws_code = (request.GET.get("use_case") or "").strip()
        if ws_code and path:
            qs = qs.filter(**{f"{path}__code": ws_code})

        # Hub operator's per-institution filter (staff only).
        from apps.usecases.models import Organization

        org_path = ORG_FILTER_PATHS.get(key)
        orgs = list(Organization.objects.all()) if (org_path and is_staff) else []
        org_code = (request.GET.get("org") or "").strip()
        if org_path and org_code and is_staff:
            qs = qs.filter(**{f"{org_path}__code": org_code})

        page = Paginator(qs, 30).get_page(request.GET.get("page"))
        rows = [
            {"pk": obj.pk, "cells": [_cell(obj, f) for f in m.list_display]}
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

    return list(grantable_scopes(user)["use_cases"].values_list("id", flat=True))


def _editable_use_cases(user):
    """Projects a user may load data into: all for staff, their own for a coordinator."""
    from apps.usecases.models import UseCase

    if user.is_staff:
        return UseCase.objects.filter(is_active=True).order_by("code")
    return UseCase.objects.filter(id__in=_coordinator_uc_ids(user)).order_by("code")


class ImportCollectionUnitsView(UserPassesTestMixin, View):
    """Bulk-import a project's collection units (plots / farmers-households) from
    CSV. Staff for any project; a coordinator only for their own."""

    def test_func(self) -> bool:
        from .registry import console_can_edit

        return console_can_edit(self.request.user, "collection-units")

    def _ctx(self, request, **extra):
        ctx = {"groups": grouped(), "console_key": "collection-units",
               "use_cases": _editable_use_cases(request.user)}
        ctx.update(extra)
        return ctx

    def get(self, request):
        return render(request, "console/import_units.html", self._ctx(request))

    def post(self, request):
        from apps.fieldwork.imports import import_collection_units

        uc = _editable_use_cases(request.user).filter(pk=request.POST.get("use_case")).first()
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
    """Fetch an object — staff: any; coordinator: only within their projects."""
    if user.is_staff:
        return get_object_or_404(m.model, pk=pk)
    from .registry import USECASE_FILTER_PATHS

    path = USECASE_FILTER_PATHS.get(key)
    if path is None:
        raise Http404("Not available.")
    return get_object_or_404(m.model, pk=pk, **{f"{path}__in": _coordinator_uc_ids(user)})


def _restrict_form_to_scope(form, user):
    """Limit a form's foreign-key choices to the coordinator's own projects, so
    they can never attach a row to a project they don't coordinate."""
    if user.is_staff:
        return
    from apps.usecases.models import UseCase

    uc_ids = _coordinator_uc_ids(user)
    for field in form.fields.values():
        qs = getattr(field, "queryset", None)
        if qs is None:
            continue
        model = qs.model
        if model is UseCase:
            field.queryset = qs.filter(id__in=uc_ids)
        elif any(f.name == "use_case" for f in model._meta.fields):
            field.queryset = qs.filter(use_case_id__in=uc_ids)


def _default_use_case(form, request):
    """Pre-select a new row's Project to the workspace the coordinator is in — the
    ?use_case= carried by every sidebar console link, else the active-project
    session. Only applies when the form still offers that project as a choice."""
    field = form.fields.get("use_case")
    if field is None or getattr(field, "queryset", None) is None:
        return
    code = request.GET.get("use_case") or request.session.get("active_project")
    if not code:
        return
    uc = field.queryset.filter(code=code).first()
    if uc is not None:
        form.initial.setdefault("use_case", uc.pk)


class ConsoleFormView(UserPassesTestMixin, View):
    """Create/edit — staff for any section; a coordinator for their own
    projects' configuration & field data, scoped on both the object and the
    foreign-key choices."""

    def test_func(self) -> bool:
        from .registry import console_can_edit

        return console_can_edit(self.request.user, self.kwargs.get("key"))

    def _form_class(self, m: Managed):
        return modelform_factory(m.model, fields=m.form_fields or "__all__")

    def get(self, request, key, pk=None):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        instance = _scoped_get(request.user, m, key, pk) if pk else None
        form = self._form_class(m)(instance=instance)
        _restrict_form_to_scope(form, request.user)
        if instance is None:
            _default_use_case(form, request)
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


class PublishFormView(StaffMixin, View):
    """Platform Admin uploads an XLSForm and publishes it to a project's server,
    then (on success) the form is recorded and ready to grant + collect."""

    def _ctx(self, request, **extra):
        from apps.usecases.models import FormDefinition, UseCase

        ctx = {
            "groups": grouped(),
            "console_key": "forms",
            "use_cases": UseCase.objects.filter(is_active=True).order_by("code"),
            "roles": FormDefinition.Role.choices,
        }
        ctx.update(extra)
        return ctx

    def get(self, request):
        return render(request, "console/publish_form.html", self._ctx(request))

    def post(self, request):
        from apps.ingestion.publishing import publish_xlsform
        from apps.usecases.models import UseCase

        uc = UseCase.objects.filter(pk=request.POST.get("use_case")).first()
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


class OnboardProjectView(StaffMixin, View):
    """Onboard a new project to monitor, end to end, from inside the app:

    1. Define the use case (paste/upload a YAML config, or start from a template).
    2. It is created with its forms, mappings, schedule and rules.
    3. Hit "Sync now" on the use case to pull ONA submissions and start monitoring.

    Also surfaces ONA form discovery so you can see which forms the token can reach.
    """

    TEMPLATE_YAML = (
        "use_case:\n"
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
            "console_key": "use-cases",
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
                problems = ["Config must be a YAML mapping (use_case: ...)."]
            else:
                problems = validate_config(data)
                if not problems:
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
            return redirect("console:list", key="use-cases")

        forms, discover_error = self._discover_forms()
        return render(request, "console/onboard.html", {
            "groups": grouped(),
            "console_key": "use-cases",
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
        from apps.ingestion.backends.registry import BACKEND_CHOICES
        from apps.usecases.models import FormDefinition, Organization

        from .onboarding import CANONICAL_TARGETS

        # No network here — projects are discovered asynchronously (see
        # WizardProjectsView) so the wizard opens instantly.
        ctx = {
            "groups": grouped(),
            "console_key": "use-cases",
            "roles": FormDefinition.Role.choices,
            "backends": BACKEND_CHOICES,
            "targets": CANONICAL_TARGETS,
            "organizations": Organization.objects.filter(is_active=True),
        }
        ctx.update(extra)
        return ctx

    def get(self, request):
        return render(request, "console/wizard.html", self._ctx(request))

    def post(self, request):
        from apps.config_admin.loader import ConfigError, import_config, validate_config

        from .onboarding import build_config

        try:
            data = build_config(request.POST)
            problems = validate_config(data)
            if not problems:
                uc = import_config(data)
                messages.success(
                    request,
                    f"Project “{uc.code}” onboarded — {uc.forms.count()} form(s). "
                    f"Use “Sync now” to pull submissions.",
                )
                return redirect("console:list", key="use-cases")
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
        if request.GET.get("refresh") != "1":
            cached = cache.get(key)
            if cached is not None:
                return render(request, "console/_wizard_projects.html", cached)

        projects, error = [], None
        try:
            projects = _backend_from_request(request).discover_projects()
        except NotImplementedError:
            error = "This backend doesn't support discovery — enter details manually."
        except Exception as exc:
            error = f"Could not reach the server: {exc}"
        ctx = {"projects": projects, "discover_error": error}
        if not error:
            cache.set(key, ctx, 300)  # 5 min
        return render(request, "console/_wizard_projects.html", ctx)


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
            qs = qs.filter(use_case_id__in=_coordinator_uc_ids(request.user))
        return qs.select_related("use_case", "enumerator", "household").order_by(
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


class EnumeratorLinkView(ManageMixin, View):
    """Bulk-link Enumerators to platform accounts by phone/name.

    GET shows a dry-run preview (matches + ambiguous); POST applies the confident
    matches. After applying, the next sync populates Submission.collected_by.
    Coordinators are scoped to their own projects' enumerators.
    """

    def _scope(self, request):
        # Staff: all projects (None). Coordinator: only their own.
        return None if request.user.is_staff else _coordinator_uc_ids(request.user)

    def get(self, request):
        from apps.submissions.linking import link_enumerators

        report = link_enumerators(apply=False, use_cases=self._scope(request))
        ctx = _console_page_ctx("link-enumerators") | {
            "report": report,
            "rows": report.actionable[:300],
        }
        return render(request, "console/link_enumerators.html", ctx)

    def post(self, request):
        from apps.submissions.linking import link_enumerators

        overwrite = request.POST.get("overwrite") == "1"
        report = link_enumerators(apply=True, overwrite=overwrite, use_cases=self._scope(request))
        if report.matched:
            messages.success(
                request, f"Linked {report.matched} enumerator(s) to accounts. "
                f"collected_by will populate on the next sync."
            )
        else:
            messages.info(request, "No confident matches to link.")
        if report.ambiguous:
            messages.warning(
                request, f"{report.ambiguous} enumerator(s) matched more than one "
                "account — link those manually under Enumerators."
            )
        return redirect("console:link_enumerators")


def _csv_list(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


class FormMappingsView(StaffMixin, View):
    """Inline editor for one form's field mappings (add / edit / delete rows)."""

    def _form(self, pk):
        from apps.usecases.models import FormDefinition

        return get_object_or_404(FormDefinition.objects.select_related("use_case"), pk=pk)

    def _ctx(self, form):
        from apps.usecases.models import FieldMapping

        return _console_page_ctx("forms") | {
            "form": form,
            "mappings": form.mappings.all().order_by("order", "target_field"),
            "transforms": FieldMapping.Transform.choices,
        }

    def get(self, request, pk):
        return render(request, "console/form_mappings.html", self._ctx(self._form(pk)))

    def post(self, request, pk):
        from apps.usecases.models import FieldMapping

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

        from apps.usecases.models import FieldMapping

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
            "available_units": CollectionUnit.objects.filter(use_case=job.use_case)
            .exclude(id__in=taken).order_by("code"),
            "enumerators": project_enumerators(job.use_case),
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
            units = CollectionUnit.objects.filter(use_case=job.use_case).exclude(
                assignments__job=job)
            UnitAssignment.objects.bulk_create(
                [UnitAssignment(job=job, unit=u, enumerator=enum) for u in units])
            if enum:
                job.assigned_to.add(enum)
            messages.success(request, f"Assigned {len(units)} unit(s).")
        else:  # add one
            unit = CollectionUnit.objects.filter(
                use_case=job.use_case, pk=request.POST.get("unit")).first()
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

        use_cases = _editable_use_cases(request.user)
        uc = use_cases.filter(code=request.GET.get("use_case")).first() or use_cases.first()
        ctx = {"use_cases": use_cases, "uc": uc, "rows": [], "progress": None,
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

        use_cases = _editable_use_cases(request.user)
        uc = get_object_or_404(use_cases, code=request.POST.get("use_case"))
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
        return redirect(f"{reverse('console:plot_election')}?use_case={uc.code}")


class PlotElectionView(ManageMixin, View):
    """Elect one candidate plot for a single trial (or flag no-valid-plot)."""

    def _uc(self, request, code):
        return get_object_or_404(_editable_use_cases(request.user), code=code)

    def get(self, request, code, trial_key):
        from apps.dashboards.charts import candidate_plots_map_html
        from apps.fieldwork.models import CandidatePlot

        uc = self._uc(request, code)
        cands = list(CandidatePlot.objects.filter(use_case=uc, trial_key=trial_key))
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
        queue_url = f"{reverse('console:plot_election')}?use_case={uc.code}"
        elect_url = redirect("console:plot_elect", code=uc.code, trial_key=trial_key)
        if request.POST.get("action") == "capture_anchor":
            elected = CandidatePlot.objects.filter(
                use_case=uc, trial_key=trial_key, status=CandidatePlot.Status.ELECTED
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
            use_case=uc, trial_key=trial_key, pk=request.POST.get("candidate")).first()
        if chosen is None:
            messages.error(request, "Pick a candidate to elect.")
            return redirect("console:plot_elect", code=uc.code, trial_key=trial_key)
        if chosen.role == CandidatePlot.Role.BACKUP and not note:
            messages.error(request, "A reason is required when electing the backup plot.")
            return redirect("console:plot_elect", code=uc.code, trial_key=trial_key)
        elect_candidate(request.user, chosen, note=note)
        messages.success(request, f"Trial {trial_key}: elected plot {chosen.candidate_ref}.")
        return redirect(queue_url)
