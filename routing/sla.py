"""Derive effective priorities and elapsed-time SLA deadlines without writes."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import Category, Priority, SLAConfiguration


PRIORITY_ORDER = (Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.CRITICAL)


class SLAConfigurationError(Exception):
    """No applicable active SLA configuration exists."""


@dataclass(frozen=True)
class SLAResolution:
    duration_minutes: int
    source: str
    configuration: SLAConfiguration


@dataclass(frozen=True)
class PrioritySLA:
    priority: str
    due_at: datetime
    duration_minutes: int
    source: str


def effective_priority(indicated, category: Category | None) -> str:
    """Apply the category minimum without lowering the indicated priority."""
    if indicated not in Priority.values:
        raise ValueError("Invalid indicated priority.")
    if category is None:
        return indicated
    return max((indicated, category.minimum_priority), key=PRIORITY_ORDER.index)


def resolve_sla(category: Category | None, priority: str) -> SLAResolution:
    """Select an active category override, falling back to the global default."""
    if category is not None:
        configuration = SLAConfiguration.objects.filter(
            category=category, priority=priority, active=True
        ).first()
        if configuration is not None:
            return SLAResolution(configuration.duration_minutes, "CATEGORY", configuration)
    configuration = SLAConfiguration.objects.filter(
        category=None, priority=priority, active=True
    ).first()
    if configuration is None:
        raise SLAConfigurationError("No active SLA configuration exists for this priority.")
    return SLAResolution(configuration.duration_minutes, "DEFAULT", configuration)


def compute_due_at(submitted_at: datetime, duration_minutes: int) -> datetime:
    """Add positive elapsed minutes to an aware timestamp, returning UTC."""
    if not isinstance(submitted_at, datetime) or submitted_at.utcoffset() is None:
        raise ValueError("submitted_at must be an aware datetime.")
    if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int) or duration_minutes <= 0:
        raise ValueError("duration_minutes must be a positive integer.")
    return submitted_at.astimezone(timezone.utc) + timedelta(minutes=duration_minutes)


def derive_priority_and_due(category: Category | None, indicated_priority: str, submitted_at: datetime) -> PrioritySLA:
    """Derive the values to store on a newly submitted complaint."""
    priority = effective_priority(indicated_priority, category)
    resolution = resolve_sla(category, priority)
    return PrioritySLA(priority, compute_due_at(submitted_at, resolution.duration_minutes),
                       resolution.duration_minutes, resolution.source)
