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


class ConsoleListView(StaffMixin, View):
    def get(self, request, key):
        m = _managed(key)
        qs = m.model._default_manager.all()
        if m.ordering:
            qs = qs.order_by(*m.ordering)
        q = (request.GET.get("q") or "").strip()
        if q and m.search_fields:
            cond = Q()
            for f in m.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
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
        }
        return render(request, "console/list.html", ctx)


class ConsoleFormView(StaffMixin, View):
    def _form_class(self, m: Managed):
        return modelform_factory(m.model, fields=m.form_fields or "__all__")

    def get(self, request, key, pk=None):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        instance = get_object_or_404(m.model, pk=pk) if pk else None
        form = self._form_class(m)(instance=instance)
        return render(request, "console/form.html", _base_ctx(m) | {"form": form, "instance": instance})

    def post(self, request, key, pk=None):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        instance = get_object_or_404(m.model, pk=pk) if pk else None
        form = self._form_class(m)(request.POST, instance=instance)
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

    def _projects(self, request):
        try:
            return _backend_from_request(request).discover_projects(), None
        except NotImplementedError:
            return [], "This backend doesn't support project discovery — enter details manually."
        except Exception as exc:
            return [], f"Could not reach the server: {exc}"

    def _ctx(self, request, **extra):
        from apps.ingestion.backends.registry import BACKEND_CHOICES
        from apps.usecases.models import FormDefinition

        from .onboarding import CANONICAL_TARGETS

        projects, discover_error = self._projects(request)
        ctx = {
            "groups": grouped(),
            "console_key": "use-cases",
            "projects": projects,
            "discover_error": discover_error,
            "roles": FormDefinition.Role.choices,
            "backends": BACKEND_CHOICES,
            "targets": CANONICAL_TARGETS,
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


class ConsoleDeleteView(StaffMixin, View):
    def get(self, request, key, pk):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        obj = get_object_or_404(m.model, pk=pk)
        return render(request, "console/delete.html", _base_ctx(m) | {"obj": obj})

    def post(self, request, key, pk):
        m = _managed(key)
        if m.readonly:
            raise PermissionDenied("This section is read-only.")
        obj = get_object_or_404(m.model, pk=pk)
        label = str(obj)
        obj.delete()
        messages.success(request, f"Deleted “{label}”.")
        return redirect("console:list", key=key)


class WriteBackQueueView(StaffMixin, View):
    """Operational queue: submissions whose reviewer edits still need to reach the
    source server. Retry one or flush all PENDING/FAILED."""

    def _queue(self):
        from apps.submissions.models import Submission

        status = Submission.WriteBackStatus
        return (
            Submission.objects.filter(writeback_status__in=[status.PENDING, status.FAILED])
            .select_related("use_case", "enumerator", "household")
            .order_by("writeback_status", "-updated_at")
        )

    def get(self, request):
        from django.conf import settings

        qs = self._queue()
        ctx = _console_page_ctx("writeback") | {
            "rows": qs[:300],
            "pending": qs.filter(writeback_status="PENDING").count(),
            "failed": qs.filter(writeback_status="FAILED").count(),
            "enabled": getattr(settings, "WRITEBACK_ENABLED", False),
        }
        return render(request, "console/writeback.html", ctx)

    def post(self, request):
        from apps.ingestion.tasks import writeback_submission_task

        action = request.POST.get("action")
        if action == "flush":
            ids = list(self._queue().values_list("pk", flat=True))
            for pk in ids:
                writeback_submission_task.delay(str(pk))
            messages.success(request, f"Queued write-back for {len(ids)} submission(s).")
        elif action == "retry":
            pk = request.POST.get("submission_id")
            if pk:
                writeback_submission_task.delay(str(pk))
                messages.success(request, "Write-back retried.")
        return redirect("console:writeback")


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
