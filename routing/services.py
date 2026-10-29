"""Admin-only configuration operations for B17.

Views and management commands must use these functions instead of writing models
directly. That keeps authorization, validation and REQ-ADM-04 auditing together.
"""

from functools import wraps

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
    MAX_ESCALATION_INTERVAL_MINUTES,
    MAX_ESCALATION_LEVEL,
    MAX_SLA_DURATION_MINUTES,
)


class ConfigurationError(ValidationError):
    """A safe validation failure for an administrator to correct."""


UNSET = object()


def _require_admin(actor):
    require_permission(can_manage_configuration, actor)


def admin_operation(func):
    """Authorize before beginning the atomic configuration change."""

    @wraps(func)
    def wrapper(actor, *args, **kwargs):
        _require_admin(actor)
        with transaction.atomic():
            return func(actor, *args, **kwargs)

    return wrapper


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


def _positive_int(value, field_name, minimum=1, maximum=None, message=None):
    if message is None:
        if maximum is None:
            message = f"Enter a whole number from {minimum} or greater."
        else:
            message = f"Enter a whole number from {minimum} to {maximum}."
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError({field_name: message}) from exc
    if value < minimum or (maximum is not None and value > maximum):
        raise ConfigurationError({field_name: message})
    return value


def _sla_duration(value):
    return _positive_int(
        value,
        "duration_minutes",
        minimum=1,
        maximum=MAX_SLA_DURATION_MINUTES,
        message=(
            f"Enter a whole number of minutes from 1 to {MAX_SLA_DURATION_MINUTES} "
            "(one year)."
        ),
    )


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


@admin_operation
def create_category(actor, *, name, minimum_priority=Priority.LOW):
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


@admin_operation
def update_category(actor, category, *, name=None, minimum_priority=None):
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


@admin_operation
def deactivate_category(actor, category):
    if category.active:
        if category.routing_rules.filter(active=True).exists():
            raise ConfigurationError(
                "Deactivate this category's active routing rules before deactivating it."
            )
        if category.sla_configurations.filter(active=True).exists():
            raise ConfigurationError(
                "Deactivate this category's active SLA overrides before deactivating it."
            )
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


@admin_operation
def reactivate_category(actor, category):
    if not category.active:
        old = _snapshot(category, ("name", "minimum_priority", "active"))
        category.active = True
        category.save(update_fields=["active"])
        _audit(
            actor,
            category,
            ConfigurationAuditEvent.Action.REACTIVATED,
            old,
            _snapshot(category, ("name", "minimum_priority", "active")),
        )
    return category


@admin_operation
def create_routing_rule(actor, *, category=None, location_code="", department, precedence=100):
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


@admin_operation
def update_routing_rule(
    actor,
    rule,
    *,
    category=UNSET,
    location_code=UNSET,
    department=UNSET,
    precedence=UNSET,
):
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


@admin_operation
def deactivate_routing_rule(actor, rule):
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


@admin_operation
def set_sla_configuration(actor, *, priority, duration_minutes, category=None):
    duration_minutes = _sla_duration(duration_minutes)
    if priority not in Priority.values:
        raise ConfigurationError({"priority": "Choose a supported priority."})
    if category is not None and not category.active:
        raise ConfigurationError({"category": "An inactive category cannot have an SLA override."})
    config = SLAConfiguration.objects.filter(
        active=True, category=category, priority=priority
    ).first()
    if config is None:
        config = SLAConfiguration(
            category=category, priority=priority, duration_minutes=duration_minutes
        )
        _validate(config)
        try:
            with transaction.atomic():
                config.save()
        except IntegrityError as exc:
            raise ConfigurationError(
                "An active SLA configuration already exists for this category and priority."
            ) from exc
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


@admin_operation
def deactivate_sla_configuration(actor, config):
    if config.active:
        if (
            config.category_id is None
            and SLAConfiguration.objects.filter(
                active=True, category=None, priority=config.priority
            ).count()
            <= 1
        ):
            raise ConfigurationError(
                "Each priority must retain one active default SLA configuration."
            )
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


@admin_operation
def update_escalation_policy(
    actor, policy, *, default_department=None, interval_minutes=None, maximum_level=None
):
    old = _snapshot(policy, ("default_department", "interval_minutes", "maximum_level"))
    if default_department is not None:
        policy.default_department = default_department
    if interval_minutes is not None:
        policy.interval_minutes = _positive_int(
            interval_minutes,
            "interval_minutes",
            minimum=1,
            maximum=MAX_ESCALATION_INTERVAL_MINUTES,
            message=(
                f"Enter a whole number of minutes from 1 to {MAX_ESCALATION_INTERVAL_MINUTES} "
                "(30 days)."
            ),
        )
    if maximum_level is not None:
        policy.maximum_level = _positive_int(
            maximum_level,
            "maximum_level",
            minimum=1,
            maximum=MAX_ESCALATION_LEVEL,
            message=f"Enter a whole number from 1 to {MAX_ESCALATION_LEVEL}.",
        )
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


@admin_operation
def create_escalation_policy(
    actor, *, default_department, interval_minutes, maximum_level
):
    """Create the singleton policy after F1's departments are available."""
    if EscalationPolicy.objects.filter(key="default").exists():
        raise ConfigurationError("The escalation policy already exists.")
    policy = EscalationPolicy(
        key="default",
        default_department=default_department,
        interval_minutes=_positive_int(
            interval_minutes,
            "interval_minutes",
            minimum=1,
            maximum=MAX_ESCALATION_INTERVAL_MINUTES,
            message=(
                f"Enter a whole number of minutes from 1 to {MAX_ESCALATION_INTERVAL_MINUTES} "
                "(30 days)."
            ),
        ),
        maximum_level=_positive_int(
            maximum_level,
            "maximum_level",
            minimum=1,
            maximum=MAX_ESCALATION_LEVEL,
            message=f"Enter a whole number from 1 to {MAX_ESCALATION_LEVEL}.",
        ),
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


def department_in_use(department):
    """F1's department-deactivation service must refuse deactivation when this is true."""
    return (
        RoutingRule.objects.filter(department=department, active=True).exists()
        or EscalationPolicy.objects.filter(default_department=department).exists()
    )
