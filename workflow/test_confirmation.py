"""TC-09 owner confirmation; anonymous B13 is intentionally unavailable."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.http import Http404
from django.test import Client
from django.urls import reverse

from workflow.confirmation_service import confirm_resolution
from workflow.lifecycle import LifecycleError, ModifiedRecord, _revision, get_transition_revision
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def case(complaint_factory, user_factory):
    complaint = complaint_factory(status='RESOLVED', resolution_remarks='Synthetic resolution proof')
    head = user_factory(role='HEAD', department=complaint.department)
    return complaint, complaint.submitted_by, head


def arguments(case):
    complaint, owner, _ = case
    return dict(actor=owner, complaint_id=complaint.complaint_id,
                expected_revision=get_transition_revision(actor=owner,
                    complaint_id=complaint.complaint_id, target_state='CLOSED'))


def snapshot(complaint):
    complaint.refresh_from_db()
    return (complaint.status, complaint.rating, complaint.closed_at,
            *[model.objects.count() for model in
              (ComplaintHistory, NotificationEvent, Notification, EmailDelivery)])


@pytest.mark.parametrize('rating', [None, 1, 2, 3, 4, 5])
def test_owner_closes_with_optional_rating_and_department_notice(case, rating):
    complaint, owner, head = case
    with patch('workflow.email_delivery.send_mail') as send:
        result = confirm_resolution(**arguments(case), rating=rating)
    complaint.refresh_from_db()
    assert complaint.status == 'CLOSED' and complaint.closed_at is not None
    assert complaint.rating == rating and result.new_state == 'CLOSED'
    assert complaint.resolution_remarks == 'Synthetic resolution proof'
    history = ComplaintHistory.objects.get()
    assert (history.event_type, history.actor_kind, history.previous_state, history.new_state) == (
        'STATUS_CHANGED', 'COMPLAINANT', 'RESOLVED', 'CLOSED')
    assert history.remarks == ''
    event = NotificationEvent.objects.get(history=history, kind='CLOSED')
    assert set(event.notices.values_list('recipient_id', flat=True)) == {owner.pk, head.pk}
    assert EmailDelivery.objects.count() == 2
    send.assert_not_called()


@pytest.mark.parametrize('rating', [0, 6, -1, True, False, 1.0, 1.5, '1', '', [], {}])
def test_invalid_domain_rating_is_atomic(case, rating):
    args = arguments(case)
    before = snapshot(case[0])
    with pytest.raises(ValidationError):
        confirm_resolution(**args, rating=rating)
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('state', ['SUBMITTED', 'ASSIGNED', 'IN_PROGRESS', 'REOPENED', 'CLOSED', 'REJECTED'])
def test_only_resolved_can_close(case, state):
    complaint = case[0]
    complaint.status = state
    complaint.save(update_fields=['status'])
    before = snapshot(complaint)
    with pytest.raises(LifecycleError):
        confirm_resolution(actor=case[1], complaint_id=complaint.complaint_id,
                           expected_revision=_revision(complaint))
    assert snapshot(complaint) == before


@pytest.mark.parametrize('kind', ['other', 'head', 'staff', 'admin', 'inactive', 'revoked', 'none'])
def test_wrong_or_revoked_actor_cannot_confirm(case, user_factory, kind):
    complaint, owner, head = case
    args = arguments(case)
    actor = {'head':head, 'none':None}.get(kind, owner)
    if kind in ('other', 'staff', 'admin'):
        actor = user_factory(role={'other':'COMPLAINANT','staff':'STAFF','admin':'ADMIN'}[kind],
                             department=complaint.department if kind == 'staff' else None)
    elif kind in ('inactive', 'revoked'):
        type(owner).objects.filter(pk=owner.pk).update(**(
            {'is_active':False} if kind == 'inactive' else {'role':'ADMIN'}))
    before = snapshot(complaint)
    with pytest.raises((PermissionDenied, Http404)):
        confirm_resolution(**{**args, 'actor':actor})
    assert snapshot(complaint) == before


def test_duplicate_and_stale_actions_leave_no_extra_events(case):
    args = arguments(case)
    confirm_resolution(**args)
    before = snapshot(case[0])
    with pytest.raises(ModifiedRecord):
        confirm_resolution(**args, rating=5)
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('target', ['workflow.lifecycle.record_history',
                                 'workflow.notifications.Notification.objects.create'])
def test_required_failure_rolls_back_closure_metadata_and_notices(case, target):
    args = arguments(case)
    before = snapshot(case[0])
    with patch(target, side_effect=RuntimeError('synthetic failure')):
        with pytest.raises(RuntimeError):
            confirm_resolution(**args, rating=4)
    assert snapshot(case[0]) == before


def test_concurrent_confirmation_accepts_only_once(case):
    args = arguments(case)
    barrier = Barrier(2)
    def work(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                confirm_resolution(**args, rating=3)
                return 'CLOSED'
            except ModifiedRecord:
                return 'STALE'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(work, range(2))) == ['CLOSED', 'STALE']
    assert ComplaintHistory.objects.count() == NotificationEvent.objects.count() == 1


def test_csrf_get_post_redirect_and_closed_detail(case):
    complaint, owner, _ = case
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    url = reverse('workflow:confirm', args=[complaint.complaint_id])
    before = snapshot(complaint)
    response = client.get(url)
    assert response.status_code == 200 and 'no-store' in response.headers['Cache-Control']
    assert snapshot(complaint) == before
    data = {'revision':response.context['form'].initial['revision'], 'rating':'5'}
    assert client.post(url, data).status_code == 403
    data['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
    response = client.post(url, data)
    assert response.status_code == 302
    assert client.get(response.url).status_code == 200
    assert client.post(url, data).status_code == 409


@pytest.mark.parametrize('data', [{'rating':'1.0'}, {'rating':'6'}, {'rating':'true'},
                                 {'rating':'-1'}, {'reference':'a'*32}, {'status':'CLOSED'}])
def test_http_invalid_rating_or_reference_tampering_is_refused(case, client, data):
    client.force_login(case[1])
    url = reverse('workflow:confirm', args=[case[0].complaint_id])
    response = client.get(url)
    before = snapshot(case[0])
    assert client.post(url, {'revision':response.context['form'].initial['revision'], **data}).status_code == 400
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('reference', ['a'*32, 'wrong', ''])
def test_anonymous_reference_cannot_grant_confirmation_or_full_read(complaint_factory, client, reference):
    complaint = complaint_factory(anonymous=True, status='RESOLVED')
    before = snapshot(complaint)
    for route in ('confirm', 'complaint_detail'):
        url = reverse('workflow:'+route, args=[complaint.complaint_id])
        response = client.get(url, {'reference':reference})
        assert response.status_code == 302
        assert complaint.description.encode() not in response.content
    assert client.post(reverse('workflow:confirm', args=[complaint.complaint_id]),
                       {'reference':reference, 'rating':'5'}).status_code == 302
    assert snapshot(complaint) == before


def test_actual_issued_reference_remains_blocked_without_b13(complaint_factory, client):
    from complaints.references import hash_reference
    reference = 'b' * 32
    complaint = complaint_factory(anonymous=True, status='RESOLVED',
                                  reference_digest=hash_reference(reference))
    before = snapshot(complaint)
    with pytest.raises(Http404):
        confirm_resolution(actor=None, complaint_id=complaint.complaint_id,
                           expected_revision=_revision(complaint))
    response = client.post(reverse('workflow:confirm', args=[complaint.complaint_id]),
                           {'reference':reference, 'rating':'4'})
    assert response.status_code == 302
    assert snapshot(complaint) == before


def test_owner_http_can_omit_rating(case, client):
    client.force_login(case[1])
    url = reverse('workflow:confirm', args=[case[0].complaint_id])
    response = client.get(url)
    assert client.post(url, {'revision':response.context['form'].initial['revision']}).status_code == 302
    case[0].refresh_from_db()
    assert case[0].rating is None and case[0].status == 'CLOSED'


def test_other_owner_http_get_and_post_are_concealed(case, client, user_factory):
    args = arguments(case)
    client.force_login(user_factory())
    url = reverse('workflow:confirm', args=[case[0].complaint_id])
    before = snapshot(case[0])
    assert client.get(url).status_code == 404
    assert client.post(url, {'revision':args['expected_revision'], 'rating':'5'}).status_code == 404
    assert snapshot(case[0]) == before


def test_callers_outer_rollback_reverts_confirmation(case):
    from django.db import transaction
    args = arguments(case)
    before = snapshot(case[0])
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            confirm_resolution(**args, rating=4)
            raise RuntimeError('synthetic outer rollback')
    assert snapshot(case[0]) == before
