from django.contrib import admin

from routing.models import EscalationRun


@admin.register(EscalationRun)
class EscalationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "started_at", "finished_at", "status", "examined", "escalated", "skipped", "failed")
    readonly_fields = ("started_at", "finished_at", "status", "examined", "escalated", "skipped", "failed", "error")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
