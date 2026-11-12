from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from accounts.models import SecurityEvent, User
from complaints.models import Complaint
from routing.queue import department_queue, department_queue_page

pytestmark = pytest.mark.django_db


def test_queue_order_scope_and_statuses(department, head_user, staff_user, department_factory, complaint_factory):
    now = timezone.now()
    def create(**kwargs):
        return complaint_factory(department=department, submitted_at=now, **kwargs)
    low = create(priority="LOW")
    medium = create(priority="MEDIUM", status="IN_PROGRESS")
    high = create(priority="HIGH", status="REOPENED")
    critical = create(priority="CRITICAL")
    escalated = create(priority="LOW", is_escalated=True, escalation_level=1)
    older = complaint_factory(department=department, submitted_at=now - timedelta(minutes=1), priority="HIGH")
    tie = create(priority="HIGH")
    for status in ("SUBMITTED", "RESOLVED", "CLOSED", "REJECTED"):
        create(status=status)
    complaint_factory(department=department_factory(), submitted_at=now)
    expected = [escalated.pk, critical.pk, older.pk, high.pk, tie.pk, medium.pk, low.pk]
    for user in (head_user, staff_user):
        assert list(department_queue(user, department).values_list("pk", flat=True)) == expected


def test_queue_refusals_are_logged(department, department_factory, user_factory):
    other = department_factory()
    for role, dept in ((User.Role.ADMIN, None), (User.Role.COMPLAINANT, None),
                       (User.Role.STAFF, other), (User.Role.HEAD, other)):
        user = user_factory(role=role, department=dept)
        before = SecurityEvent.objects.count()
        with pytest.raises(PermissionDenied):
            department_queue(user, department)
        assert SecurityEvent.objects.count() == before + 1
        assert SecurityEvent.objects.latest("pk").event_type == SecurityEvent.EventType.AUTHORIZATION_REFUSED


def test_queue_pagination(department, head_user, complaint_factory):
    for _ in range(26):
        complaint_factory(department=department)
    first = department_queue_page(head_user, department)
    second = department_queue_page(head_user, department, 2)
    assert len(first.object_list) == 25 and len(second.object_list) == 1
    assert first.paginator.count == 26
