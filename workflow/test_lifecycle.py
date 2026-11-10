"""B20 SRS matrix, authorization, revision and atomic integration tests."""

from concurrent.futures import ThreadPoolExecutor
from itertools import product
from threading import Barrier
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, transaction
from django.http import Http404

from accounts.models import SecurityEvent, User
from complaints.models import Complaint
from workflow.history_service import record_history
from workflow.lifecycle import (
    FeatureRequired, LifecycleError, ModifiedRecord, TRANSITIONS, _revision,
    get_transition_revision, transition_complaint, validate_owner_edit,
)
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent

State = Complaint.Status
pytestmark = pytest.mark.django_db(transaction=True)

# Independent literal transcription of SRS §4.3, not derived from the code table.
SRS_EDGES = {
    ('SUBMITTED', 'ASSIGNED'), ('SUBMITTED', 'REJECTED'),
    ('ASSIGNED', 'IN_PROGRESS'), ('ASSIGNED', 'REJECTED'),
    ('IN_PROGRESS', 'RESOLVED'), ('RESOLVED', 'CLOSED'),
    ('RESOLVED', 'REOPENED'), ('REOPENED', 'IN_PROGRESS'),
}
CORE_EDGES = {('SUBMITTED', 'REJECTED'), ('ASSIGNED', 'IN_PROGRESS'),
              ('ASSIGNED', 'REJECTED'), ('REOPENED', 'IN_PROGRESS')}


@pytest.fixture
def case(complaint_factory, user_factory):
    complaint = complaint_factory()
    staff = user_factory(role='STAFF', department=complaint.department)
    head = user_factory(role='HEAD', department=complaint.department)
    admin = user_factory(role='ADMIN')
    complaint.assignee = staff
    complaint.save(update_fields=['assignee'])
    return complaint, staff, head, admin


def capture(complaint):
    return (Complaint.objects.filter(pk=complaint.pk).values().get(),
            *[list(model.objects.order_by('pk').values()) for model in (
                ComplaintHistory, NotificationEvent, Notification, EmailDelivery)])


def change(actor, complaint, target, revision=None, reason='Synthetic rejection reason'):
    if revision is None:
        revision = get_transition_revision(actor=actor, complaint_id=complaint.complaint_id, target_state=target)
    return transition_complaint(actor=actor, complaint_id=complaint.complaint_id,
                                target_state=target, expected_revision=revision, reason=reason)


def test_policy_exactly_matches_srs_and_documents_external_actors():
    assert set(TRANSITIONS) == SRS_EDGES
    assert TRANSITIONS[('SUBMITTED', 'ASSIGNED')].external_actors == ('SYSTEM_ROUTING',)
    assert TRANSITIONS[('RESOLVED', 'CLOSED')].external_actors == ('ANONYMOUS_REFERENCE', 'AUTO_CLOSE')
    assert TRANSITIONS[('RESOLVED', 'REOPENED')].external_actors == ('ANONYMOUS_REFERENCE',)
    with pytest.raises(TypeError):
        TRANSITIONS[('CLOSED', 'SUBMITTED')] = None


@pytest.mark.parametrize('source,target', list(product(State.values, repeat=2)))
def test_every_state_pair_succeeds_or_fails_closed(case, source, target):
    complaint, staff, head, _ = case
    complaint.status = source
    complaint.save(update_fields=['status'])
    actor = staff if (source, target) == ('IN_PROGRESS', 'RESOLVED') else (
        complaint.submitted_by if source == 'RESOLVED' and target in ('CLOSED', 'REOPENED') else head)
    before = capture(complaint)
    # Supply a fresh internal revision to test policy denial independently of
    # the public preflight helper, which correctly refuses forbidden actions.
    token = _revision(complaint)
    if (source, target) in CORE_EDGES:
        result = change(actor, complaint, target, token)
        assert result.new_state == target
        assert ComplaintHistory.objects.count() == 1
    elif (source, target) == ('SUBMITTED', 'ASSIGNED'):
        with pytest.raises(PermissionDenied):
            change(actor, complaint, target, token)
        assert capture(complaint) == before
    elif (source, target) in SRS_EDGES:
        with pytest.raises(FeatureRequired):
            change(actor, complaint, target, token)
        assert capture(complaint) == before
    else:
        with pytest.raises(LifecycleError) as error:
            change(actor, complaint, target, token)
        assert error.value.code == 'invalid_transition'
        assert capture(complaint) == before


