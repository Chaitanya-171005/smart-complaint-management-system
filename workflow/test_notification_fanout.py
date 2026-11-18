"""Recipient fanout work is batched without dropping recipients or email jobs."""
import json
from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest
from workflow.history_service import record_history
from workflow.models import EmailDelivery, Notification, NotificationEvent
from workflow.notifications import publish_history_event

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('head_count', [3, 50])
def test_notice_fanout_has_two_inserts_and_complete_durable_graph(complaint_factory, user_factory, department_factory, head_count):
    complaint = complaint_factory()
    staff = user_factory(role='STAFF', department=complaint.department)
    complaint.assignee = staff
    complaint.save(update_fields=['assignee'])
    heads = [user_factory(role='HEAD', department=complaint.department) for _ in range(head_count)]
    user_factory(role='HEAD', department=department_factory())
    user_factory(role='HEAD', department=complaint.department, is_active=False)
    user_factory(role='STAFF', department=complaint.department)
    with CaptureQueriesContext(connection) as queries:
        history = record_history(complaint.complaint_id, 'ALLOCATED', 'HEAD', 'ASSIGNED', 'ASSIGNED')
    notice_inserts = [q['sql'] for q in queries if q['sql'].startswith('INSERT INTO "workflow_notification"')]
    email_inserts = [q['sql'] for q in queries if q['sql'].startswith('INSERT INTO "workflow_emaildelivery"')]
    print(json.dumps({'heads': head_count, 'notice_inserts':len(notice_inserts), 'email_inserts':len(email_inserts), 'total_statements':len(queries)}))
    event = NotificationEvent.objects.get(history=history)
    expected = {complaint.submitted_by_id, staff.pk, *(h.pk for h in heads)}
    assert set(Notification.objects.filter(event=event).values_list('recipient_id',flat=True)) == expected
    jobs = EmailDelivery.objects.filter(notice__event=event)
    assert set(jobs.values_list('notice__recipient_id',flat=True)) == expected
    assert jobs.filter(status='PENDING', attempt_count=0).count() == len(expected)
    before = list(event.notices.order_by('pk').values_list('pk',flat=True))
    assert publish_history_event(history).pk == event.pk
    assert list(event.notices.order_by('pk').values_list('pk',flat=True)) == before
    assert len(notice_inserts) == len(email_inserts) == 1
