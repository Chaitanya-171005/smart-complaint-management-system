"""Real DB/CSRF/privacy/rollback/competition checks for reference feedback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
import json
import re
from urllib.parse import urlencode

import pytest
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.http import Http404
from django.test import Client
from django.utils import timezone

from complaints.checks import check_feedback_privacy
from complaints.models import Complaint
from complaints.references import hash_reference
from complaints.test_tracking import backend, PEER  # noqa: F401
from workflow.checks import check_reopen_policy
from workflow.confirmation_service import confirm_resolution
from workflow.reopening_service import reject_resolution
from workflow.lifecycle import LifecycleError, ModifiedRecord, _revision
from workflow.models import AnonymousResolutionFeedback, ComplaintHistory, EmailDelivery, Notification, NotificationEvent
from workflow.reference_feedback import authorized_feedback_history, reference_feedback_summary, submit_reference_feedback
from workflow.autoclose import auto_close_complaint

pytestmark = pytest.mark.django_db(transaction=True)
REFERENCE = 'a' * 32
REASON = 'The synthetic repair still needs further attention.'
PATH = '/anonymous/feedback/'


@pytest.fixture
def case(complaint_factory, user_factory):
    complaint = complaint_factory(anonymous=True, reference_digest=hash_reference(REFERENCE),
        status='RESOLVED', resolved_at=timezone.now(), resolution_remarks='PRIVATE synthetic repair detail')
    head = user_factory(role='HEAD', department=complaint.department)
    staff = user_factory(role='STAFF', department=complaint.department)
    complaint.assignee = staff
    complaint.save(update_fields=['assignee'])
    return complaint, head, staff


def snapshot(complaint):
    return [list(Complaint.objects.filter(pk=complaint.pk).values()), *[
        list(model.objects.order_by('pk').values()) for model in (
            ComplaintHistory, NotificationEvent, Notification, EmailDelivery, AnonymousResolutionFeedback)]]


def submit(complaint, action='confirm', **kwargs):
    return submit_reference_feedback(reference=REFERENCE, expected_revision=_revision(complaint), action=action, **kwargs)


@pytest.mark.parametrize('rating', [None, 1, 5])
def test_confirm_atomically_closes_and_rates_without_identity(case, rating):
    complaint, head, staff = case
    before = complaint.due_at, complaint.department_id, complaint.assignee_id
    with patch('workflow.email_delivery.send_mail') as send:
        result = submit(complaint, rating=rating)
    complaint.refresh_from_db()
    assert (complaint.status, complaint.rating) == ('CLOSED', rating)
    assert complaint.closed_at is not None
    assert (complaint.due_at, complaint.department_id, complaint.assignee_id) == before
    history = ComplaintHistory.objects.get()
    assert (history.actor_kind, history.actor_id, history.assignee_id, history.remarks) == ('ANONYMOUS', None, None, '')
    assert set(Notification.objects.values_list('recipient_id', flat=True)) == {head.pk, staff.pk}
    assert EmailDelivery.objects.count() == 2
    assert AnonymousResolutionFeedback.objects.get().rating == rating
    assert set(result) == {'complaint_id', 'category', 'location', 'status', 'decision'}
    send.assert_not_called()


@pytest.mark.parametrize('rating', [0, 6, True, 2.5, '4'])
def test_invalid_confirmation_rating_rolls_back(case, rating):
    before = snapshot(case[0])
    with pytest.raises(ValidationError):
        submit(case[0], rating=rating)
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('maximum,count,expected', [(2,0,'REOPEN'), (2,2,'HEAD_REVIEW'), (4,2,'REOPEN'), (0,0,'HEAD_REVIEW')])
def test_rejection_uses_configured_limit_and_retains_protected_reason(case, settings, maximum, count, expected):
    complaint, head, staff = case
    settings.COMPLAINT_MAX_REOPENS = maximum
    complaint.reopen_count = count
    complaint.save(update_fields=['reopen_count'])
    before = complaint.due_at, complaint.assignee_id, complaint.department_id, complaint.escalation_level
    result = submit(complaint, action='reject', reason=REASON)
    complaint.refresh_from_db()
    assert result['decision'] == expected
    assert complaint.status == ('REOPENED' if expected == 'REOPEN' else 'RESOLVED')
    assert complaint.reopen_count == count + (expected == 'REOPEN')
    assert (complaint.due_at, complaint.assignee_id, complaint.department_id, complaint.escalation_level) == before
    record = AnonymousResolutionFeedback.objects.get()
    assert record.reason == REASON and record.rating is None
    assert ComplaintHistory.objects.get().remarks == ''
    assert Notification.objects.filter(recipient=head).exists()
    assert REASON not in str(list(NotificationEvent.objects.values()))


@pytest.mark.parametrize('reason', ['', 'x'*19, 'x'*2001, ' '*30, 'x'*19+'\u200b', REFERENCE, 'x'*20+'\x00', None])
def test_invalid_or_credential_bearing_rejection_never_persists(case, reason):
    before = snapshot(case[0])
    with pytest.raises(ValidationError):
        submit(case[0], action='reject', reason=reason)
    assert snapshot(case[0]) == before


def credential_variant(value, variant):
    if variant == 'upper':
        return value.upper()
    if variant == 'mixed':
        return ''.join(char.upper() if index % 2 else char for index, char in enumerate(value))
    return value


@pytest.mark.parametrize('maximum', [0, 2], ids=['head-review', 'reopen'])
@pytest.mark.parametrize('secret', ['reference', 'digest'])
@pytest.mark.parametrize('variant', ['lower', 'upper', 'mixed'])
def test_case_variant_credentials_are_rejected_atomically(case, settings, maximum, secret, variant):
    complaint = case[0]
    settings.COMPLAINT_MAX_REOPENS = maximum
    value = REFERENCE if secret == 'reference' else complaint.reference_digest
    reason = REASON + ' Reference material: ' + credential_variant(value, variant)
    before = snapshot(complaint)
    with patch('workflow.email_delivery.send_mail') as send:
        with pytest.raises(ValidationError) as failure:
            submit(complaint, action='reject', reason=reason)
    assert failure.value.code == 'invalid_reason'
    assert snapshot(complaint) == before
    send.assert_not_called()


@pytest.mark.parametrize('value', [-1, 32768, True, '2', None])
def test_invalid_policy_is_reported_and_rejection_refused(case, settings, value):
    settings.COMPLAINT_MAX_REOPENS = value
    assert check_reopen_policy(None)[0].id == 'workflow.E001'
    before = snapshot(case[0])
    with pytest.raises(ValidationError):
        submit(case[0], action='reject', reason=REASON)
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('reference', ['b'*32, 'bad', '', None, 'A'*32, 'SCMS-2026-000001'])
def test_unknown_and_malformed_do_not_authorize_any_action(case, reference):
    before = snapshot(case[0])
    assert reference_feedback_summary(reference) is None
    assert submit_reference_feedback(reference=reference, expected_revision=_revision(case[0]), action='confirm') is None
    assert snapshot(case[0]) == before


def test_authenticated_record_and_account_owner_api_cannot_be_reached_by_reference(case, complaint_factory):
    owned = complaint_factory(status='RESOLVED')
    assert reference_feedback_summary(owned.complaint_id) is None
    with pytest.raises((Http404, PermissionDenied)):
        confirm_resolution(actor=case[1], complaint_id=case[0].complaint_id, expected_revision=_revision(case[0]))


@pytest.mark.parametrize('state', ['SUBMITTED','ASSIGNED','IN_PROGRESS','REOPENED','CLOSED','REJECTED'])
def test_only_resolved_accepts_feedback(case, state):
    complaint = case[0]
    complaint.status = state
    complaint.save(update_fields=['status'])
    assert reference_feedback_summary(REFERENCE)['revision'] is None
    before = snapshot(complaint)
    with pytest.raises(LifecycleError):
        submit(complaint)
    assert snapshot(complaint) == before


def test_stale_or_replayed_action_cannot_duplicate(case):
    complaint = case[0]
    revision = _revision(complaint)
    submit(complaint)
    before = snapshot(complaint)
    with pytest.raises(ModifiedRecord):
        submit_reference_feedback(reference=REFERENCE, expected_revision=revision, action='confirm')
    assert snapshot(complaint) == before


@pytest.mark.parametrize('target', ['workflow.notifications.Notification.objects.bulk_create',
                                  'workflow.reference_feedback.AnonymousResolutionFeedback.objects.create'])
def test_required_feedback_or_notification_failure_rolls_back_complete_graph(case, target):
    before = snapshot(case[0])
    with patch(target, side_effect=RuntimeError('synthetic persistence failure')):
        with pytest.raises(RuntimeError):
            submit(case[0], action='reject', reason=REASON)
    assert snapshot(case[0]) == before


def test_competing_confirm_and_reject_accept_exactly_one(case):
    barrier = Barrier(2)
    revision = _revision(case[0])
    def act(action):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                submit_reference_feedback(reference=REFERENCE, expected_revision=revision, action=action,
                                          reason=REASON if action == 'reject' else '')
                return 'accepted'
            except ModifiedRecord:
                return 'stale'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(act, ['confirm','reject']))
    assert sorted(results) == ['accepted','stale']
    assert AnonymousResolutionFeedback.objects.count() == ComplaintHistory.objects.count() == 1


@pytest.fixture
def http(backend, settings):
    settings.ANONYMOUS_FEEDBACK_ENABLED = True
    client = Client(enforce_csrf_checks=True)
    response = client.get(PATH, secure=True, REMOTE_ADDR=PEER)
    assert response.status_code == 200
    token = client.cookies['csrftoken'].value
    def post(data, **headers):
        return client.post(PATH, urlencode({'csrfmiddlewaretoken': token, **data}),
                           content_type='application/x-www-form-urlencoded', secure=True,
                           REMOTE_ADDR=PEER, HTTP_ORIGIN=headers.pop('HTTP_ORIGIN','https://testserver'), **headers)
    return client, post


def test_normal_csrf_lookup_then_feedback_never_echoes_reference_or_private_data(case, http):
    client, post = http
    lookup = post({'reference':REFERENCE,'action':'lookup'})
    assert lookup.status_code == 200
    assert lookup['Referrer-Policy'] == 'same-origin'
    assert REFERENCE.encode() not in lookup.content
    assert b'PRIVATE' not in lookup.content
    revision = lookup.context['summary']['revision']
    response = post({'reference':REFERENCE,'action':'confirm','revision':revision,'rating':'5'})
    assert response.status_code == 200 and response.context['result']['decision'] == 'CONFIRM'
    assert response['Referrer-Policy'] == 'no-referrer'
    assert 'no-store' in response['Cache-Control']
    assert REFERENCE.encode() not in response.content
    assert REFERENCE not in json.dumps(list(AnonymousResolutionFeedback.objects.values()), default=str)
    assert 'sessionid' not in response.cookies


@pytest.mark.parametrize('maximum', [0, 2], ids=['head-review', 'reopen'])
@pytest.mark.parametrize('secret', ['reference', 'digest'])
@pytest.mark.parametrize('variant', ['lower', 'upper', 'mixed'])
def test_http_case_variant_credentials_never_reach_department_output(case, http, settings, maximum, secret, variant):
    complaint, head, staff = case
    settings.COMPLAINT_MAX_REOPENS = maximum
    client, post = http
    value = REFERENCE if secret == 'reference' else complaint.reference_digest
    reason = REASON + ' Reference material: ' + credential_variant(value, variant)
    lookup = post({'reference': REFERENCE, 'action': 'lookup'})
    assert lookup.status_code == 200
    before = snapshot(complaint)
    response = post({'reference': REFERENCE, 'action': 'reject',
                     'revision': lookup.context['summary']['revision'], 'reason': reason})
    assert response.status_code == 400
    assert snapshot(complaint) == before
    assert 'no-store' in response['Cache-Control']
    outputs = [response.content.decode()]
    for reader in (head, staff):
        department_client = Client()
        department_client.force_login(reader)
        visible = department_client.get(
            f'/complaints/{complaint.complaint_id}/resolution-feedback/', secure=True)
        assert visible.status_code == 200
        outputs.append(visible.content.decode())
    for output in outputs:
        assert REFERENCE.casefold() not in output.casefold()
        assert complaint.reference_digest.casefold() not in output.casefold()
        assert reason not in output


def test_reason_retained_only_for_authorized_department_readers(case, http, user_factory):
    client, post = http
    submit(case[0], action='reject', reason='<script>synthetic uncorrected repair</script>')
    path = f'/complaints/{case[0].complaint_id}/resolution-feedback/'
    assert client.get(path, secure=True).status_code == 302
    client.force_login(case[1])
    allowed = client.get(path, secure=True)
    assert allowed.status_code == 200 and b'&lt;script&gt;' in allowed.content
    assert b'<script>' not in allowed.content
    client.force_login(user_factory(role='HEAD'))
    assert client.get(path, secure=True).status_code == 404
    client.force_login(user_factory(role='ADMIN'))
    assert client.get(path, secure=True).status_code == 404


@pytest.mark.parametrize('origin,csrf', [('null',True),('https://evil.example.test',True),('https://testserver',False)])
def test_csrf_failures_never_modify(case, http, origin, csrf):
    client, _ = http
    before = snapshot(case[0])
    data = {'reference':REFERENCE,'action':'lookup'}
    if csrf:
        data['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
    response = client.post(PATH, urlencode(data), content_type='application/x-www-form-urlencoded',
                           secure=True, REMOTE_ADDR=PEER, HTTP_ORIGIN=origin)
    assert response.status_code == 403
    assert snapshot(case[0]) == before


def test_shared_reference_limit_covers_tracking_and_feedback(case, http):
    client, post = http
    for _ in range(5):
        assert post({'reference':'b'*32,'action':'lookup'}).status_code == 200
        assert client.post('/anonymous/track/', urlencode({'reference':'b'*32,'csrfmiddlewaretoken':client.cookies['csrftoken'].value}),
                           content_type='application/x-www-form-urlencoded', secure=True,
                           REMOTE_ADDR=PEER, HTTP_ORIGIN='https://testserver').status_code == 200
    assert post({'reference':REFERENCE,'action':'lookup'}).status_code == 429
    assert not AnonymousResolutionFeedback.objects.exists()


def test_signed_in_browser_is_not_linked_to_reference_action(case, http, user_factory):
    client, post = http
    user = user_factory()
    client.force_login(user)
    sessions = list(Session.objects.values())
    response = post({'reference':REFERENCE,'action':'confirm','revision':_revision(case[0])})
    assert response.status_code == 200
    assert list(Session.objects.values()) == sessions
    assert 'sessionid' not in response.cookies
    assert ComplaintHistory.objects.get().actor_id is None


def test_disabled_gate_and_unverified_transport_refuse(case, http, settings):
    client, post = http
    settings.ANONYMOUS_FEEDBACK_ENABLED = False
    assert post({'reference':REFERENCE,'action':'lookup'}).status_code == 503
    settings.ANONYMOUS_FEEDBACK_ENABLED = True
    settings.ANONYMOUS_TRANSPORT_VERIFIED = False
    assert check_feedback_privacy(None)[0].id == 'complaints.E004'
    assert post({'reference':REFERENCE,'action':'lookup'}).status_code == 503


def test_unknown_and_malformed_http_are_indistinguishable(case, http):
    _, post = http
    mask = lambda value: re.sub(rb'value="[A-Za-z0-9]{64}"', b'value="CSRF"', value)
    a = post({'reference':'b'*32,'action':'lookup'})
    b = post({'reference':'malformed','action':'lookup'})
    assert a.status_code == b.status_code == 200
    assert mask(a.content) == mask(b.content)


@pytest.mark.parametrize('extra', [{'complaint_id':'SCMS-2099-000001'},{'actor':'ADMIN'},{'action':'CONFIRM'}])
def test_client_cannot_supply_authority_or_an_unlisted_action(case, http, extra):
    _, post = http
    before = snapshot(case[0])
    response = post({'reference':REFERENCE,'action':'confirm','revision':_revision(case[0]),**extra})
    assert response.status_code == 400
    assert snapshot(case[0]) == before


def test_recorded_feedback_is_immutable(case):
    submit(case[0])
    row = AnonymousResolutionFeedback.objects.get()
    for operation in (lambda: row.save(), lambda: row.delete(),
                      lambda: AnonymousResolutionFeedback.objects.update(rating=1),
                      lambda: AnonymousResolutionFeedback.objects.all().delete()):
        with pytest.raises(ValidationError):
            operation()


def test_head_review_feedback_prevents_automatic_closure(case):
    complaint = case[0]
    complaint.reopen_count = 2
    complaint.resolved_at = timezone.now() - timedelta(days=8)
    complaint.save(update_fields=['reopen_count','resolved_at'])
    submit(complaint, action='reject', reason=REASON)
    before = snapshot(complaint)
    assert auto_close_complaint(complaint.complaint_id) is None
    assert snapshot(complaint) == before


def test_automatic_closure_first_fences_reference_feedback(case):
    complaint = case[0]
    complaint.resolved_at = timezone.now() - timedelta(days=8)
    complaint.save(update_fields=['resolved_at'])
    revision = _revision(complaint)
    assert auto_close_complaint(complaint.complaint_id) is not None
    before = snapshot(complaint)
    with pytest.raises(ModifiedRecord):
        submit_reference_feedback(reference=REFERENCE, expected_revision=revision, action='reject', reason=REASON)
    assert snapshot(complaint) == before


def test_tracking_form_preserves_native_same_origin_csrf(http):
    client, _ = http
    response = client.get('/anonymous/track/', secure=True, REMOTE_ADDR=PEER)
    assert response.status_code == 200 and response['Referrer-Policy'] == 'same-origin'
    assert 'no-store' in response['Cache-Control']


def test_duplicate_fields_and_oversized_body_are_refused_before_mutation(case, http):
    client, _ = http
    before = snapshot(case[0])
    token = client.cookies['csrftoken'].value
    body = urlencode([('reference',REFERENCE),('reference','b'*32),('csrfmiddlewaretoken',token)])
    assert client.post(PATH, body, content_type='application/x-www-form-urlencoded', secure=True,
                       REMOTE_ADDR=PEER, HTTP_ORIGIN='https://testserver').status_code == 400
    body = urlencode({'reference':REFERENCE,'csrfmiddlewaretoken':token,'reason':'x'*32768})
    assert client.post(PATH, body, content_type='application/x-www-form-urlencoded', secure=True,
                       REMOTE_ADDR=PEER, HTTP_ORIGIN='https://testserver').status_code == 400
    assert snapshot(case[0]) == before


def test_account_rejection_uses_the_same_configurable_limit(settings, complaint_factory):
    settings.COMPLAINT_MAX_REOPENS = 4
    complaint = complaint_factory(status='RESOLVED', reopen_count=2)
    reject_resolution(actor=complaint.submitted_by, complaint_id=complaint.complaint_id,
                      expected_revision=_revision(complaint), reason=REASON)
    complaint.refresh_from_db()
    assert (complaint.status, complaint.reopen_count) == ('REOPENED', 3)


def test_revision_from_another_reference_does_not_authorize_action(case, complaint_factory):
    other = complaint_factory(anonymous=True, reference_digest=hash_reference('b'*32), status='RESOLVED')
    before = snapshot(case[0])
    with pytest.raises(ModifiedRecord):
        submit_reference_feedback(reference=REFERENCE, expected_revision=_revision(other), action='confirm')
    assert snapshot(case[0]) == before


def test_department_membership_revocation_applies_to_feedback_reader(case, user_factory):
    head = case[1]
    user_factory(role='HEAD')
    type(head).objects.filter(pk=head.pk).update(is_active=False)
    with pytest.raises(Http404):
        authorized_feedback_history(actor=head, complaint_id=case[0].complaint_id)
