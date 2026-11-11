"""Explicit B22 + unmerged F2/F3 checks; no dependency skip guards."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from complaints.anonymous import submit_anonymous_complaint
from complaints.evidence import staged_evidence
from complaints.intake import new_intake_key
from complaints.models import Attachment, Complaint
from routing.allocation import allocate_complaint
from routing.escalation import run_escalation
from workflow.lifecycle import ModifiedRecord, get_transition_revision
from workflow.models import ComplaintHistory, NotificationEvent
from workflow.resolution_service import progress_complaint, resolve_complaint
from workflow.test_resolution_integration import REMARKS, upload

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def case(complaint_factory, routing_configuration, head_user, staff_user, settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / 'private'
    complaint = complaint_factory(due_at=timezone.now() - timedelta(minutes=1))
    allocate_complaint(actor=head_user, complaint_id=complaint.complaint_id, assignee=staff_user,
                       expected_assignee_id=None)
    token = get_transition_revision(actor=staff_user, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    progress_complaint(actor=staff_user, complaint_id=complaint.complaint_id, expected_revision=token)
    return complaint, staff_user, head_user


def args(case):
    complaint, staff, _ = case
    return dict(actor=staff, complaint_id=complaint.complaint_id, remarks=REMARKS,
                expected_revision=get_transition_revision(actor=staff, complaint_id=complaint.complaint_id,
                                                          target_state='RESOLVED'))


def test_real_assignment_progress_resolution_and_escalation_exclusion(case):
    complaint, staff, _ = case
    resolve_complaint(**args(case), files=[upload('PDF')])
    complaint.refresh_from_db()
    assert complaint.status == 'RESOLVED' and complaint.assignee_id == staff.pk
    assert run_escalation().escalated == 0
    assert list(ComplaintHistory.objects.values_list('event_type', flat=True)) == ['ALLOCATED','STATUS_CHANGED','RESOLVED']
    assert ComplaintHistory.objects.get(event_type='RESOLVED').actor_id == staff.pk
    assert Attachment.objects.get().stage == 'RESOLUTION'
    assert NotificationEvent.objects.filter(kind='RESOLVED').count() == 1


@pytest.mark.parametrize('change', ['allocation', 'escalation'])
def test_real_f3_change_during_staging_refuses_stale_resolution(case, change, user_factory, settings):
    complaint, staff, head = case
    arguments = args(case)
    @contextmanager
    def staged(*files, **kwargs):
        with staged_evidence(*files, **kwargs) as stored:
            if change == 'allocation':
                replacement = user_factory(role='STAFF', department=complaint.department)
                allocate_complaint(actor=head, complaint_id=complaint.complaint_id, assignee=replacement,
                                   expected_assignee_id=staff.pk, reason='Synthetic reassignment')
            else:
                assert run_escalation().escalated == 1
            yield stored
    with patch('workflow.resolution_service.staged_evidence', staged):
        with pytest.raises(ModifiedRecord):
            resolve_complaint(**arguments, files=[upload()])
    complaint.refresh_from_db()
    assert complaint.status == 'IN_PROGRESS' and complaint.resolved_at is None
    assert not Attachment.objects.exists() and not list(settings.PRIVATE_EVIDENCE_ROOT.glob('*'))
    assert not ComplaintHistory.objects.filter(event_type='RESOLVED').exists()


def test_real_anonymous_intake_can_be_resolved_without_reporter_identity(
        routing_configuration, head_user, staff_user, settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / 'private'
    config = routing_configuration
    accepted = submit_anonymous_complaint(key=new_intake_key(), data={
        'category':str(config['category'].pk), 'location':config['location'].code,
        'title':'Synthetic anonymous complaint', 'priority':'LOW',
        'description':'The light does not work in this synthetic test room.',
    })
    complaint = Complaint.objects.get(complaint_id=accepted.complaint_id)
    allocate_complaint(actor=head_user, complaint_id=complaint.complaint_id, assignee=staff_user,
                       expected_assignee_id=None)
    token = get_transition_revision(actor=staff_user, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    progress_complaint(actor=staff_user, complaint_id=complaint.complaint_id, expected_revision=token)
    resolve_complaint(**args((complaint, staff_user, head_user)), files=[upload()])
    complaint.refresh_from_db()
    event = NotificationEvent.objects.get(kind='RESOLVED')
    assert complaint.submitted_by_id is None and event.anonymous
    assert set(event.notices.values_list('recipient_id', flat=True)) == {staff_user.pk, head_user.pk}
    assert Attachment.objects.get(stage='RESOLUTION').uploaded_by_id == staff_user.pk
