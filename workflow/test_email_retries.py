"""B27 timing, durable attempts, recovery and sanitized transport evidence."""

import json
import os
import smtplib
import subprocess
import sys
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from accounts.models import User
from workflow.email_delivery import (
    CLAIM_LEASE, RETRY_DELAYS, _begin_send, _claim, _finish, deliver_email, due_delivery_ids,
)
from workflow.history_service import record_history
from workflow.models import EmailAttempt, EmailDelivery, Notification

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def job(complaint_factory):
    complaint = complaint_factory()
    record_history(complaint.complaint_id, "SUBMITTED", "COMPLAINANT", new_state="SUBMITTED")
    return EmailDelivery.objects.get()


def temporary_error():
    return smtplib.SMTPDataError(451, b"Synthetic temporary refusal SECRET recipient@example.test")


def test_three_total_attempts_and_increasing_exact_due_boundaries(job):
    now = timezone.now()
    initial_state = job.notice.event.complaint.status
    with patch("workflow.email_delivery.send_mail", side_effect=temporary_error()) as send:
        for number in range(1, 4):
            expected = "RETRY_WAIT" if number < 3 else "FAILED"
            assert deliver_email(job.pk, now=now) == expected
            job.refresh_from_db()
            assert job.attempt_count == send.call_count == number
            attempt = job.attempts.get(number=number)
            assert attempt.status == "RETRYABLE" and attempt.finished_at == now
            assert attempt.diagnostic_code == "temporary_failure"
            if number < 3:
                assert job.next_attempt_at == now + RETRY_DELAYS[number - 1]
                assert RETRY_DELAYS[1] > RETRY_DELAYS[0] > timedelta(0)
                before = job.next_attempt_at - timedelta(microseconds=1)
                assert deliver_email(job.pk, now=before) == "RETRY_WAIT"
                assert job.pk not in due_delivery_ids(now=before)
                assert job.pk in due_delivery_ids(now=job.next_attempt_at)
                assert send.call_count == number
                now = job.next_attempt_at
    assert job.failure_code == "attempt_limit" and job.next_attempt_at is None
    assert job.attempts.count() == 3
    with patch("workflow.email_delivery.send_mail") as send:
        assert deliver_email(job.pk, now=now + timedelta(days=1)) == "FAILED"
        assert job.pk not in due_delivery_ids(now=now + timedelta(days=1))
    send.assert_not_called()
    job.notice.event.complaint.refresh_from_db()
    assert job.notice.event.complaint.status == initial_state
    assert Notification.objects.filter(pk=job.notice_id).exists()
    output = json.dumps(list(job.attempts.values()), default=str)
    assert "SECRET" not in output and "recipient@example.test" not in output


@pytest.mark.parametrize("success_on", [1, 2, 3])
def test_success_stops_retries_at_each_attempt(job, success_on):
    now = timezone.now()
    outcomes = [temporary_error()] * (success_on - 1) + [1]
    with patch("workflow.email_delivery.send_mail", side_effect=outcomes) as send:
        for number in range(1, success_on + 1):
            assert deliver_email(job.pk, now=now) == ("SENT" if number == success_on else "RETRY_WAIT")
            job.refresh_from_db()
            now = job.next_attempt_at or now
        assert deliver_email(job.pk, now=now + timedelta(days=1)) == "SENT"
    assert send.call_count == success_on and job.attempt_count == success_on
    assert job.sent_at is not None and job.failure_code == "" and job.next_attempt_at is None
    assert job.attempts.last().status == "SENT"


@pytest.mark.parametrize("error,expected,code", [
    (smtplib.SMTPDataError(550, b"SECRET"), "FAILED", "permanent_rejection"),
    (smtplib.SMTPRecipientsRefused({"secret@example.test": (450, b"SECRET")}), "RETRY_WAIT", "temporary_failure"),
    (smtplib.SMTPRecipientsRefused({"secret@example.test": (550, b"SECRET")}), "FAILED", "permanent_rejection"),
    (ConnectionRefusedError("SECRET"), "RETRY_WAIT", "connection_unavailable"),
    (smtplib.SMTPServerDisconnected("SECRET"), "FAILED", "delivery_unknown"),
    (TimeoutError("SECRET"), "FAILED", "delivery_unknown"),
])
def test_transport_classification_never_persists_exception_values(job, error, expected, code):
    with patch("workflow.email_delivery.send_mail", side_effect=error):
        assert deliver_email(job.pk) == expected
    job.refresh_from_db()
    assert job.failure_code == code and job.attempts.get().diagnostic_code == code
    assert "SECRET" not in json.dumps(list(job.attempts.values()), default=str)


