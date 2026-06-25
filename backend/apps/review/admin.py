from __future__ import annotations

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Review, ReviewActionLog


class ReviewActionLogInline(TabularInline):
    model = ReviewActionLog
    extra = 0
    can_delete = False
    readonly_fields = [
        "actor", "action", "from_state", "to_state", "field_key",
        "old_value", "new_value", "note", "created_at",
    ]

    def has_add_permission(self, request, obj=None):  # audit log is append-only
        return False


@admin.register(Review)
class ReviewAdmin(ModelAdmin):
    list_display = ["submission", "state", "assigned_to", "qc_signed_by", "updated_at"]
    list_filter = ["state"]
    search_fields = ["submission__ona_uuid"]
    readonly_fields = ["submission", "qc_signed_by", "qc_signed_at"]

    def get_inlines(self, request, obj):
        return [ReviewActionLogInline] if obj else []


@admin.register(ReviewActionLog)
class ReviewActionLogAdmin(ModelAdmin):
    list_display = ["submission", "actor", "action", "from_state", "to_state", "created_at"]
    list_filter = ["action"]
    readonly_fields = [f.name for f in ReviewActionLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
