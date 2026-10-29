"""Routing, SLA and escalation configuration (B17 / REQ-ADM-03)."""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


MAX_SLA_DURATION_MINUTES = 365 * 24 * 60


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    CRITICAL = "CRITICAL", "Critical"


class Category(models.Model):
    """Administrator-managed complaint category, retained by deactivation."""

    name = models.CharField(max_length=50, unique=True)
    minimum_priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.LOW
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "pk"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(Lower("name"), name="category_name_ci_unique"),
        ]

    def __str__(self):
        return self.name


class RoutingRule(models.Model):
    """One active route, ordered by configured precedence within its scope."""

    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="routing_rules",
    )
    # F1 owns canonical location master data. This stable code is the agreed
    # integration boundary until its Location model is merged.
    location_code = models.CharField(max_length=100, blank=True)
    # A non-null canonical representation permits a portable conditional unique
    # constraint for category-only, location-only and combined rules.
    scope_key = models.CharField(max_length=220, editable=False)
    department = models.ForeignKey(
        "accounts.Department", on_delete=models.PROTECT, related_name="routing_rules"
    )
    precedence = models.PositiveIntegerField(default=100)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["precedence", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(category__isnull=False) | ~Q(location_code=""),
                name="routing_rule_has_category_or_location",
            ),
            models.UniqueConstraint(
                fields=["scope_key"],
                condition=Q(active=True),
                name="routing_rule_unique_active_scope",
            ),
        ]

    def clean(self):
        self.location_code = (self.location_code or "").strip().upper()
        if not self.category_id and not self.location_code:
            raise ValidationError("A routing rule needs a category or a location.")
        if self.precedence < 1:
            raise ValidationError({"precedence": "Precedence must be positive."})

    def save(self, *args, **kwargs):
        self.location_code = (self.location_code or "").strip().upper()
        self.scope_key = f"{self.category_id or 0}:{self.location_code}"
        super().save(*args, **kwargs)

    def __str__(self):
        scope = self.category.name if self.category_id else "Any category"
        if self.location_code:
            scope += f" / {self.location_code}"
        return f"{scope} -> {self.department.name}"


class SLAConfiguration(models.Model):
    """A positive elapsed-time SLA, optionally specific to a category."""

    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sla_configurations",
    )
    priority = models.CharField(max_length=10, choices=Priority.choices)
    # This bound keeps later due-date calculation within a predictable business range.
    duration_minutes = models.PositiveIntegerField(
        validators=[MaxValueValidator(MAX_SLA_DURATION_MINUTES)]
    )
    # A non-null scope key makes the active-row uniqueness constraint portable to
    # SQLite, which otherwise treats NULL values as distinct in unique indexes.
    scope_key = models.CharField(max_length=120, editable=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category__name", "priority", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(duration_minutes__gt=0), name="sla_duration_must_be_positive"
            ),
            models.CheckConstraint(
                condition=Q(duration_minutes__lte=MAX_SLA_DURATION_MINUTES),
                name="sla_duration_within_one_year",
            ),
            models.UniqueConstraint(
                fields=["scope_key"],
                condition=Q(active=True),
                name="sla_unique_active_scope",
            ),
        ]

    def clean(self):
        errors = {}
        if self.duration_minutes < 1:
            errors["duration_minutes"] = "SLA duration must be positive."
        if self.duration_minutes > MAX_SLA_DURATION_MINUTES:
            errors["duration_minutes"] = "SLA duration cannot exceed one year."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.scope_key = f"{self.category_id or 0}:{self.priority}"
        super().save(*args, **kwargs)

    def __str__(self):
        scope = self.category.name if self.category_id else "Default"
        return f"{scope}: {self.get_priority_display()} ({self.duration_minutes} min)"


class EscalationPolicy(models.Model):
    """The one campus-wide escalation policy used by new scheduled runs."""

    key = models.CharField(max_length=32, unique=True, default="default", editable=False)
    default_department = models.ForeignKey(
        "accounts.Department", on_delete=models.PROTECT, related_name="default_for_escalation"
    )
    interval_minutes = models.PositiveIntegerField()
    maximum_level = models.PositiveIntegerField()

    class Meta:
        verbose_name_plural = "escalation policies"
        constraints = [
            models.CheckConstraint(
                condition=Q(interval_minutes__gt=0),
                name="escalation_interval_must_be_positive",
            ),
            models.CheckConstraint(
                condition=Q(maximum_level__gt=0),
                name="escalation_maximum_level_must_be_positive",
            ),
        ]

    def clean(self):
        errors = {}
        if self.interval_minutes < 1:
            errors["interval_minutes"] = "Escalation interval must be positive."
        if self.maximum_level < 1:
            errors["maximum_level"] = "Maximum escalation level must be positive."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Every {self.interval_minutes} min, maximum level {self.maximum_level}"


class ConfigurationAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Configuration audit events cannot be edited.")

    def delete(self):
        raise ValidationError("Configuration audit events cannot be deleted.")


class ConfigurationAuditEvent(models.Model):
    """Append-only audit record for master-data and configuration changes."""

    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        DEACTIVATED = "DEACTIVATED", "Deactivated"
        REACTIVATED = "REACTIVATED", "Reactivated"

    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="configuration_audit_events",
    )
    entity_type = models.CharField(max_length=64)
    entity_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=16, choices=Action.choices)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ConfigurationAuditQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Configuration audit events cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Configuration audit events cannot be deleted.")

    def __str__(self):
        return f"{self.entity_type}#{self.entity_id}: {self.action}"