def test_expired_claim_is_scheduled_and_stale_owner_is_fenced(job):
    now = timezone.now()
    attempt_id, _ = _claim(job.pk, now)
    assert _begin_send(job.pk, attempt_id, now + CLAIM_LEASE) is None
    job.refresh_from_db()
    assert job.status == "RETRY_WAIT" and job.attempts.get().status == "ABANDONED"
    with patch("workflow.email_delivery.send_mail", return_value=1) as send:
        assert deliver_email(job.pk, now=job.next_attempt_at) == "SENT"
        assert _begin_send(job.pk, attempt_id, job.next_attempt_at) is None
    assert send.call_count == 1 and job.attempts.count() == 2
    assert _finish(job.pk, attempt_id, "SENT", "", now) == "SENT"
    assert job.attempts.get(pk=attempt_id).status == "ABANDONED"


def test_expired_sending_is_not_replayed_and_late_result_can_reconcile(job):
    now = timezone.now()
    attempt_id, _ = _claim(job.pk, now)
    assert _begin_send(job.pk, attempt_id, now) is not None
    expiry = now + CLAIM_LEASE
    assert job.pk not in due_delivery_ids(now=expiry - timedelta(microseconds=1))
    assert job.pk in due_delivery_ids(now=expiry)
    with patch("workflow.email_delivery.send_mail") as send:
        assert deliver_email(job.pk, now=expiry) == "FAILED"
        assert deliver_email(job.pk, now=expiry + timedelta(days=1)) == "FAILED"
    send.assert_not_called()
    assert job.attempts.get().status == "UNKNOWN"
    assert _finish(job.pk, attempt_id, "SENT", "", expiry + timedelta(seconds=1)) == "SENT"
    job.refresh_from_db()
    assert job.status == "SENT" and job.attempts.get().status == "SENT"


@pytest.mark.parametrize("crash_phase", ["claimed", "sending"])
def test_process_death_survives_restart_without_blind_resend(job, crash_phase):
    # A real child exits at a durable boundary. It never opens a network socket.
    target = "_begin_send" if crash_phase == "claimed" else "send_mail"
    script = f'''
import os
os.environ["DJANGO_SETTINGS_MODULE"] = "scms.settings"
import django
django.setup()
from unittest.mock import patch
from workflow.email_delivery import deliver_email
with patch("workflow.email_delivery.{target}", side_effect=lambda *a, **kw: os._exit(23)):
    deliver_email({job.pk})
'''
    env = dict(os.environ, DJANGO_SECRET_KEY="b27-child-test-only",
               DJANGO_DB_PATH=str(connection.settings_dict["NAME"]))
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, timeout=20)
    assert result.returncode == 23
    close_old_connections()
    job.refresh_from_db()
    attempt = job.attempts.get()
    assert job.status == "SENDING"
    expiry = attempt.lease_expires_at
    with patch("workflow.email_delivery.send_mail", return_value=1) as send:
        status = deliver_email(job.pk, now=expiry)
        if crash_phase == "claimed":
            assert status == "RETRY_WAIT"
            job.refresh_from_db()
            assert deliver_email(job.pk, now=job.next_attempt_at) == "SENT"
            assert send.call_count == 1
        else:
            assert status == "FAILED"
            assert deliver_email(job.pk, now=expiry + timedelta(days=1)) == "FAILED"
            send.assert_not_called()
    assert Notification.objects.filter(pk=job.notice_id).exists()


def test_three_abandoned_reservations_exhaust_budget_without_smtp(job):
    now = timezone.now()
    for number in range(1, 4):
        attempt_id, _ = _claim(job.pk, now)
        assert attempt_id is not None
        assert deliver_email(job.pk, now=now + CLAIM_LEASE) == ("RETRY_WAIT" if number < 3 else "FAILED")
        job.refresh_from_db()
        now = job.next_attempt_at or now
    assert job.attempt_count == 3 and job.failure_code == "attempt_limit"
    assert list(job.attempts.values_list("status", flat=True)) == ["ABANDONED"] * 3


