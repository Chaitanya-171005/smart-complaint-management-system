"""TC-09 rejection, two-reopen maximum, atomic feedback and owner scope."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, transaction
from django.http import Http404
from django.test import Client
from django.urls import reverse

from workflow.lifecycle import LifecycleError, ModifiedRecord, _revision, get_transition_revision
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent
from workflow.reopening_service import reject_resolution
from workflow.test_confirmation import case

pytestmark = pytest.mark.django_db(transaction=True)
REASON = 'Synthetic unresolved problem needs attention.'


def args(case):
    complaint, owner, _ = case
    return dict(actor=owner, complaint_id=complaint.complaint_id, reason=REASON,
                expected_revision=get_transition_revision(actor=owner,
                    complaint_id=complaint.complaint_id, target_state='REOPENED'))


def snapshot(complaint):
    complaint.refresh_from_db()
    return (type(complaint).objects.filter(pk=complaint.pk).values().get(),
            *[list(model.objects.order_by('pk').values()) for model in
              (ComplaintHistory, NotificationEvent, Notification, EmailDelivery)])


@pytest.mark.parametrize('count', [0, 1, 2, 3])
def test_reopen_or_escalate_at_limit_without_changing_assignment_or_due(case, count):
    complaint, owner, head = case
    complaint.reopen_count = count
    complaint.save(update_fields=['reopen_count'])
    original = snapshot(complaint)[0]
    with patch('workflow.email_delivery.send_mail') as send:
        result = reject_resolution(**args(case))
    complaint.refresh_from_db()
    assert complaint.reopen_count == (count + 1 if count < 2 else count)
    assert complaint.status == ('REOPENED' if count < 2 else 'RESOLVED')
    assert result.new_state == complaint.status
    for key in ('department_id','assignee_id','due_at','resolved_at','resolution_remarks',
                'rating','closed_at','is_escalated','escalation_level'):
        assert getattr(complaint, key) == original[key]
    history = ComplaintHistory.objects.get()
    assert history.remarks == REASON and history.actor_kind == 'COMPLAINANT'
    assert history.previous_state == 'RESOLVED' and history.new_state == complaint.status
    event = NotificationEvent.objects.get(history=history)
    assert event.kind == ('REOPENED' if count < 2 else 'ESCALATED')
    assert event.notices.filter(recipient=head).exists()
    assert event.notices.filter(recipient=owner).exists()
    assert REASON not in str(list(NotificationEvent.objects.values()))
    send.assert_not_called()


@pytest.mark.parametrize('reason', ['', ' '*30, 'x'*19, 'x'*2001, None, 42, 'x'*20+'\x00'])
def test_invalid_reason_leaves_everything_unchanged(case, reason):
    arguments = args(case)
    before = snapshot(case[0])
    with pytest.raises(ValidationError):
        reject_resolution(**{**arguments, 'reason':reason})
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('length', [20, 2000])
def test_reason_boundaries_are_trimmed_and_retained(case, length):
    reject_resolution(**{**args(case), 'reason':'  '+'x'*length+'  '})
    assert ComplaintHistory.objects.get().remarks == 'x'*length


@pytest.mark.parametrize('state', ['SUBMITTED','ASSIGNED','IN_PROGRESS','REOPENED','CLOSED','REJECTED'])
def test_wrong_state_refused(case, state):
    complaint = case[0]
    complaint.status = state
    complaint.save(update_fields=['status'])
    before = snapshot(complaint)
    with pytest.raises(LifecycleError):
        reject_resolution(actor=case[1], complaint_id=complaint.complaint_id,
                          expected_revision=_revision(complaint), reason=REASON)
    assert snapshot(complaint) == before


@pytest.mark.parametrize('kind', ['other','head','staff','admin','inactive','revoked','none'])
def test_wrong_actor_leaves_aggregate_unchanged(case, user_factory, kind):
    arguments = args(case)
    actor = case[1]
    if kind == 'head':
        actor = case[2]
    elif kind == 'none':
        actor = None
    elif kind in ('other','staff','admin'):
        actor = user_factory(role={'other':'COMPLAINANT','staff':'STAFF','admin':'ADMIN'}[kind],
                             department=case[0].department if kind == 'staff' else None)
    else:
        type(actor).objects.filter(pk=actor.pk).update(**(
            {'is_active':False} if kind == 'inactive' else {'role':'ADMIN'}))
    before = snapshot(case[0])
    with pytest.raises((Http404, PermissionDenied)):
        reject_resolution(**{**arguments, 'actor':actor})
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('count,target', [
    (0, 'workflow.lifecycle.record_history'),
    (2, 'workflow.reopening_service.record_history'),
    (0, 'workflow.notifications.Notification.objects.create'),
    (2, 'workflow.notifications.Notification.objects.create'),
])
def test_rollback_including_maximum_escalation(case, count, target):
    complaint = case[0]
    complaint.reopen_count = count
    complaint.save(update_fields=['reopen_count'])
    arguments = args(case)
    before = snapshot(complaint)
    with patch(target, side_effect=RuntimeError('synthetic required failure')):
        with pytest.raises(RuntimeError):
            reject_resolution(**arguments)
    assert snapshot(complaint) == before


@pytest.mark.parametrize('count', [0,2])
def test_duplicate_and_concurrent_feedback_is_accepted_once(case, count):
    complaint = case[0]
    complaint.reopen_count = count
    complaint.save(update_fields=['reopen_count'])
    arguments = args(case)
    barrier = Barrier(2)
    def work(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                reject_resolution(**arguments)
                return 'ACCEPTED'
            except ModifiedRecord:
                return 'STALE'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(work, range(2))) == ['ACCEPTED','STALE']
    before = snapshot(complaint)
    with pytest.raises(ModifiedRecord):
        reject_resolution(**arguments)
    assert snapshot(complaint) == before


def test_outer_rollback_and_prior_reason_retention(case):
    arguments = args(case)
    before = snapshot(case[0])
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            reject_resolution(**arguments)
            raise RuntimeError('synthetic outer failure')
    assert snapshot(case[0]) == before
    reject_resolution(**arguments)
    case[0].status = 'RESOLVED'
    case[0].save(update_fields=['status'])
    reject_resolution(**{**args(case), 'reason':'A second independent unsatisfactory resolution.'})
    assert list(ComplaintHistory.objects.values_list('remarks', flat=True)) == [
        REASON, 'A second independent unsatisfactory resolution.']
    case[0].refresh_from_db()
    assert case[0].reopen_count == 2


def test_csrf_read_only_get_form_redirect_and_tampering(case):
    complaint, owner, _ = case
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    url = reverse('workflow:reject_resolution', args=[complaint.complaint_id])
    before = snapshot(complaint)
    response = client.get(url)
    assert response.status_code == 200 and 'no-store' in response.headers['Cache-Control']
    assert snapshot(complaint) == before
    data = {'revision':response.context['form'].initial['revision'], 'reason':REASON}
    assert client.post(url, data).status_code == 403
    data['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
    assert client.post(url, {**data,'reference':'a'*32}).status_code == 400
    assert client.post(url, {**data,'reason':'short'}).status_code == 400
    assert snapshot(complaint) == before
    response = client.post(url, data)
    assert response.status_code == 302 and client.get(response.url).status_code == 200
    assert client.post(url, data).status_code == 409


def test_anonymous_reference_and_other_owner_cannot_reject(case, client, user_factory, complaint_factory):
    from complaints.references import hash_reference
    reference = 'c'*32
    anonymous = complaint_factory(anonymous=True, status='RESOLVED',
                                  reference_digest=hash_reference(reference))
    before = snapshot(anonymous)
    url = reverse('workflow:reject_resolution', args=[anonymous.complaint_id])
    assert client.post(url, {'reference':reference,'reason':REASON}).status_code == 302
    client.force_login(user_factory())
    assert client.get(url, {'reference':reference}).status_code == 404
    assert client.post(url, {'reference':reference,'reason':REASON}).status_code == 404
    assert snapshot(anonymous) == before
    owner_url = reverse('workflow:reject_resolution', args=[case[0].complaint_id])
    assert client.get(owner_url).status_code == 404
