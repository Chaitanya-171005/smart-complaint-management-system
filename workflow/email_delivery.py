"""B27 bounded retries, fenced claims and conservative SMTP crash recovery."""

import smtplib
import socket
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import connection, transaction
from django.db.models import F, Q
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from accounts.models import User
from complaints.models import Complaint
from workflow.models import EmailAttempt, EmailDelivery
from workflow.notifications import eligible_recipient

# User-authorized policy: THREE TOTAL reservations, not initial + three retries.
MAX_ATTEMPTS = 3
RETRY_DELAYS = (timedelta(seconds=60), timedelta(seconds=300))
CLAIM_LEASE = timedelta(minutes=5)


def _recipient(job):
    event = job.notice.event
    user = User.objects.get(pk=job.notice.recipient_id)
    complaint = Complaint.objects.get(pk=event.complaint_id)
    if not user.email or not eligible_recipient(user, complaint, event.kind):
        return None
    return event, user.email


def _outcome(job, attempt, outcome, code, now):
    """Caller holds the delivery lock; diagnostics are static codes only."""
    attempt.status = outcome
    attempt.diagnostic_code = code
    attempt.finished_at = now
    attempt.save(update_fields=["status", "diagnostic_code", "finished_at"])
    job.next_attempt_at = None
    job.failure_code = code
    if outcome == EmailAttempt.Status.SENT:
        job.status, job.sent_at = EmailDelivery.Status.SENT, now
    elif outcome in (EmailAttempt.Status.RETRYABLE, EmailAttempt.Status.ABANDONED):
        if job.attempt_count < MAX_ATTEMPTS:
            job.status = EmailDelivery.Status.RETRY_WAIT
            job.next_attempt_at = now + RETRY_DELAYS[job.attempt_count - 1]
        else:
            job.status, job.failure_code = EmailDelivery.Status.FAILED, "attempt_limit"
    else:
        job.status = EmailDelivery.Status.FAILED
    job.save(update_fields=["status", "next_attempt_at", "failure_code", "sent_at"])
    return job.status


def _recover(job, now):
    attempt = job.attempts.get(number=job.attempt_count)
    if attempt.lease_expires_at > now:
        return job.status
    if attempt.status == EmailAttempt.Status.CLAIMED:
        # The old worker must pass _begin_send's fence before touching SMTP.
        return _outcome(job, attempt, EmailAttempt.Status.ABANDONED, "worker_expired", now)
    # Never resend an expired in-flight attempt: acceptance may already have
    # happened. A late worker may still finalize this same attempt, but no new
    # worker may send it again merely because its lease expired.
    return _outcome(job, attempt, EmailAttempt.Status.UNKNOWN, "delivery_unknown", now)


@transaction.atomic
def _claim(delivery_id, now):
    job = EmailDelivery.objects.select_for_update().get(pk=delivery_id)
    if job.status == EmailDelivery.Status.SENDING:
        return None, _recover(job, now)
    if job.status not in (EmailDelivery.Status.PENDING, EmailDelivery.Status.RETRY_WAIT):
        return None, job.status
    if job.next_attempt_at is None or job.next_attempt_at > now:
        return None, job.status
    if job.attempt_count >= MAX_ATTEMPTS:
        job.status, job.failure_code, job.next_attempt_at = EmailDelivery.Status.FAILED, "attempt_limit", None
        job.save(update_fields=["status", "failure_code", "next_attempt_at"])
        return None, job.status
    if _recipient(job) is None:
        job.status, job.next_attempt_at = EmailDelivery.Status.SUPPRESSED, None
        job.save(update_fields=["status", "next_attempt_at"])
        return None, job.status
    job.attempt_count += 1
    attempt = EmailAttempt.objects.create(delivery=job, number=job.attempt_count,
                                         started_at=now, lease_expires_at=now + CLAIM_LEASE)
    job.status, job.started_at, job.next_attempt_at = EmailDelivery.Status.SENDING, now, None
    job.save(update_fields=["attempt_count", "status", "started_at", "next_attempt_at"])
    return attempt.pk, job.status