def test_revocation_between_claim_and_smtp(job):
    now = timezone.now()
    attempt_id, _ = _claim(job.pk, now)
    User.objects.filter(pk=job.notice.recipient_id).update(is_active=False)
    assert _begin_send(job.pk, attempt_id, now) is None
    job.refresh_from_db()
    assert job.status == "SUPPRESSED" and job.attempts.get().diagnostic_code == "recipient_ineligible"


def test_finalization_db_failure_leaves_recoverable_unknown_outcome(job):
    with patch("workflow.email_delivery.send_mail", return_value=1), patch(
            "workflow.email_delivery._finish", side_effect=RuntimeError("SECRET")):
        with pytest.raises(RuntimeError):
            deliver_email(job.pk)
    job.refresh_from_db()
    assert job.status == "SENDING" and job.attempts.get().status == "SENDING"
    with patch("workflow.email_delivery.send_mail") as send:
        assert deliver_email(job.pk, now=job.attempts.get().lease_expires_at) == "FAILED"
    send.assert_not_called()
    assert Notification.objects.filter(pk=job.notice_id).exists()


def test_retry_worker_command_respects_due_time(job):
    now = timezone.now()
    with patch("workflow.email_delivery.timezone.now", return_value=now):
        with patch("workflow.email_delivery.send_mail", side_effect=temporary_error()):
            call_command("deliver_notifications", stdout=StringIO())
    job.refresh_from_db()
    with patch("workflow.email_delivery.timezone.now", return_value=job.next_attempt_at - timedelta(microseconds=1)):
        with patch("workflow.email_delivery.send_mail") as send:
            call_command("deliver_notifications", stdout=StringIO())
        send.assert_not_called()
    with patch("workflow.email_delivery.timezone.now", return_value=job.next_attempt_at):
        with patch("workflow.email_delivery.send_mail", return_value=1):
            call_command("deliver_notifications", stdout=StringIO())
    assert job.attempts.count() == 2
    job.refresh_from_db()
    assert job.status == "SENT"


def test_worker_sanitizes_database_errors(job):
    out = StringIO()
    with patch("workflow.management.commands.deliver_notifications.deliver_email", side_effect=RuntimeError("SECRET")):
        with pytest.raises(CommandError) as error:
            call_command("deliver_notifications", stdout=out)
    assert "SECRET" not in str(error.value) + out.getvalue()
    with patch("workflow.management.commands.deliver_notifications.due_delivery_ids", side_effect=RuntimeError("SECRET")):
        with pytest.raises(CommandError, match="schedules could not be read"):
            call_command("deliver_notifications", stdout=out)


