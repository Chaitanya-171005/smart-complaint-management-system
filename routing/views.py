"""Administrator-facing B17 configuration screen."""

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import ConfigAuditEvent, Department, Location, User
from accounts.permissions import role_required

from .models import Category, EscalationPolicy, Priority, RoutingRule, SLAConfiguration
from .services import (
    ConfigurationError,
    create_escalation_policy,
    create_category,
    create_routing_rule,
    deactivate_category,
    deactivate_routing_rule,
    deactivate_sla_configuration,
    reactivate_category,
    set_sla_configuration,
    update_category,
    update_escalation_policy,
    update_routing_rule,
)


def _object(model, raw_id, field_name):
    try:
        return model.objects.get(pk=int(raw_id))
    except (TypeError, ValueError, ObjectDoesNotExist) as exc:
        raise ConfigurationError({field_name: "Choose a valid value."}) from exc


def _optional_category(raw_id):
    return None if not raw_id else _object(Category, raw_id, "category")


def _show_error(request, error):
    if hasattr(error, "message_dict"):
        message = "; ".join(
            f"{field}: {', '.join(values)}" for field, values in error.message_dict.items()
        )
    else:
        message = "; ".join(error.messages)
    messages.error(request, message)


@role_required(User.Role.ADMIN)
@require_http_methods(["GET", "POST"])
def configuration(request):
    """Manage the configuration that applies prospectively to new work only."""

    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "create_category":
                create_category(
                    request.user,
                    name=request.POST.get("name"),
                    minimum_priority=request.POST.get("minimum_priority", Priority.LOW),
                )
            elif action == "update_category":
                update_category(
                    request.user,
                    _object(Category, request.POST.get("category_id"), "category"),
                    name=request.POST.get("name"),
                    minimum_priority=request.POST.get("minimum_priority"),
                )
            elif action == "deactivate_category":
                deactivate_category(
                    request.user, _object(Category, request.POST.get("category_id"), "category")
                )
            elif action == "reactivate_category":
                reactivate_category(
                    request.user, _object(Category, request.POST.get("category_id"), "category")
                )
            elif action == "create_rule":
                create_routing_rule(
                    request.user,
                    category=_optional_category(request.POST.get("category_id")),
                    location_code=request.POST.get("location_code", ""),
                    department=_object(Department, request.POST.get("department_id"), "department"),
                    precedence=request.POST.get("precedence", 100),
                )
            elif action == "update_rule":
                update_routing_rule(
                    request.user,
                    _object(RoutingRule, request.POST.get("rule_id"), "rule"),
                    category=_optional_category(request.POST.get("category_id")),
                    location_code=request.POST.get("location_code", ""),
                    department=_object(Department, request.POST.get("department_id"), "department"),
                    precedence=request.POST.get("precedence"),
                )
            elif action == "deactivate_rule":
                deactivate_routing_rule(
                    request.user, _object(RoutingRule, request.POST.get("rule_id"), "rule")
                )
            elif action == "set_sla":
                set_sla_configuration(
                    request.user,
                    category=_optional_category(request.POST.get("category_id")),
                    priority=request.POST.get("priority"),
                    duration_minutes=request.POST.get("duration_minutes"),
                )
            elif action == "deactivate_sla":
                deactivate_sla_configuration(
                    request.user,
                    _object(SLAConfiguration, request.POST.get("sla_id"), "SLA configuration"),
                )
            elif action == "update_escalation":
                update_escalation_policy(
                    request.user,
                    _object(EscalationPolicy, request.POST.get("policy_id"), "policy"),
                    default_department=_object(
                        Department, request.POST.get("default_department_id"), "default department"
                    ),
                    interval_minutes=request.POST.get("interval_minutes"),
                    maximum_level=request.POST.get("maximum_level"),
                )
            elif action == "create_escalation":
                create_escalation_policy(
                    request.user,
                    default_department=_object(
                        Department, request.POST.get("default_department_id"), "default department"
                    ),
                    interval_minutes=request.POST.get("interval_minutes"),
                    maximum_level=request.POST.get("maximum_level"),
                )
            else:
                return HttpResponseBadRequest("Unknown configuration action.")
        except ConfigurationError as error:
            _show_error(request, error)
        else:
            messages.success(request, "Configuration updated.")
        return redirect("routing:configuration")

    return render(
        request,
        "routing/configuration.html",
        {
            "categories": Category.objects.all(),
            "locations": Location.objects.filter(active=True).order_by("code"),
            "active_location_codes": set(Location.objects.filter(active=True).values_list("code", flat=True)),
            "departments": Department.objects.filter(active=True).order_by("name"),
            "rules": RoutingRule.objects.select_related("category", "department").all(),
            "sla_configurations": SLAConfiguration.objects.select_related("category").all(),
            "policy": EscalationPolicy.objects.select_related("default_department").filter(key="default").first(),
            "priorities": Priority.choices,
            "audit_events": ConfigAuditEvent.objects.filter(entity_type__in=("Category", "RoutingRule", "SLAConfiguration", "EscalationPolicy")).order_by("-created_at", "-pk")[:20],
        },
    )


@role_required(User.Role.HEAD, User.Role.STAFF)
@require_http_methods(["GET"])
def queue(request):
    from .queue import department_queue_page

    page = department_queue_page(request.user, request.user.department_id, request.GET.get("page", 1))
    staff = User.objects.filter(role=User.Role.STAFF, is_active=True, department_id=request.user.department_id)
    return render(request, "routing/queue.html", {"page": page, "staff": staff})


@role_required(User.Role.HEAD)
@require_http_methods(["POST"])
def assign(request, complaint_id):
    from .allocation import AllocationError, allocate_complaint

    try:
        target = int(request.POST.get("assignee", ""))
        expected = request.POST.get("expected_assignee", "")
        expected = int(expected) if expected else None
        if target <= 0 or (expected is not None and expected <= 0):
            raise ValueError
    except ValueError:
        return HttpResponseBadRequest("Invalid assignee.")
    try:
        allocate_complaint(actor=request.user, complaint_id=complaint_id, assignee=target,
                           expected_assignee_id=expected, reason=request.POST.get("reason", ""))
    except AllocationError as error:
        return HttpResponseBadRequest("; ".join(error.messages))
    return redirect("routing:queue")
