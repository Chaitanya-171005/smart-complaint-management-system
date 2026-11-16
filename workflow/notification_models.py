"""B26 durable event, recipient notice and email-outbox records."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from complaints.models import Complaint


class NotificationEvent(models.Model):
    class Kind(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submission"
        DEPARTMENT_ASSIGNED = "DEPARTMENT_ASSIGNED", "Department assignment"
        STAFF_ASSIGNED = "STAFF_ASSIGNED", "Staff assignment"
        STARTED = "STARTED", "Work commencement"
        RESOLVED = "RESOLVED", "Resolution"
        ESCALATED = "ESCALATED", "Escalation"
        REOPENED = "REOPENED", "Reopening"
        CLOSED = "CLOSED", "Closure"

    # The immutable success-history row is the operation's idempotency key.
    history = models.OneToOneField("workflow.ComplaintHistory", on_delete=models.PROTECT)
    complaint = models.ForeignKey(Complaint, on_delete=models.PROTECT)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    public_id = models.CharField(max_length=16)
    status = models.CharField(max_length=11, choices=Complaint.Status.choices)
    anonymous = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(public_id__regex=r"\ASCMS-[0-9]{4}-[0-9]{6}\Z"),
                                   name="notice_event_public_id_format"),
            models.CheckConstraint(condition=models.Q(status__in=Complaint.Status.values),
                                   name="notice_event_valid_state"),
            models.CheckConstraint(condition=models.Q(kind__in=[
                "SUBMITTED", "DEPARTMENT_ASSIGNED", "STAFF_ASSIGNED", "STARTED",
                "RESOLVED", "ESCALATED", "REOPENED", "CLOSED",
            ]), name="notice_event_valid_kind"),
        ]


class Notification(models.Model):
    event = models.ForeignKey(NotificationEvent, on_delete=models.PROTECT, related_name="notices")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(
            fields=["event", "recipient"], name="notice_event_recipient_unique",
        )]


class EmailDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RETRY_WAIT = "RETRY_WAIT", "Waiting for retry"
        SENDING = "SENDING", "Sending / outcome may be unknown"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        SUPPRESSED = "SUPPRESSED", "Recipient no longer eligible"

    notice = models.OneToOneField(Notification, on_delete=models.PROTECT, related_name="email_delivery")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    # Static codes only: never store an SMTP exception, address or message body.
    failure_code = models.CharField(max_length=32, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, null=True, blank=True, db_index=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(status__in=["PENDING", "RETRY_WAIT", "SENDING", "SENT", "FAILED", "SUPPRESSED"]),
            name="email_delivery_valid_status",
        ), models.CheckConstraint(condition=models.Q(attempt_count__gte=0, attempt_count__lte=3),
                                  name="email_delivery_attempt_limit")]


class EmailAttempt(models.Model):
    """One durable, fenced reservation; never retains addresses or exceptions."""

    class Status(models.TextChoices):
        CLAIMED = "CLAIMED", "Claimed, SMTP not started"
        SENDING = "SENDING", "SMTP may have started"
        SENT = "SENT", "Sent"
        RETRYABLE = "RETRYABLE", "Definite temporary failure"
        FAILED = "FAILED", "Permanent failure"
        UNKNOWN = "UNKNOWN", "SMTP outcome unknown"
        ABANDONED = "ABANDONED", "Expired before SMTP"

    delivery = models.ForeignKey(EmailDelivery, on_delete=models.PROTECT, related_name="attempts")
    number = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CLAIMED)
    started_at = models.DateTimeField(default=timezone.now)
    lease_expires_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    diagnostic_code = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["delivery", "number"], name="email_attempt_number_unique"),
            models.CheckConstraint(condition=models.Q(number__gte=1, number__lte=3),
                                   name="email_attempt_number_limit"),
            models.CheckConstraint(condition=models.Q(status__in=[
                "CLAIMED", "SENDING", "SENT", "RETRYABLE", "FAILED", "UNKNOWN", "ABANDONED",
            ]), name="email_attempt_valid_status"),
        ]
