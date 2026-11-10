"""TC-10 proposed D05 boundaries, repeat safety and competing feedback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.utils import timezone

from workflow.autoclose import auto_close_complaint, run_auto_close
from workflow.confirmation_service import confirm_resolution
from workflow.lifecycle import ModifiedRecord, get_transition_revision
from workflow.models import ComplaintHistory, NotificationEvent
from workflow.reopening_service import reject_resolution
from workflow.test_confirmation import case
from workflow.test_reopening import snapshot

pytestmark = pytest.mark.django_db(transaction=True)


def expired(case):
    now = timezone.now()
    complaint = case[0]
    complaint.resolved_at = now - timedelta(days=7)
    complaint.save(update_fields=['resolved_at'])
    return now


@pytest.mark.parametrize('offset,expected', [(-1,0),(0,1),(1,1)])
def test_before_at_after_exact_deadline(case, offset, expected):
    now = expired(case) + timedelta(microseconds=offset)
    assert run_auto_close(now=now) == expected
    case[0].refresh_from_db()
    assert case[0].status == ('CLOSED' if expected else 'RESOLVED')
    if expected:
        assert case[0].closed_at == now and case[0].rating is None
        history = ComplaintHistory.objects.get()
        assert history.actor_kind == 'SYSTEM' and 'unconfirmed' in history.remarks
        assert history.previous_state == 'RESOLVED' and history.new_state == 'CLOSED'
        assert NotificationEvent.objects.get().notices.filter(recipient=case[2]).exists()


@pytest.mark.parametrize('days', [1,3,14,'2'])
def test_configured_duration(case, settings, days):
    settings.COMPLAINT_AUTO_CLOSE_DAYS = days
    now = timezone.now()
    case[0].resolved_at = now - timedelta(days=int(days))
    case[0].save(update_fields=['resolved_at'])
    assert run_auto_close(now=now) == 1


@pytest.mark.parametrize('days', [0,-1,True,1.5,'1.5','bad',None,36501])
def test_invalid_duration_refused_without_writes(case, settings, days):
    settings.COMPLAINT_AUTO_CLOSE_DAYS = days
    now = expired(case)
    before = snapshot(case[0])
    with pytest.raises(ImproperlyConfigured):
        run_auto_close(now=now)
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('state', ['SUBMITTED','ASSIGNED','IN_PROGRESS','REOPENED','CLOSED','REJECTED'])
def test_other_states_excluded_even_with_expired_resolution(case, state):
    now = expired(case)
    case[0].status = state
    case[0].save(update_fields=['status'])
    before = snapshot(case[0])
    assert run_auto_close(now=now) == 0
    assert auto_close_complaint(case[0].complaint_id, now=now) is None
    assert snapshot(case[0]) == before


def test_missing_resolution_timestamp_excluded(case):
    assert case[0].resolved_at is None
    assert run_auto_close() == 0


def test_repeated_runs_do_not_duplicate_and_preserve_metadata(case):
    now = expired(case)
    original = snapshot(case[0])[0]
    with patch('workflow.email_delivery.send_mail') as send:
        assert run_auto_close(now=now) == 1
        before = snapshot(case[0])
        assert run_auto_close(now=now) == 0
    assert snapshot(case[0]) == before
    case[0].refresh_from_db()
    for key in ('department_id','assignee_id','due_at','reopen_count','resolution_remarks','resolved_at'):
        assert getattr(case[0], key) == original[key]
    send.assert_not_called()


@pytest.mark.parametrize('target', ['workflow.lifecycle.record_history',
                                  'workflow.notifications.Notification.objects.create'])
def test_history_or_notice_failure_rolls_back_closure(case, target):
    now = expired(case)
    before = snapshot(case[0])
    with patch(target, side_effect=RuntimeError('synthetic failure')):
        with pytest.raises(RuntimeError):
            run_auto_close(now=now)
    assert snapshot(case[0]) == before
    assert run_auto_close(now=now) == 1


@pytest.mark.parametrize('count', [0,2])
def test_feedback_first_is_preserved_including_head_review(case, count):
    now = expired(case)
    case[0].reopen_count = count
    case[0].save(update_fields=['reopen_count'])
    token = get_transition_revision(actor=case[1], complaint_id=case[0].complaint_id,
                                    target_state='REOPENED')
    reject_resolution(actor=case[1], complaint_id=case[0].complaint_id,
                      expected_revision=token, reason='Synthetic dissatisfaction reason.')
    before = snapshot(case[0])
    assert run_auto_close(now=timezone.now()) == 0
    assert auto_close_complaint(case[0].complaint_id, now=timezone.now()) is None
    assert snapshot(case[0]) == before


@pytest.mark.parametrize('kind', ['worker','confirm','reject','maximum'])
def test_overlapping_workers_and_feedback_first_transaction_wins(case, kind):
    now = expired(case)
    if kind == 'maximum':
        case[0].reopen_count = 2
        case[0].save(update_fields=['reopen_count'])
    target = 'CLOSED' if kind == 'confirm' else 'REOPENED'
    token = get_transition_revision(actor=case[1], complaint_id=case[0].complaint_id, target_state=target)
    barrier = Barrier(2)
    def work(worker):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if worker or kind == 'worker':
                return 'AUTO' if auto_close_complaint(case[0].complaint_id, now=now) else 'SKIPPED'
            try:
                if kind == 'confirm':
                    confirm_resolution(actor=case[1], complaint_id=case[0].complaint_id,
                                       expected_revision=token, rating=5)
                else:
                    reject_resolution(actor=case[1], complaint_id=case[0].complaint_id,
                                      expected_revision=token, reason='Synthetic dissatisfaction reason.')
                return 'FEEDBACK'
            except ModifiedRecord:
                return 'STALE'
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, [True,False]))
    assert ComplaintHistory.objects.count() == NotificationEvent.objects.count() == 1
    case[0].refresh_from_db()
    if 'FEEDBACK' in results:
        assert case[0].status == {'confirm':'CLOSED','reject':'REOPENED','maximum':'RESOLVED'}[kind]
        assert 'AUTO' not in results
    else:
        assert results.count('AUTO') == 1 and case[0].status == 'CLOSED'


def test_management_command_and_invalid_limit(case):
    expired(case)
    out = StringIO()
    call_command('auto_close_complaints', stdout=out)
    assert 'Automatically closed 1 complaints.' in out.getvalue()
    with pytest.raises(CommandError):
        call_command('auto_close_complaints', limit=0)


def test_head_review_does_not_starve_batch(case, complaint_factory):
    now = expired(case)
    case[0].reopen_count = 2
    case[0].save(update_fields=['reopen_count'])
    reject_resolution(actor=case[1], complaint_id=case[0].complaint_id,
                      expected_revision=get_transition_revision(actor=case[1],
                        complaint_id=case[0].complaint_id, target_state='REOPENED'),
                      reason='Synthetic dissatisfaction reason.')
    other = complaint_factory(status='RESOLVED', resolved_at=now-timedelta(days=7))
    assert run_auto_close(now=timezone.now(), limit=1) == 1
    other.refresh_from_db()
    assert other.status == 'CLOSED'


def test_auto_close_first_refuses_old_feedback_revision(case):
    now = expired(case)
    token = get_transition_revision(actor=case[1], complaint_id=case[0].complaint_id,
                                    target_state='REOPENED')
    assert run_auto_close(now=now) == 1
    before = snapshot(case[0])
    with pytest.raises(ModifiedRecord):
        reject_resolution(actor=case[1], complaint_id=case[0].complaint_id,
                          expected_revision=token, reason='Synthetic dissatisfaction reason.')
    assert snapshot(case[0]) == before


def test_command_failure_is_sanitized(case):
    with patch('workflow.management.commands.auto_close_complaints.run_auto_close',
               side_effect=RuntimeError('PRIVATE DB CONNECTION')):
        with pytest.raises(CommandError) as error:
            call_command('auto_close_complaints')
    assert 'PRIVATE' not in str(error.value)