@transaction.atomic
def _begin_send(delivery_id, attempt_id, now):
    job = EmailDelivery.objects.select_for_update().get(pk=delivery_id)
    attempt = job.attempts.get(pk=attempt_id)
    if (job.status != EmailDelivery.Status.SENDING or job.attempt_count != attempt.number
            or attempt.status != EmailAttempt.Status.CLAIMED):
        return None
    if attempt.lease_expires_at <= now:
        _recover(job, now)
        return None
    recipient = _recipient(job)  # Recheck changes since the claim transaction.
    if recipient is None:
        _outcome(job, attempt, EmailAttempt.Status.FAILED, "recipient_ineligible", now)
        job.status = EmailDelivery.Status.SUPPRESSED
        job.save(update_fields=["status"])
        return None
    try:
        validate_email(recipient[1])
    except ValidationError:
        _outcome(job, attempt, EmailAttempt.Status.FAILED, "invalid_address", now)
        return None
    attempt.status = EmailAttempt.Status.SENDING
    attempt.save(update_fields=["status"])
    return recipient


def _classify(error):
    # Explicit negative SMTP responses prove non-acceptance; their values may
    # include addresses/secrets, so inspect only numeric codes and never log them.
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        codes = [value[0] for value in error.recipients.values()]
        temporary = bool(codes) and all(isinstance(code, int) and 400 <= code < 500 for code in codes)
        return (EmailAttempt.Status.RETRYABLE, "temporary_failure") if temporary else (
            EmailAttempt.Status.FAILED, "permanent_rejection")
    if isinstance(error, smtplib.SMTPResponseException):
        return (EmailAttempt.Status.RETRYABLE, "temporary_failure") if 400 <= error.smtp_code < 500 else (
            EmailAttempt.Status.FAILED, "permanent_rejection")
    if isinstance(error, (ConnectionRefusedError, socket.gaierror)):
        return EmailAttempt.Status.RETRYABLE, "connection_unavailable"
    # Disconnects/timeouts/arbitrary backend errors can occur AFTER acceptance.
    return EmailAttempt.Status.UNKNOWN, "delivery_unknown"


@transaction.atomic
def _finish(delivery_id, attempt_id, outcome, code, now):
    job = EmailDelivery.objects.select_for_update().get(pk=delivery_id)
    attempt = job.attempts.get(pk=attempt_id)
    active = job.status == EmailDelivery.Status.SENDING and attempt.status == EmailAttempt.Status.SENDING
    late = (job.status == EmailDelivery.Status.FAILED and job.failure_code == "delivery_unknown"
            and attempt.status == EmailAttempt.Status.UNKNOWN)
    if job.attempt_count != attempt.number or not (active or late):
        return job.status
    return _outcome(job, attempt, outcome, code, now)


def deliver_email(delivery_id, *, now=None):
    """Process one due attempt or expired claim; no sleep or inline retry loop.

    All claims/attempts commit before SMTP, which runs outside every business
    transaction. ``now`` is an internal clock override for deterministic tests.
    """
    if connection.in_atomic_block:
        raise TransactionManagementError("Run email delivery outside business transactions.")
    attempt_id, status = _claim(delivery_id, now or timezone.now())
    if attempt_id is None:
        return status
    recipient = _begin_send(delivery_id, attempt_id, now or timezone.now())
    if recipient is None:
        return EmailDelivery.objects.get(pk=delivery_id).status
    event, address = recipient
    try:
        subject = f"SCMS {event.get_kind_display()}: {event.public_id}"
        body = f"Complaint: {event.public_id}\nStatus: {event.status}\n"
        if event.anonymous:
            body += "Complainant: Anonymous\n"
        sent = send_mail(subject, body, None, [address], using="default", fail_silently=False)
        if sent == 1:
            outcome, code = EmailAttempt.Status.SENT, ""
        else:
            outcome, code = EmailAttempt.Status.RETRYABLE, "not_accepted"
    except Exception as error:
        outcome, code = _classify(error)
    return _finish(delivery_id, attempt_id, outcome, code, now or timezone.now())


def due_delivery_ids(*, now=None, limit=100):
    """Persistent schedules survive worker exit; include expired claim recovery."""
    clock = now or timezone.now()
    eligible = Q(status__in=[EmailDelivery.Status.PENDING, EmailDelivery.Status.RETRY_WAIT],
                 next_attempt_at__lte=clock)
    expired = Q(status=EmailDelivery.Status.SENDING, attempts__number=F("attempt_count"),
                attempts__lease_expires_at__lte=clock)
    return list(EmailDelivery.objects.filter(eligible | expired).distinct().order_by("created_at", "pk")
                .values_list("pk", flat=True)[:limit])
