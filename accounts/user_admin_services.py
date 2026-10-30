"""Administrator management of users, roles and department membership (B06, REQ-ADM-02, BR-04).

Rules enforced here, on the server, whatever the screen shows:
- only an Administrator may do this (checked against the database, not the session);
- nobody changes their own role or membership;
- the last active Administrator can never be removed;
- Staff and Head need an active department; Complainants and Administrators have none;
- a refused or invalid change leaves roles, memberships and permissions exactly as they were;
- every applied change is a configuration-audit record AND a security event (REQ-ADM-04).
Permissions are read from the database on every request (accounts.permissions), so an
applied change takes effect on the user's next protected request.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .config_audit import record_change
from .models import ConfigAuditEvent, Department, SecurityEvent, User
from .permissions import can_manage_configuration, require_permission
from .security_log import record_event

Role = User.Role
DEPARTMENT_ROLES = (Role.STAFF, Role.HEAD)


class _Refused(Exception):
    """Raised inside the transaction; logged and converted after it has rolled back."""


def _refuse(actor, target, reason):
    raise _Refused(reason)


def _log_refusal(actor, target, reason):
    """Record the refused attempt outside any transaction, so the record is kept."""
    record_event(
        SecurityEvent.EventType.ROLE_CHANGE_REFUSED,
        user=actor if getattr(actor, "is_authenticated", False) else None,
        identifier=getattr(actor, "email", ""),
        detail=f"{reason} (target user #{getattr(target, 'pk', '?')})",
    )


def _department_id(department):
    return None if department is None else getattr(department, "pk", department)


def _values(user):
    return {"role": user.role, "department": user.department_id}


def _validate(actor, target, role, department_id):
    if role not in Role.values:
        _refuse(actor, target, "Choose a valid role.")
    if target.pk == actor.pk:
        _refuse(actor, target, "You cannot change your own role or membership.")
    if role in DEPARTMENT_ROLES:
        if department_id is None:
            _refuse(actor, target, "Staff and Department Heads need a department.")
        dept = Department.objects.filter(pk=department_id).first()
        if dept is None:
            _refuse(actor, target, "Choose a valid department.")
        # Only active departments can be newly assigned; keeping the current one is fine.
        if not dept.active and target.department_id != dept.pk:
            _refuse(actor, target, "Choose an active department.")
    elif department_id is not None:
        _refuse(actor, target, "Only Staff and Department Heads belong to a department.")


def _ensure_an_admin_remains(actor, target, role):
    """After the change at least one active Administrator must exist (REQ-ADM-02)."""
    others = User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=target.pk).count()
    stays_admin = 1 if role == Role.ADMIN and target.is_active else 0
    if others + stays_admin < 1:
        _refuse(actor, target, "At least one active Administrator must remain.")


def set_role_and_membership(actor, target, *, role, department=None):
    """Set a user's role and department membership together, atomically.

    ``department`` is a Department, its pk, or None. Returns the updated user.
    """
    # The permission check runs before the transaction opens so that a refusal's security
    # event is not rolled back with it. It also uses the actor's CURRENT database row.
    fresh_actor = User.objects.filter(pk=getattr(actor, "pk", None)).first() or actor
    require_permission(can_manage_configuration, fresh_actor)
    department_id = _department_id(department)
    try:
        with transaction.atomic():
            # Lock both rows in a fixed order so two simultaneous changes cannot interleave.
            locked = {
                u.pk: u
                for u in User.objects.select_for_update().filter(pk__in=[fresh_actor.pk, target.pk]).order_by("pk")
            }
            actor_row, target_row = locked[fresh_actor.pk], locked[target.pk]
            if not can_manage_configuration(actor_row):  # demoted since the first check
                raise PermissionDenied
            _validate(actor_row, target_row, role, department_id)
            _ensure_an_admin_remains(actor_row, target_row, role)
            old = _values(target_row)
            if old == {"role": role, "department": department_id}:
                return target_row
            target_row.role = role
            target_row.department_id = department_id
            target_row.save(update_fields=["role", "department"])
            new = _values(target_row)
            record_change(
                actor=actor_row, entity_type="user", entity_id=target_row.pk,
                action=ConfigAuditEvent.Action.UPDATE, old=old, new=new,
            )
            record_event(
                SecurityEvent.EventType.ROLE_CHANGED,
                user=actor_row,
                identifier=actor_row.email,
                detail=(
                    f"user #{target_row.pk}: role {old['role']}->{new['role']}, "
                    f"department {old['department']}->{new['department']}"
                ),
            )
            return target_row
    except _Refused as refusal:
        _log_refusal(fresh_actor, target, str(refusal))
        raise ValidationError({"__all__": str(refusal)}) from refusal
    except PermissionDenied:
        # Lost the Administrator role between the check and the lock: refused, logged once.
        record_event(
            SecurityEvent.EventType.AUTHORIZATION_REFUSED,
            user=fresh_actor, identifier=fresh_actor.email,
            detail="set_role_and_membership: no longer an Administrator",
        )
        raise
