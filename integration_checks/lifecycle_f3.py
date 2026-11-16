"""Explicit B20 + PR #68/#70 compatibility checks; missing sources fail."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections
from django.utils import timezone

from complaints.models import Complaint
from routing.allocation import allocate_complaint
from routing.escalation import run_escalation
from workflow.lifecycle import ModifiedRecord, get_transition_revision, transition_complaint
from workflow.models import ComplaintHistory, NotificationEvent

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def case(complaint_factory, head_user, staff_user, routing_configuration):
    complaint = complaint_factory(assignee=staff_user, due_at=timezone.now() - timedelta(minutes=1))
    return complaint, head_user, staff_user


def revision(complaint, head, target='IN_PROGRESS'):
    return get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state=target)


def act(complaint, head, token, target='IN_PROGRESS'):
    return transition_complaint(actor=head, complaint_id=complaint.complaint_id, target_state=target,
                                expected_revision=token, reason='Synthetic rejection reason')


def test_real_allocation_invalidates_revision_and_lifecycle_records_account(case, user_factory):
    complaint, head, staff = case
    token = revision(complaint, head)
    replacement = user_factory(role='STAFF', department=complaint.department)
    allocate_complaint(actor=head, complaint_id=complaint.complaint_id, assignee=replacement,
                       expected_assignee_id=staff.pk, reason='Synthetic reassignment')
    with pytest.raises(ModifiedRecord):
        act(complaint, head, token)
    act(complaint, head, revision(complaint, head))
    event = ComplaintHistory.objects.get(event_type='STATUS_CHANGED')
    assert event.actor_id == head.pk and event.new_state == 'IN_PROGRESS'
    complaint.refresh_from_db()
    assert complaint.assignee_id == replacement.pk
    assert NotificationEvent.objects.filter(kind='STAFF_ASSIGNED').count() == 1
    assert NotificationEvent.objects.filter(kind='STARTED').count() == 1


def test_real_escalation_invalidates_revision_and_terminal_rejection_excludes_next_run(case):
    complaint, head, _ = case
    token = revision(complaint, head, 'REJECTED')
    assert run_escalation().escalated == 1
    with pytest.raises(ModifiedRecord):
        act(complaint, head, token, 'REJECTED')
    act(complaint, head, revision(complaint, head, 'REJECTED'), 'REJECTED')
    complaint.refresh_from_db()
    assert complaint.status == 'REJECTED' and complaint.escalation_level == 1
    assert run_escalation().escalated == 0
    assert ComplaintHistory.objects.count() == 2
    assert NotificationEvent.objects.filter(kind='ESCALATED').count() == 1


def test_lifecycle_rollback_preserves_committed_f3_assignment(case, user_factory):
    complaint, head, staff = case
    replacement = user_factory(role='STAFF', department=complaint.department)
    allocate_complaint(actor=head, complaint_id=complaint.complaint_id, assignee=replacement,
                       expected_assignee_id=staff.pk, reason='Synthetic reassignment')
    token = revision(complaint, head)
    with patch('workflow.notifications.Notification.objects.create', side_effect=RuntimeError('controlled')):
        with pytest.raises(RuntimeError):
            act(complaint, head, token)
    complaint.refresh_from_db()
    assert complaint.status == 'ASSIGNED' and complaint.assignee_id == replacement.pk
    assert ComplaintHistory.objects.count() == NotificationEvent.objects.count() == 1


def test_concurrent_rejection_and_real_escalation_do_not_overwrite_each_other(case):
    complaint, head, _ = case
    token = revision(complaint, head, 'REJECTED')
    barrier = Barrier(2)

    def work(kind):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if kind == 'escalate':
                return run_escalation().escalated
            try:
                return act(complaint, head, token, 'REJECTED').new_state
            except ModifiedRecord:
                return 'STALE'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        escalated, rejected = list(pool.map(work, ['escalate', 'reject']))
    complaint.refresh_from_db()
    assert ComplaintHistory.objects.count() == 1
    if rejected == 'REJECTED':
        assert complaint.status == 'REJECTED' and escalated == 0
    else:
        assert rejected == 'STALE' and complaint.status == 'ASSIGNED' and escalated == 1
