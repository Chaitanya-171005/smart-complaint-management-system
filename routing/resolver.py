"""Read routing configuration and persist immutable intake decisions."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from django.db import connections
from django.db.models import Q
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from accounts.models import Department, Location
from .models import Category, EscalationPolicy, RoutingDecision, RoutingRule


@dataclass(frozen=True)
class RouteResult:
    department: Department
    rule: RoutingRule | None
    used_default: bool
    unrouted: bool
    basis: str
    reason: str
    decided_at: datetime


class RoutingConfigurationError(Exception):
    """No active default department is available when routing needs one."""


def route_complaint(category: Category | None, location_code, *, now=None) -> RouteResult:
    """Choose the first matching scope, ordered by precedence then primary key."""
    location = Location.normalize_code(location_code or "")
    decided_at = timezone.now() if now is None else now
    candidates = Q(pk__in=[])
    if category is not None:
        candidates |= Q(category=category, location_code="")
        if location:
            candidates |= Q(category=category, location_code=location)
    if location:
        candidates |= Q(category__isnull=True, location_code=location)
    rules = RoutingRule.objects.filter(candidates, active=True, department__active=True).select_related(
        "department"
    ).order_by("precedence", "pk")
    tiers = {}
    for rule in rules:
        basis = ("CATEGORY_LOCATION" if rule.category_id and rule.location_code else
                 "CATEGORY" if rule.category_id else "LOCATION")
        tiers.setdefault(basis, rule)
    for basis, label in (("CATEGORY_LOCATION", "category + location"),
                         ("CATEGORY", "category"), ("LOCATION", "location")):
        if basis in tiers:
            rule = tiers[basis]
            return RouteResult(rule.department, rule, False, False, basis,
                               f"{label} rule #{rule.pk} (precedence {rule.precedence})", decided_at)
    policy = EscalationPolicy.objects.select_related("default_department").filter(key="default").first()
    if policy is None or not policy.default_department.active:
        raise RoutingConfigurationError("No active default routing department is configured.")
    return RouteResult(policy.default_department, None, True, True, "DEFAULT",
                       "no matching rule: default department, needs Administrator attention", decided_at)


def route_and_record(complaint_id, category, location_code, *, now=None) -> RoutingDecision:
    """Record routing in the caller's existing intake transaction."""
    if not connections["default"].in_atomic_block:
        raise TransactionManagementError("Routing requires the caller's intake transaction.")
    if not isinstance(complaint_id, str) or not re.fullmatch(r"SCMS-[0-9]{4}-[0-9]{6}", complaint_id):
        raise ValueError("Invalid complaint ID.")
    try:
        result = route_complaint(category, location_code, now=now)
    except RoutingConfigurationError:
        logging.getLogger(__name__).error("Routing configuration is unavailable.")
        raise
    return RoutingDecision.objects.create(
        complaint_id=complaint_id, department=result.department, rule=result.rule,
        basis=result.basis, unrouted=result.unrouted, reason=result.reason, decided_at=result.decided_at,
    )
