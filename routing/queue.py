"""Authorized department queues ordered by urgency and age."""

from django.db.models import Case, IntegerField, Value, When

from accounts.permissions import can_view_department_queue, require_permission, scope_complaints
from complaints.models import Complaint
from workflow.services import paginate_complaints

OPEN_QUEUE_STATUSES = (
    Complaint.Status.ASSIGNED, Complaint.Status.IN_PROGRESS, Complaint.Status.REOPENED,
)


def department_queue(user, department):
    require_permission(can_view_department_queue, user, department)
    return (
        scope_complaints(user, Complaint.objects.all())
        .filter(department=department, status__in=OPEN_QUEUE_STATUSES)
        .select_related("assignee")
        .annotate(priority_rank=Case(
            When(priority=Complaint.Priority.CRITICAL, then=Value(0)),
            When(priority=Complaint.Priority.HIGH, then=Value(1)),
            When(priority=Complaint.Priority.MEDIUM, then=Value(2)),
            When(priority=Complaint.Priority.LOW, then=Value(3)),
            default=Value(4), output_field=IntegerField(),
        ))
        .order_by("-is_escalated", "priority_rank", "submitted_at", "pk")
    )


def department_queue_page(user, department, page_number=1):
    return paginate_complaints(department_queue(user, department), page_number)
