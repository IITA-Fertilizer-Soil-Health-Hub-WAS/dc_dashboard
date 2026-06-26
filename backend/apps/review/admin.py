from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin

from .models import Review, ReviewActionLog


@admin.register(Review)
class ReviewAdmin(ModelAdmin):
    list_display = ["submission", "state", "endorsed_by", "qc_signed_by", "updated_at"]
    list_filter = ["state"]
    search_fields = ["submission__ona_uuid"]
    # ReviewActionLog has no FK to Review (it points at Submission, and Review is
    # a OneToOne on Submission), so it cannot be an inline. Show the trail as a
    # read-only rendering of the submission's actions instead.
    readonly_fields = [
        "submission", "endorsed_by", "endorsed_at", "qc_signed_by", "qc_signed_at",
        "audit_trail",
    ]
    fields = [
        "submission", "state", "assigned_to", "endorsed_by", "endorsed_at",
        "qc_signed_by", "qc_signed_at", "audit_trail",
    ]

    @admin.display(description="Audit trail")
    def audit_trail(self, obj):
        if obj is None or obj.pk is None:
            return "—"
        logs = obj.submission.actions.select_related("actor").order_by("created_at")
        rows = [
            (
                log.created_at.strftime("%Y-%m-%d %H:%M"),
                log.action,
                log.from_state or "",
                log.to_state or "",
                getattr(log.actor, "email", "") or "system",
                log.note or "",
            )
            for log in logs
        ]
        if not rows:
            return "No actions yet."
        return format_html(
            "<table style='border-collapse:collapse;'>"
            "<tr><th style='text-align:left;padding:2px 8px;'>When</th>"
            "<th style='text-align:left;padding:2px 8px;'>Action</th>"
            "<th style='text-align:left;padding:2px 8px;'>From→To</th>"
            "<th style='text-align:left;padding:2px 8px;'>Actor</th>"
            "<th style='text-align:left;padding:2px 8px;'>Note</th></tr>{}</table>",
            format_html_join(
                "",
                "<tr><td style='padding:2px 8px;'>{}</td><td style='padding:2px 8px;'>{}</td>"
                "<td style='padding:2px 8px;'>{}→{}</td><td style='padding:2px 8px;'>{}</td>"
                "<td style='padding:2px 8px;'>{}</td></tr>",
                rows,
            ),
        )


@admin.register(ReviewActionLog)
class ReviewActionLogAdmin(ModelAdmin):
    list_display = ["submission", "actor", "action", "from_state", "to_state", "created_at"]
    list_filter = ["action"]
    readonly_fields = [f.name for f in ReviewActionLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