@pytest.mark.parametrize('source,target,role', [
    ('SUBMITTED', 'REJECTED', 'ADMIN'), ('SUBMITTED', 'REJECTED', 'HEAD'),
    ('ASSIGNED', 'IN_PROGRESS', 'STAFF'), ('ASSIGNED', 'IN_PROGRESS', 'HEAD'),
    ('ASSIGNED', 'REJECTED', 'STAFF'), ('ASSIGNED', 'REJECTED', 'HEAD'),
    ('REOPENED', 'IN_PROGRESS', 'STAFF'), ('REOPENED', 'IN_PROGRESS', 'HEAD'),
])
def test_core_roles_preserve_unrelated_data_and_record_history_once(case, source, target, role):
    complaint, staff, head, admin = case
    complaint.status = source
    complaint.save(update_fields=['status'])
    actor = {'STAFF': staff, 'HEAD': head, 'ADMIN': admin}[role]
    before = capture(complaint)[0]
    revision = get_transition_revision(actor=actor, complaint_id=complaint.complaint_id, target_state=target)
    assert isinstance(revision, str) and len(revision) == 64
    assert all(character in '0123456789abcdef' for character in revision)
    with patch('workflow.email_delivery.send_mail') as send:
        result = change(actor, complaint, target, revision, '  Synthetic reason  ')
    send.assert_not_called()
    after = capture(complaint)[0]
    assert {k:v for k,v in before.items() if k != 'status'} == {k:v for k,v in after.items() if k != 'status'}
    history = ComplaintHistory.objects.get()
    assert (history.previous_state, history.new_state, history.actor_kind, history.remarks) == (
        source, target, role, 'Synthetic reason')
    assert history.occurred_at and result.history_id == history.pk and result.revision != revision
    assert not hasattr(result, 'description') and not hasattr(result, 'submitted_by')
    if any(field.name == 'actor' for field in ComplaintHistory._meta.fields):
        assert history.actor_id == actor.pk  # PR #68 composition.
    if target == 'IN_PROGRESS':
        event = NotificationEvent.objects.get(history=history)
        assert event.kind == 'STARTED' and event.notices.count() == 3
        assert not EmailDelivery.objects.exists()  # SRS: start is in-app only.
    else:
        assert not NotificationEvent.objects.exists()  # B26 does not invent rejection notices.


@pytest.mark.parametrize('role,source,target', [
    ('STAFF', 'SUBMITTED', 'REJECTED'), ('ADMIN', 'ASSIGNED', 'REJECTED'),
    ('ADMIN', 'ASSIGNED', 'IN_PROGRESS'), ('HEAD', 'IN_PROGRESS', 'RESOLVED'),
    ('ADMIN', 'IN_PROGRESS', 'RESOLVED'), ('STAFF', 'RESOLVED', 'CLOSED'),
    ('HEAD', 'RESOLVED', 'CLOSED'), ('COMPLAINANT', 'ASSIGNED', 'IN_PROGRESS'),
])
def test_roles_do_not_gain_additional_srs_powers(case, role, source, target):
    complaint, staff, head, admin = case
    complaint.status = source
    complaint.save(update_fields=['status'])
    actor = {'STAFF':staff, 'HEAD':head, 'ADMIN':admin, 'COMPLAINANT':complaint.submitted_by}[role]
    before = capture(complaint)
    with pytest.raises((PermissionDenied, Http404)):
        change(actor, complaint, target, _revision(complaint))
    assert capture(complaint) == before