def test_database_enforces_attempt_budget_and_identity(job):
    now = timezone.now()
    _claim(job.pk, now)
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailAttempt.objects.create(delivery=job, number=1, lease_expires_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailAttempt.objects.create(delivery=job, number=4, lease_expires_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailDelivery.objects.filter(pk=job.pk).update(attempt_count=4)


def test_b26_migration_preserves_old_outcomes_without_resend(complaint_factory):
    from django.db.migrations.executor import MigrationExecutor

    complaint = complaint_factory()
    for _ in range(5):
        record_history(complaint.complaint_id, "SUBMITTED", "COMPLAINANT")
    ids = list(EmailDelivery.objects.order_by("pk").values_list("pk", flat=True))
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    old = [("workflow", "0003_b26_notifications")]
    executor.migrate(old)
    try:
        historical = executor.loader.project_state(old).apps.get_model("workflow", "EmailDelivery")
        for pk, status in zip(ids, ["PENDING", "SENT", "FAILED", "SENDING", "SUPPRESSED"]):
            historical.objects.filter(pk=pk).update(status=status, failure_code="OLD-SECRET")
    finally:
        MigrationExecutor(connection).migrate(latest)
    jobs = list(EmailDelivery.objects.order_by("pk"))
    assert [j.status for j in jobs] == ["PENDING", "SENT", "FAILED", "FAILED", "SUPPRESSED"]
    assert [j.attempt_count for j in jobs] == [0, 1, 1, 1, 0]
    assert [a.status for a in EmailAttempt.objects.order_by("delivery_id")] == ["SENT", "FAILED", "UNKNOWN"]
    assert jobs[2].failure_code == "legacy_failure" and jobs[3].failure_code == "delivery_unknown"
    assert jobs[1].next_attempt_at is jobs[2].next_attempt_at is jobs[3].next_attempt_at is None
    assert Notification.objects.count() == 5
    assert "OLD-SECRET" not in json.dumps(list(EmailDelivery.objects.values()), default=str)


def test_overlapping_workers_send_only_one_retry(job):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    now = timezone.now()
    with patch("workflow.email_delivery.send_mail", side_effect=temporary_error()):
        assert deliver_email(job.pk, now=now) == "RETRY_WAIT"
    job.refresh_from_db()
    due = job.next_attempt_at
    barrier, lock, calls = Barrier(2), Lock(), []

    def send(*args, **kwargs):
        assert not transaction.get_connection().in_atomic_block
        with lock:
            calls.append(1)
        return 1

    def work(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return deliver_email(job.pk, now=due)
        finally:
            close_old_connections()

    with patch("workflow.email_delivery.send_mail", side_effect=send), ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(work, range(2)))
    assert set(statuses) <= {"SENDING", "SENT"} and len(calls) == 1
    job.refresh_from_db()
    assert job.status == "SENT" and job.attempt_count == job.attempts.count() == 2


def test_anonymous_retry_content_and_attempt_records_are_minimal(complaint_factory, user_factory, settings):
    from django.core import mail

    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    complaint = complaint_factory(anonymous=True, title="SECRET-IDENTITY", description="SECRET-SESSION" * 3)
    head = user_factory(role="HEAD", department=complaint.department)
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM", remarks="SECRET-REFERENCE")
    job = EmailDelivery.objects.get(notice__recipient=head)
    with patch("workflow.email_delivery.send_mail", side_effect=temporary_error()):
        assert deliver_email(job.pk) == "RETRY_WAIT"
    job.refresh_from_db()
    assert deliver_email(job.pk, now=job.next_attempt_at) == "SENT"
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [head.email]
    combined = mail.outbox[0].message().as_string() + json.dumps(list(job.attempts.values()), default=str)
    assert "Anonymous" in combined and "SECRET" not in combined
    assert complaint.reference_digest not in combined and "submitted_by" not in combined
    assert Notification.objects.filter(pk=job.notice_id).exists()


def test_revocation_before_retry_prevents_another_reservation(job):
    with patch("workflow.email_delivery.send_mail", side_effect=temporary_error()):
        assert deliver_email(job.pk) == "RETRY_WAIT"
    job.refresh_from_db()
    User.objects.filter(pk=job.notice.recipient_id).update(is_active=False)
    with patch("workflow.email_delivery.send_mail") as send:
        assert deliver_email(job.pk, now=job.next_attempt_at) == "SUPPRESSED"
    send.assert_not_called()
    assert job.attempts.count() == 1


def test_command_recovers_expired_claim_after_restart(job):
    now = timezone.now()
    attempt_id, _ = _claim(job.pk, now)
    with patch("workflow.email_delivery.timezone.now", return_value=now + CLAIM_LEASE):
        with patch("workflow.email_delivery.send_mail") as send:
            call_command("deliver_notifications", stdout=StringIO())
    send.assert_not_called()
    job.refresh_from_db()
    assert job.status == "RETRY_WAIT" and job.attempts.get(pk=attempt_id).status == "ABANDONED"


def test_paused_live_sender_is_not_duplicated_by_recovery(job):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    now = timezone.now()
    entered, release = Event(), Event()
    calls = []

    def send(*args, **kwargs):
        assert not transaction.get_connection().in_atomic_block
        calls.append(1)
        entered.set()
        assert release.wait(timeout=10)
        return 1

    def work():
        close_old_connections()
        try:
            return deliver_email(job.pk, now=now)
        finally:
            close_old_connections()

    with patch("workflow.email_delivery.send_mail", side_effect=send), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(work)
        try:
            assert entered.wait(timeout=10)
            assert deliver_email(job.pk, now=now + CLAIM_LEASE / 2) == "SENDING"
            assert deliver_email(job.pk, now=now + CLAIM_LEASE) == "FAILED"
            assert len(calls) == 1
        finally:
            release.set()
        assert future.result(timeout=10) == "SENT"
    job.refresh_from_db()
    assert job.status == "SENT" and job.attempt_count == 1
    assert job.attempts.get().status == "SENT"
