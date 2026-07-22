"""Read API — the platform's data backbone for downstream consumers (dashboards,
GIS, researchers). Every endpoint is scoped to the caller's visible projects
(RBAC), paginated, and available with either a session or an API token, so
Fieldbase becomes the source of truth instead of raw ODK exports.
"""
from __future__ import annotations

from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rbac.permissions import visible_projects
from apps.submissions.models import Submission
from apps.validation.models import ValidationFlag


def _project_or_404(request, code):
    from rest_framework.exceptions import NotFound

    p = visible_projects(request.user).filter(code=code).first()
    if p is None:
        raise NotFound("No such project (or you can't access it).")
    return p


class ProjectListAPI(APIView):
    """GET /api/v1/projects/ — projects the caller can see, with headline counts."""

    def get(self, request):
        from django.db.models import Count, Q

        rows = (
            visible_projects(request.user).select_related("organization")
            .annotate(
                n_submissions=Count("submissions", distinct=True),
                n_open_issues=Count("submissions__flags", distinct=True,
                                    filter=Q(submissions__flags__status="OPEN")),
            ).order_by("code")
        )
        return Response([{
            "code": p.code, "name": p.name,
            "organization": p.organization.code if p.organization_id else None,
            "country": p.country.name if p.country_id else None,
            "submissions": p.n_submissions, "open_issues": p.n_open_issues,
            "links": {
                "submissions": request.build_absolute_uri(f"/api/v1/projects/{p.code}/submissions/"),
                "flags": request.build_absolute_uri(f"/api/v1/projects/{p.code}/flags/"),
                "kpis": request.build_absolute_uri(f"/api/v1/projects/{p.code}/kpis/"),
            },
        } for p in rows])


class SubmissionSerializer(serializers.ModelSerializer):
    form = serializers.SerializerMethodField()
    enumerator = serializers.SerializerMethodField()
    collection_unit = serializers.SerializerMethodField()
    review_state = serializers.SerializerMethodField()
    values = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ["ona_uuid", "form", "event_key", "event_date", "lat", "lon",
                  "enumerator", "collection_unit", "review_state", "ingested_at", "values"]

    def get_form(self, o):
        return o.form.title or o.form.server_ref if o.form_id else None

    def get_enumerator(self, o):
        return o.enumerator.enid if o.enumerator_id else None

    def get_collection_unit(self, o):
        return o.collection_unit.code if o.collection_unit_id else None

    def get_review_state(self, o):
        return getattr(getattr(o, "review", None), "state", None)

    def get_values(self, o):
        if not self.context.get("with_values"):
            return None
        return {v.field_key: v.current_value for v in o.values.all()}


class SubmissionListAPI(ListAPIView):
    """GET /api/v1/projects/<code>/submissions/ — paginated authoritative data.
    Filters: ?form=<server_id>&event=<key>&since=<YYYY-MM-DD>&values=1"""

    serializer_class = SubmissionSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["with_values"] = self.request.query_params.get("values") in ("1", "true")
        return ctx

    def get_queryset(self):
        p = _project_or_404(self.request, self.kwargs["code"])
        qs = (Submission.objects.filter(project=p)
              .select_related("form", "enumerator", "collection_unit", "review")
              .order_by("-event_date", "-ingested_at"))
        q = self.request.query_params
        if q.get("form"):
            qs = qs.filter(form__server_form_id=q["form"])
        if q.get("event"):
            qs = qs.filter(event_key=q["event"])
        if q.get("since"):
            qs = qs.filter(event_date__gte=q["since"])
        if q.get("values") in ("1", "true"):
            qs = qs.prefetch_related("values")
        return qs


class FlagSerializer(serializers.ModelSerializer):
    submission = serializers.CharField(source="submission.ona_uuid", read_only=True)
    rule = serializers.CharField(source="rule.code", read_only=True)

    class Meta:
        model = ValidationFlag
        fields = ["submission", "rule", "field_key", "message", "severity",
                  "status", "created_at"]


class FlagListAPI(ListAPIView):
    """GET /api/v1/projects/<code>/flags/ — validation flags (default: open)."""

    serializer_class = FlagSerializer

    def get_queryset(self):
        p = _project_or_404(self.request, self.kwargs["code"])
        qs = (ValidationFlag.objects.filter(submission__project=p)
              .select_related("submission", "rule").order_by("-created_at"))
        status = self.request.query_params.get("status", "OPEN").upper()
        if status != "ALL":
            qs = qs.filter(status=status)
        return qs


class KpiAPI(APIView):
    """GET /api/v1/projects/<code>/kpis/ — the project's M&E summary."""

    def get(self, request, code):
        p = _project_or_404(request, code)
        try:
            from apps.kpi.builder import project_summary
            data = project_summary(p)
        except Exception:
            from django.db.models import Q
            data = {
                "submissions": Submission.objects.filter(project=p).count(),
                "open_issues": ValidationFlag.objects.filter(
                    submission__project=p, status="OPEN").count(),
            }
        return Response({"project": p.code, **data})
