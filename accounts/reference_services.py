"""Administrator reference-data management: departments and locations (B05, REQ-ADM-01).

Rules: only the Administrator may change reference data; records are deactivated, never
deleted (BR-05); inactive records stay on existing complaints and users but are not offered
to new operations; every change is audited in the same transaction (REQ-ADM-04, B29).
"""

from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower

from .config_audit import record_change
from .models import ConfigAuditEvent, Department, Location
from .permissions import can_manage_configuration, require_permission

Action = ConfigAuditEvent.Action


def admin_action(fn):
    """Administrator only, then all-or-nothing with its audit record.

    The permission check runs before the transaction opens: a refusal is logged as a
    security event, and that log entry must not be rolled back with the refused change.
    """

    @wraps(fn)
    def wrapper(actor, *args, **kwargs):
        require_permission(can_manage_configuration, actor)
        with transaction.atomic():
            return fn(actor, *args, **kwargs)

    return wrapper


# --- what new operations may choose ---------------------------------------------------


def active_departments():
    """Departments offered to new operations (routing, membership, filters)."""
    return Department.objects.filter(active=True)


def active_locations():
    """Locations offered to new complaints."""
    return Location.objects.filter(active=True)


# --- helpers ---------------------------------------------------------------------------


def _text(value, label, max_length, *, required=True):
    value = (value or "").strip()
    if required and not value:
        raise ValidationError({label: "This field is required."})
    if len(value) > max_length:
        raise ValidationError({label: f"Use at most {max_length} characters."})
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError({label: "Use a single line without control characters."})
    return value


def _department_values(d):
    return {"name": d.name, "active": d.active}


def _location_values(loc):
    return {
        "code": loc.code, "block": loc.block, "floor": loc.floor,
        "room_area": loc.room_area, "active": loc.active,
    }


def _save(instance, error_field, message):
    try:
        with transaction.atomic():
            instance.save()
    except IntegrityError as exc:
        raise ValidationError({error_field: message}) from exc


# --- departments -----------------------------------------------------------------------


@admin_action
def create_department(actor, name):
    name = _text(name, "name", 50)
    if Department.objects.annotate(n=Lower("name")).filter(n=name.lower()).exists():
        raise ValidationError({"name": "A department with this name already exists."})
    dept = Department(name=name, active=True)
    _save(dept, "name", "A department with this name already exists.")
    record_change(actor=actor, entity_type="department", entity_id=dept.pk,
                  action=Action.CREATE, new=_department_values(dept))
    return dept


@admin_action
def rename_department(actor, department, name):
    department = Department.objects.select_for_update().get(pk=department.pk)
    name = _text(name, "name", 50)
    clash = (
        Department.objects.annotate(n=Lower("name")).filter(n=name.lower())
        .exclude(pk=department.pk).exists()
    )
    if clash:
        raise ValidationError({"name": "A department with this name already exists."})
    old = _department_values(department)
    if name == department.name:
        return department
    department.name = name
    _save(department, "name", "A department with this name already exists.")
    record_change(actor=actor, entity_type="department", entity_id=department.pk,
                  action=Action.UPDATE, old=old, new=_department_values(department))
    return department


@admin_action
def set_department_active(actor, department, active):
    """Deactivate or reactivate. Existing users and complaints keep their reference."""
    department = Department.objects.select_for_update().get(pk=department.pk)
    if department.active == bool(active):
        return department
    old = _department_values(department)
    department.active = bool(active)
    department.save(update_fields=["active"])
    record_change(actor=actor, entity_type="department", entity_id=department.pk,
                  action=Action.REACTIVATE if active else Action.DEACTIVATE,
                  old=old, new=_department_values(department))
    return department


# --- locations -------------------------------------------------------------------------


def _location_code(value):
    code = Location.normalize_code(_text(value, "code", 100))
    if not Location.is_valid_code(code):
        raise ValidationError(
            {"code": "Use only letters, digits, '.', '_' and '-' (no spaces) in a location code."}
        )
    return code


def _location_fields(code, block, floor, room_area):
    return {
        "code": _location_code(code),
        "block": _text(block, "block", 20),
        "floor": _text(floor, "floor", 10, required=False),
        "room_area": _text(room_area, "room_area", 30),
    }


def _check_location_unique(fields, exclude_pk=None):
    qs = Location.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.filter(code=fields["code"]).exists():
        raise ValidationError({"code": "This location code is already used."})
    place = qs.annotate(b=Lower("block"), f=Lower("floor"), r=Lower("room_area")).filter(
        b=fields["block"].lower(), f=fields["floor"].lower(), r=fields["room_area"].lower()
    )
    if place.exists():
        raise ValidationError({"room_area": "This block, floor and room/area already exists."})


@admin_action
def create_location(actor, *, code, block, floor, room_area):
    fields = _location_fields(code, block, floor, room_area)
    _check_location_unique(fields)
    loc = Location(active=True, **fields)
    _save(loc, "code", "This location already exists.")
    record_change(actor=actor, entity_type="location", entity_id=loc.pk,
                  action=Action.CREATE, new=_location_values(loc))
    return loc


@admin_action
def update_location(actor, location, *, block, floor, room_area):
    """Edit the descriptive fields. The code is the stable key and is never changed here."""
    location = Location.objects.select_for_update().get(pk=location.pk)
    fields = _location_fields(location.code, block, floor, room_area)
    _check_location_unique(fields, exclude_pk=location.pk)
    old = _location_values(location)
    for key in ("block", "floor", "room_area"):
        setattr(location, key, fields[key])
    if _location_values(location) == old:
        return location
    _save(location, "room_area", "This block, floor and room/area already exists.")
    record_change(actor=actor, entity_type="location", entity_id=location.pk,
                  action=Action.UPDATE, old=old, new=_location_values(location))
    return location


@admin_action
def set_location_active(actor, location, active):
    location = Location.objects.select_for_update().get(pk=location.pk)
    if location.active == bool(active):
        return location
    old = _location_values(location)
    location.active = bool(active)
    location.save(update_fields=["active"])
    record_change(actor=actor, entity_type="location", entity_id=location.pk,
                  action=Action.REACTIVATE if active else Action.DEACTIVATE,
                  old=old, new=_location_values(location))
    return location
