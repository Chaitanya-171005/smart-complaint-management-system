from django.contrib import admin

from workflow.models import ComplaintHistory


@admin.register(ComplaintHistory)
class ComplaintHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "complaint_ref",
        "event_type",
        "actor_kind",
        "previous_state",
        "new_state",
        "occurred_at",
    )
    list_filter = ("event_type", "actor_kind")
    search_fields = ("complaint_ref",)
    ordering = ("occurred_at", "pk")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