@pytest.mark.parametrize('kind', ['unassigned', 'cross_department', 'inactive', 'anonymous', 'none', 'deleted'])
def test_invalid_objects_and_current_accounts_are_denied(case, kind, user_factory, department_factory):
    complaint, staff, _, _ = case
    actor = staff
    if kind == 'unassigned':
        actor = user_factory(role='STAFF', department=complaint.department)
    elif kind == 'cross_department':
        actor = user_factory(role='HEAD', department=department_factory())
    elif kind == 'inactive':
        User.objects.filter(pk=actor.pk).update(is_active=False)
    elif kind == 'anonymous':
        actor = AnonymousUser()
    elif kind == 'none':
        actor = None
    else:
        actor = User(pk=99999999, role='STAFF')
    before = capture(complaint)
    with pytest.raises((PermissionDenied, Http404)):
        change(actor, complaint, 'IN_PROGRESS', _revision(complaint))
    assert capture(complaint) == before
    assert SecurityEvent.objects.filter(event_type='AUTHORIZATION_REFUSED').count() == 1


def test_current_role_reloaded_and_refusal_log_is_sanitized(case):
    complaint, staff, _, _ = case
    token = get_transition_revision(actor=staff, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    User.objects.filter(pk=staff.pk).update(role='COMPLAINANT')
    before = capture(complaint)
    with pytest.raises(Http404):
        change(staff, complaint, 'IN_PROGRESS', token, reason='SECRET REFERENCE SESSION')
    assert capture(complaint) == before
    assert 'SECRET' not in SecurityEvent.objects.latest('pk').detail


@pytest.mark.parametrize('reason', [None, 1, [], {}, '', '   ', 'x' * 2001])
def test_rejection_reason_required_and_bounded(case, reason):
    complaint, _, head, _ = case
    before = capture(complaint)
    token = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='REJECTED')
    with pytest.raises(LifecycleError):
        change(head, complaint, 'REJECTED', token, reason)
    assert capture(complaint) == before


@pytest.mark.parametrize('reason', ['x', 'x' * 2000])
def test_terminal_rejection_reason_has_no_invented_feedback_minimum(case, reason):
    complaint, _, head, _ = case
    change(head, complaint, 'REJECTED', reason=reason)
    assert ComplaintHistory.objects.get().remarks == reason


@pytest.mark.parametrize('token', ['', 'bad', None, 1, 'a' * 64])
def test_missing_or_invalid_revision_cannot_mutate(case, token):
    complaint, _, head, _ = case
    before = capture(complaint)
    with pytest.raises(ModifiedRecord):
        transition_complaint(actor=head, complaint_id=complaint.complaint_id,
                             target_state='IN_PROGRESS', expected_revision=token)
    assert capture(complaint) == before


def test_successful_action_invalidates_replayed_revision(case):
    complaint, _, head, _ = case
    revision = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    change(head, complaint, 'IN_PROGRESS', revision)
    before = capture(complaint)
    with pytest.raises(ModifiedRecord):
        change(head, complaint, 'IN_PROGRESS', revision)
    assert capture(complaint) == before


@pytest.mark.parametrize('change_kind', ['assignment', 'escalation_history', 'assignment_aba', 'edit'])
def test_same_state_changes_invalidate_revision(case, user_factory, change_kind):
    complaint, staff, head, _ = case
    revision = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    if change_kind in ('assignment', 'assignment_aba'):
        other = user_factory(role='STAFF', department=complaint.department)
        Complaint.objects.filter(pk=complaint.pk).update(assignee=other)
        record_history(complaint.complaint_id, 'REASSIGNED', 'HEAD', 'ASSIGNED', 'ASSIGNED')
        if change_kind == 'assignment_aba':
            Complaint.objects.filter(pk=complaint.pk).update(assignee=staff)
            record_history(complaint.complaint_id, 'REASSIGNED', 'HEAD', 'ASSIGNED', 'ASSIGNED')
    elif change_kind == 'escalation_history':
        record_history(complaint.complaint_id, 'ESCALATED', 'SYSTEM', 'ASSIGNED', 'ASSIGNED')
    else:
        Complaint.objects.filter(pk=complaint.pk).update(title='New synthetic title')
    before = capture(complaint)
    with pytest.raises(ModifiedRecord):
        change(head, complaint, 'IN_PROGRESS', revision)
    assert capture(complaint) == before


