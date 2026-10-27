"""Admin-only configuration operations for B17.

Views and management commands must use these functions instead of writing models
directly. That keeps authorization, validation and REQ-ADM-04 auditing together.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.permissions import can_manage_configuration, require_permission

from .models import (
    Category,
    ConfigurationAuditEvent,
    EscalationPolicy,
    Priority,
    RoutingRule,
    SLAConfiguration,
)


class ConfigurationError(ValidationError):
    """A safe validation failure for an administrator to correct."""


UNSET = object()


def _require_admin(actor):
    require_permission(can_manage_configuration, actor)


def _snapshot(obj, fields):
    result = {}
    for field in fields:
        result[field] = getattr(obj, f"{field}_id", getattr(obj, field))
    return result


def _audit(actor, obj, action, old_values=None, new_values=None):
    return ConfigurationAuditEvent.objects.create(
        actor=actor,
        entity_type=type(obj).__name__,
        entity_id=obj.pk,
        action=action,
        old_values=old_values or {},
        new_values=new_values or {},
    )


def _validate(instance):
    try:
        instance.full_clean()
    except ValidationError as exc:
        detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        raise ConfigurationError(detail) from exc


def _normalise_location(location_code):
    return (location_code or "").strip().upper()


def _positive_int(value, field_name):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            {field_name: "Enter a positive whole number."}
        ) from exc
    if value < 1:
        raise ConfigurationError({field_name: "Enter a positive whole number."})
    return value


def _active_rule_exists(*, category, location_code, excluding=None):
    rules = RoutingRule.objects.filter(
        active=True, category=category, location_code=location_code
    )
    if excluding is not None:
        rules = rules.exclude(pk=excluding.pk)
    return rules.exists()


def _save_routing_rule(rule):
    """Convert a database uniqueness race into a safe validation response."""
    try:
        # A nested savepoint lets the outer service transaction continue after
        # SQLite/PostgreSQL rejects a concurrent duplicate insert/update.
        with transaction.atomic():
            rule.save()
    except IntegrityError as exc:
        raise ConfigurationError(
            "An active routing rule already exists for this category and location."
        ) from exc


@transaction.atomic
def create_category(actor, *, name, minimum_priority=Priority.LOW):
    _require_admin(actor)
    category = Category(name=(name or "").strip(), minimum_priority=minimum_priority)
    _validate(category)
    category.save()
    _audit(
        actor,
        category,
        ConfigurationAuditEvent.Action.CREATED,
        new_values=_snapshot(category, ("name", "minimum_priority", "active")),
    )
    return category


@transaction.atomic
def update_category(actor, category, *, name=None, minimum_priority=None):
    _require_admin(actor)
    old = _snapshot(category, ("name", "minimum_priority", "active"))
    if name is not None:
        category.name = name.strip()
    if minimum_priority is not None:
        category.minimum_priority = minimum_priority
    _validate(category)
    category.save()
    _audit(
        actor,
        category,
        ConfigurationAuditEvent.Action.UPDATED,
        old,
        _snapshot(category, ("name", "minimum_priority", "active")),
    )
    return category


@transaction.atomic
def deactivate_category(actor, category):
    _require_admin(actor)
    if category.active:
        old = _snapshot(category, ("name", "minimum_priority", "active"))
        category.active = False
        category.save(update_fields=["active"])
        _audit(
            actor,
            category,
            ConfigurationAuditEvent.Action.DEACTIVATED,
            old,
            _snapshot(category, ("name", "minimum_priority", "active")),
        )
    return category


@transaction.atomic
def create_routing_rule(actor, *, category=None, location_code="", department, precedence=100):
    _require_admin(actor)
    location_code = _normalise_location(location_code)
    precedence = _positive_int(precedence, "precedence")
    if _active_rule_exists(category=category, location_code=location_code):
        raise ConfigurationError(
            "An active routing rule already exists for this category and location."
        )
    rule = RoutingRule(
        category=category,
        location_code=location_code,
        department=department,
        precedence=precedence,
    )
    _validate(rule)
    if not department.active:
        raise ConfigurationError({"department": "A routing rule requires an active department."})
    if category is not None and not category.active:
        raise ConfigurationError({"category": "An inactive category cannot be routed."})
    _save_routing_rule(rule)
    _audit(
        actor,
        rule,
        ConfigurationAuditEvent.Action.CREATED,
        new_values=_snapshot(
            rule, ("category", "location_code", "department", "precedence", "active")
        ),
    )
    return rule


@transaction.atomic
def update_routing_rule(
    actor,
    rule,
    *,
    category=UNSET,
    location_code=UNSET,
    department=UNSET,
    precedence=UNSET,
):
    _require_admin(actor)
    old = _snapshot(rule, ("category", "location_code", "department", "precedence", "active"))
    if category is not UNSET:
        rule.category = category
    if location_code is not UNSET:
        rule.location_code = _normalise_location(location_code)
    if department is not UNSET:
        rule.department = department
    if precedence is not UNSET:
        rule.precedence = _positive_int(precedence, "precedence")
    if rule.active and _active_rule_exists(
        category=rule.category, location_code=rule.location_code, excluding=rule
    ):
        raise ConfigurationError(
            "An active routing rule already exists for this category and location."
        )
    _validate(rule)
    if not rule.department.active:
        raise ConfigurationError({"department": "A routing rule requires an active department."})
    if rule.category is not None and not rule.category.active:
        raise ConfigurationError({"category": "An inactive category cannot be routed."})
    _save_routing_rule(rule)
    _audit(
        actor,
        rule,
        ConfigurationAuditEvent.Action.UPDATED,
        old,
        _snapshot(rule, ("category", "location_code", "department", "precedence", "active")),
    )
    return rule


@transaction.atomic
def deactivate_routing_rule(actor, rule):
    _require_admin(actor)
    if rule.active:
        old = _snapshot(rule, ("category", "location_code", "department", "precedence", "active"))
        rule.active = False
        rule.save(update_fields=["active"])
        _audit(
            actor,
            rule,
            ConfigurationAuditEvent.Action.DEACTIVATED,
            old,
            _snapshot(rule, ("category", "location_code", "department", "precedence", "active")),
        )
    return rule


@transaction.atomic
def set_sla_configuration(actor, *, priority, duration_minutes, category=None):
    _require_admin(actor)
    duration_minutes = _positive_int(duration_minutes, "duration_minutes")
    if priority not in Priority.values:
        raise ConfigurationError({"priority": "Choose a supported priority."})
    config = SLAConfiguration.objects.filter(
        active=True, category=category, priority=priority
    ).first()
    if config is None:
        config = SLAConfiguration(
            category=category, priority=priority, duration_minutes=duration_minutes
        )
        _validate(config)
        config.save()
        _audit(
            actor,
            config,
            ConfigurationAuditEvent.Action.CREATED,
            new_values=_snapshot(
                config, ("category", "priority", "duration_minutes", "active")
            ),
        )
    else:
        old = _snapshot(config, ("category", "priority", "duration_minutes", "active"))
        config.duration_minutes = duration_minutes
        _validate(config)
        config.save(update_fields=["duration_minutes"])
        _audit(
            actor,
            config,
            ConfigurationAuditEvent.Action.UPDATED,
            old,
            _snapshot(config, ("category", "priority", "duration_minutes", "active")),
        )
    return config


@transaction.atomic
def deactivate_sla_configuration(actor, config):
    _require_admin(actor)
    if config.active:
        old = _snapshot(config, ("category", "priority", "duration_minutes", "active"))
        config.active = False
        config.save(update_fields=["active"])
        _audit(
            actor,
            config,
            ConfigurationAuditEvent.Action.DEACTIVATED,
            old,
            _snapshot(config, ("category", "priority", "duration_minutes", "active")),
        )
    return config


@transaction.atomic
def update_escalation_policy(
    actor, policy, *, default_department=None, interval_minutes=None, maximum_level=None
):
    _require_admin(actor)
    old = _snapshot(policy, ("default_department", "interval_minutes", "maximum_level"))
    if default_department is not None:
        policy.default_department = default_department
    if interval_minutes is not None:
        policy.interval_minutes = _positive_int(interval_minutes, "interval_minutes")
    if maximum_level is not None:
        policy.maximum_level = _positive_int(maximum_level, "maximum_level")
    try:
        _validate(policy)
        if not policy.default_department.active:
            raise ConfigurationError(
                {"default_department": "The default department must be active."}
            )
    except ConfigurationError:
        policy.default_department_id = old["default_department"]
        policy.interval_minutes = old["interval_minutes"]
        policy.maximum_level = old["maximum_level"]
        raise
    policy.save()
    _audit(
        actor,
        policy,
        ConfigurationAuditEvent.Action.UPDATED,
        old,
        _snapshot(policy, ("default_department", "interval_minutes", "maximum_level")),
    )
    return policy


@transaction.atomic
def create_escalation_policy(
    actor, *, default_department, interval_minutes, maximum_level
):
    """Create the singleton policy after F1's departments are available."""
    _require_admin(actor)
    if EscalationPolicy.objects.filter(key="default").exists():
        raise ConfigurationError("The escalation policy already exists.")
    policy = EscalationPolicy(
        key="default",
        default_department=default_department,
        interval_minutes=_positive_int(interval_minutes, "interval_minutes"),
        maximum_level=_positive_int(maximum_level, "maximum_level"),
    )
    _validate(policy)
    if not default_department.active:
        raise ConfigurationError(
            {"default_department": "The default department must be active."}
        )
    policy.save()
    _audit(
        actor,
        policy,
        ConfigurationAuditEvent.Action.CREATED,
        new_values=_snapshot(policy, ("default_department", "interval_minutes", "maximum_level")),
    )
    return policy
