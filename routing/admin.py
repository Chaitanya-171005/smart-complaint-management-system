from django.contrib import admin

from accounts.models import User

from .models import (
    ConfigurationAuditEvent,
)


class AdministratorOnlyAdmin(admin.ModelAdmin):
    """The Django-admin interface is never a role-permission bypass."""

    def _is_scms_admin(self, request):
        return bool(
            request.user.is_authenticated and request.user.role == User.Role.ADMIN
        )

    def has_module_permission(self, request):
        return self._is_scms_admin(request)

    def has_view_permission(self, request, obj=None):
        return self._is_scms_admin(request)

    def has_add_permission(self, request):
        return self._is_scms_admin(request)

    def has_change_permission(self, request, obj=None):
        return self._is_scms_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfigurationAuditEvent)
class ConfigurationAuditEventAdmin(AdministratorOnlyAdmin):
    list_display = ("created_at", "actor", "entity_type", "entity_id", "action")
    readonly_fields = (
        "actor",
        "entity_type",
        "entity_id",
        "action",
        "old_values",
        "new_values",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