@pytest.mark.parametrize('failure', ['history', 'notice', 'later'])
def test_required_failure_rolls_back_state_history_and_notices(case, failure):
    complaint, _, head, _ = case
    record_history(complaint.complaint_id, 'SUBMITTED', 'SYSTEM')
    before = capture(complaint)
    revision = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            if failure == 'later':
                change(head, complaint, 'IN_PROGRESS', revision)
                raise RuntimeError('controlled caller failure')
            target = 'workflow.lifecycle.record_history' if failure == 'history' else 'workflow.notifications.Notification.objects.create'
            with patch(target, side_effect=RuntimeError('controlled required failure')):
                change(head, complaint, 'IN_PROGRESS', revision)
    assert capture(complaint) == before
    assert get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS') == revision


@pytest.mark.parametrize('targets', [('IN_PROGRESS','IN_PROGRESS'), ('IN_PROGRESS','REJECTED')])
def test_competing_actions_have_one_winner_and_one_modified_record(case, targets):
    complaint, _, head, _ = case
    revision = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    barrier = Barrier(2)
    def work(target):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return change(head, complaint, target, revision).new_state
            except ModifiedRecord:
                return 'STALE'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, targets))
    assert results.count('STALE') == 1
    assert ComplaintHistory.objects.count() == 1
    complaint.refresh_from_db()
    assert complaint.status == next(result for result in results if result != 'STALE')


@pytest.mark.parametrize('source', State.values)
def test_owner_edit_guard_all_states(case, source):
    complaint, _, _, _ = case
    complaint.status = source
    complaint.save(update_fields=['status'])
    before = capture(complaint)
    with transaction.atomic():
        if source == 'SUBMITTED':
            assert validate_owner_edit(actor=complaint.submitted_by, complaint_id=complaint.complaint_id) is None
        else:
            with pytest.raises(LifecycleError) as error:
                validate_owner_edit(actor=complaint.submitted_by, complaint_id=complaint.complaint_id)
            assert error.value.code == 'owner_edit_closed'
    assert capture(complaint) == before


def test_owner_edit_guard_requires_transaction_and_owner(case, user_factory):
    complaint, _, _, _ = case
    with pytest.raises(RuntimeError):
        validate_owner_edit(actor=complaint.submitted_by, complaint_id=complaint.complaint_id)
    with transaction.atomic(), pytest.raises(Http404):
        validate_owner_edit(actor=user_factory(), complaint_id=complaint.complaint_id)


def test_missing_complaint_and_unrelated_history(case, complaint_factory):
    complaint, _, head, _ = case
    with pytest.raises(Http404):
        get_transition_revision(actor=head, complaint_id='missing', target_state='IN_PROGRESS')
    revision = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    other = complaint_factory()
    record_history(other.complaint_id, 'SUBMITTED', 'SYSTEM')
    assert get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS') == revision
    change(head, complaint, 'IN_PROGRESS', revision)


@pytest.mark.parametrize('target', ['ESCALATED', '', None, [], {}])
def test_unknown_state_is_not_a_new_lifecycle_state(case, target):
    complaint, _, head, _ = case
    before = capture(complaint)
    with pytest.raises(LifecycleError) as error:
        change(head, complaint, target, _revision(complaint))
    assert error.value.code == 'invalid_transition'
    assert capture(complaint) == before


def test_submillisecond_timestamp_change_invalidates_revision(case):
    from datetime import timedelta

    complaint, _, head, _ = case
    token = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    Complaint.objects.filter(pk=complaint.pk).update(due_at=complaint.due_at + timedelta(microseconds=1))
    with pytest.raises(ModifiedRecord):
        change(head, complaint, 'IN_PROGRESS', token)


def test_anonymous_revision_and_notice_do_not_expose_identity(case, complaint_factory):
    _, _, head, _ = case
    complaint = complaint_factory(anonymous=True, title='SECRET-IDENTITY', department=head.department)
    token = get_transition_revision(actor=head, complaint_id=complaint.complaint_id, target_state='IN_PROGRESS')
    assert len(token) == 64 and token != complaint.reference_digest
    result = change(head, complaint, 'IN_PROGRESS', token)
    assert 'SECRET' not in str(result) and complaint.reference_digest not in str(result)
    event = NotificationEvent.objects.get()
    assert event.anonymous and list(event.notices.values_list('recipient_id', flat=True)) == [head.pk]
    assert not EmailDelivery.objects.exists()
