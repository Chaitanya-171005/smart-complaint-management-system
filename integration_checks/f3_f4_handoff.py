"""Explicit F4 dependency check; default collection excludes this filename.

Run only where F4 models/publisher are installed. Missing F4 is a dependency
failure, never a passing skip. SMTP delivery is not invoked here.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import transaction
from django.utils import timezone

from routing.escalation import run_escalation
from routing.notifications import publish_escalation_history
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent

pytestmark = pytest.mark.django_db(transaction=True)


def test_real_f4_idempotent_escalation_and_private_recipient_projection(
    routing_configuration, complaint_factory, user_factory, department_factory,
):
    complaint = complaint_factory(anonymous=True, title="PRIVATE_TITLE",
                                  due_at=timezone.now() - timedelta(minutes=1))
    head = user_factory(role="HEAD", department=complaint.department)
    user_factory(role="HEAD", department=department_factory())
    user_factory(role="ADMIN")
    user_factory(role="COMPLAINANT")
    now = timezone.now()
    assert run_escalation(now=now).escalated == 1
    assert run_escalation(now=now).escalated == 0
    history = ComplaintHistory.objects.get(complaint_ref=complaint.complaint_id, event_type="ESCALATED")
    with transaction.atomic():
        first = publish_escalation_history(history)
        assert publish_escalation_history(history).pk == first.pk
    assert NotificationEvent.objects.count() == Notification.objects.count() == EmailDelivery.objects.count() == 1
    assert Notification.objects.get().recipient_id == head.pk
    event = NotificationEvent.objects.get()
    assert event.anonymous and event.history_id == history.pk
    assert complaint.title not in str(event.__dict__)
    assert complaint.reference_digest not in str(event.__dict__)


def test_real_f4_rollback_and_retry(routing_configuration, complaint_factory, user_factory):
    complaint = complaint_factory(anonymous=True, due_at=timezone.now() - timedelta(minutes=1))
    user_factory(role="HEAD", department=complaint.department)
    with patch("workflow.notifications.publish_history_event", side_effect=RuntimeError("PRIVATE_FAILURE")):
        assert run_escalation().failed == 1
    assert not NotificationEvent.objects.exists()
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            assert run_escalation().escalated == 1
            raise RuntimeError("Outer rollback")
    assert not NotificationEvent.objects.exists()
    assert not EmailDelivery.objects.exists()
    assert run_escalation().escalated == 1
    assert NotificationEvent.objects.count() == EmailDelivery.objects.count() == 1


def test_real_f4_missing_recipients_still_records_event(routing_configuration, complaint_factory):
    complaint_factory(anonymous=True, due_at=timezone.now() - timedelta(minutes=1))
    assert run_escalation().escalated == 1
    assert NotificationEvent.objects.count() == 1
    assert not Notification.objects.exists()
    assert not EmailDelivery.objects.exists()
