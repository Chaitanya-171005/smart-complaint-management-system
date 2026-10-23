"""Shared server-side authorization checks (B04: REQ-ACC-01, REQ-SEC-02, BR-01).

Every check reads the user's CURRENT role and department from the database on each
request (Django loads ``request.user`` per request and nothing here caches a role), so
a role or membership change applies on the next request. None of this depends on what
the UI shows: call the checks in the view/service before reading or changing data.

Who may act is decided here. Whether a state transition is valid (SRS state model) is
the lifecycle's job (F4); call both.

Complaint-like objects: the checks read ``owner`` (User or None for anonymous
complaints), ``department`` and ``assignee`` (User or None). Either the related object
or the ``<name>_id`` value may be present. See docs/AUTHORIZATION.md.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import SecurityEvent, User
from .security_log import record_event

Role = User.Role


# --- helpers -------------------------------------------------------------------


def _active(user):
    return bool(user is not None and user.is_authenticated and user.is_active)


def has_role(user, *roles):
    return _active(user) and user.role in roles


def _as_id(value):
    """Accept a model instance, a primary key or None."""
    if value is None:
        return None
    return getattr(value, "pk", value)


def _fk_id(obj, name):
    value = getattr(obj, f"{name}_id", None)
    if value is not None:
        return value
    return _as_id(getattr(obj, name, None))


def _in_own_department(user, obj):
    dept = user.department_id
    return dept is not None and dept == _fk_id(obj, "department")


def _is_assignee(user, obj):
    assignee = _fk_id(obj, "assignee")
    return assignee is not None and assignee == user.pk


def _is_owner(user, obj):
    owner = _fk_id(obj, "owner")
    return owner is not None and owner == user.pk


# --- checks: complaints --------------------------------------------------------


def can_view_complaint(user, complaint):
    """Read a complaint: detail, history or evidence (REQ-ACC-01, REQ-SEC-05)."""
    if not _active(user):
        return False
    if user.role == Role.ADMIN:
        # Read-only campus view. Open decision: confirm Admin may read complaint details.
        return True
    if user.role == Role.COMPLAINANT:
        return _is_owner(user, complaint)
    if user.role in (Role.STAFF, Role.HEAD):
        return _in_own_department(user, complaint)
    return False


def can_view_evidence(user, complaint):
    """Evidence follows the parent complaint (REQ-SEC-05)."""
    return can_view_complaint(user, complaint)


def can_progress_complaint(user, complaint):
    """Move work to IN_PROGRESS: assigned Staff, or the Head of the department."""
    if has_role(user, Role.STAFF):
        return _in_own_department(user, complaint) and _is_assignee(user, complaint)
    if has_role(user, Role.HEAD):
        return _in_own_department(user, complaint)
    return False


def can_resolve_complaint(user, complaint):
    """Mark RESOLVED: only the Staff member the work is assigned to (BR-01)."""
    return (
        has_role(user, Role.STAFF)
        and _in_own_department(user, complaint)
        and _is_assignee(user, complaint)
    )


def can_reject_complaint(user, complaint):
    """Reject: Admin, the department Head, or the assigned Staff (SRS 4.3)."""
    if has_role(user, Role.ADMIN):
        return True
    if has_role(user, Role.HEAD):
        return _in_own_department(user, complaint)
    if has_role(user, Role.STAFF):
        return _in_own_department(user, complaint) and _is_assignee(user, complaint)
    return False


def can_allocate_complaint(user, complaint, assignee=None):
    """Assign or reassign: the Head of the complaint's own department.

    If ``assignee`` is given it must be active Staff of the same department.
    """
    if not (has_role(user, Role.HEAD) and _in_own_department(user, complaint)):
        return False
    if assignee is None:
        return True
    return (
        _active(assignee)
        and assignee.role == Role.STAFF
        and assignee.department_id is not None
        and assignee.department_id == user.department_id
    )


def can_confirm_resolution(user, complaint):
    """Confirm or reject a resolution: the originating Complainant only.

    Anonymous reporters (no account) are handled by the reference flow, not here.
    """
    return has_role(user, Role.COMPLAINANT) and _is_owner(user, complaint)


# --- checks: departments, reports, administration -------------------------------


def can_view_department_queue(user, department):
    if not _active(user):
        return False
    if user.role == Role.ADMIN:
        return True
    if user.role in (Role.STAFF, Role.HEAD):
        dept = _as_id(department)
        return user.department_id is not None and user.department_id == dept
    return False


def can_view_report(user, department=None):
    """Campus-wide report (``department`` None): Admin. Department report: its Head."""
    if has_role(user, Role.ADMIN):
        return True
    if has_role(user, Role.HEAD):
        dept = _as_id(department)
        return dept is not None and user.department_id == dept
    return False


def can_manage_configuration(user):
    return has_role(user, Role.ADMIN)


def can_manage_users(user):
    return has_role(user, Role.ADMIN)


# --- list scoping ----------------------------------------------------------------


def scope_complaints(user, queryset, *, owner_field="owner", department_field="department"):
    """Limit a complaint queryset to what ``user`` may see (lists, queues, filters)."""
    if not _active(user):
        return queryset.none()
    if user.role == Role.ADMIN:
        return queryset
    if user.role == Role.COMPLAINANT:
        return queryset.filter(**{owner_field: user.pk})
    if user.role in (Role.STAFF, Role.HEAD) and user.department_id is not None:
        return queryset.filter(**{department_field: user.department_id})
    return queryset.none()


# --- enforcement in views ----------------------------------------------------------


def _refuse(user, action, obj=None):
    """Record the refusal (REQ-SEC-08). Never stores request data or secrets."""
    target = ""
    if obj is not None:
        target = f"{type(obj).__name__}#{getattr(obj, 'pk', '')}"
    known = user if (user is not None and user.is_authenticated) else None
    record_event(
        SecurityEvent.EventType.AUTHORIZATION_REFUSED,
        user=known,
        identifier=getattr(known, "email", ""),
        detail=f"{action} {target}".strip(),
    )


def require_permission(check, user, *args):
    """Raise PermissionDenied (403) unless ``check(user, *args)`` passes.

    For actions on something the user may already see. Call before changing any data,
    so a refused action leaves state and history untouched.
    """
    if check(user, *args):
        return
    _refuse(user, check.__name__, args[0] if args else None)
    raise PermissionDenied


def authorize_or_404(check, user, obj, *args):
    """Return ``obj`` if ``check(user, obj, *args)`` passes, otherwise raise Http404.

    A missing object and an object the user may not see give the same 404, so the
    response does not reveal that a record exists (REQ-SEC-06).
    """
    if obj is None:
        raise Http404
    if check(user, obj, *args):
        return obj
    _refuse(user, check.__name__, obj)
    raise Http404


def _enforce_role(request, roles):
    """Return a redirect for anonymous users, raise 403 for the wrong role, else None."""
    user = request.user
    if not _active(user):
        return redirect_to_login(request.get_full_path())
    if user.role not in roles:
        _refuse(user, "role_required:" + "/".join(roles))
        raise PermissionDenied
    return None


def role_required(*roles):
    """Decorator: sign-in required and the user's current role must be one of ``roles``."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            denied = _enforce_role(request, roles)
            if denied is not None:
                return denied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


class RoleRequiredMixin:
    """Class-based view version of ``role_required``. Set ``allowed_roles``."""

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        denied = _enforce_role(request, self.allowed_roles)
        if denied is not None:
            return denied
        return super().dispatch(request, *args, **kwargs)
