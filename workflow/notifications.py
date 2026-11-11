"""Trusted success-event publishing and recipient-authorized notice reads.

Publish inside the business transaction; SMTP belongs to the separate worker.
No public payload, arbitrary recipient, address or free-text message is accepted.
"""

import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404

from accounts.models import User
from accounts.permissions import can_view_complaint, scope_complaints
from complaints.models import Complaint
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent

Kind = NotificationEvent.Kind
EMAIL_EVENTS = frozenset({Kind.SUBMITTED, Kind.DEPARTMENT_ASSIGNED, Kind.STAFF_ASSIGNED,
                          Kind.RESOLVED, Kind.ESCALATED, Kind.CLOSED})


def _kind(history):
    if history.event_type == "ALLOCATED":
        return Kind.DEPARTMENT_ASSIGNED if (
            history.actor_kind == "SYSTEM" and history.previous_state == "SUBMITTED"
            and history.new_state == "ASSIGNED"
        ) else Kind.STAFF_ASSIGNED
    if history.event_type == "REASSIGNED":
        return Kind.STAFF_ASSIGNED
    direct = {"SUBMITTED": Kind.SUBMITTED, "RESOLVED": Kind.RESOLVED, "ESCALATED": Kind.ESCALATED}
    if history.event_type in direct:
        return direct[history.event_type]
    if history.event_type == "STATUS_CHANGED" and history.previous_state != history.new_state:
        return {"IN_PROGRESS": Kind.STARTED, "RESOLVED": Kind.RESOLVED,
                "REOPENED": Kind.REOPENED, "CLOSED": Kind.CLOSED}.get(history.new_state)
    return None


def eligible_recipient(user, complaint, kind):
    """Affected parties, intersected with F1's current content permissions."""
    if not can_view_complaint(user, complaint):
        return False
    if user.role == User.Role.COMPLAINANT:
        return user.pk == complaint.submitted_by_id
    if kind == Kind.SUBMITTED:
        return False
    return (user.role == User.Role.HEAD or (
        user.role == User.Role.STAFF and user.pk == complaint.assignee_id
    ))


def _projection(complaint, recipient):
    """Authorize before using F2's privacy projection, when its PR is present.

    On Main (without PR #71), use only schema-validated ID/status and an anonymous
    flag. Never infer identity from an uploader, session, assignee or request.
    """
    if not can_view_complaint(recipient, complaint):
        raise Http404
    public_id, status = complaint.complaint_id, complaint.status
    anonymous = complaint.submitted_by_id is None
    if anonymous:
        try:
            from complaints.privacy import anonymous_summary, complainant_label
        except ModuleNotFoundError as error:
            if error.name != "complaints.privacy":
                raise
        else:
            summary = anonymous_summary(complaint)
            if complainant_label(complaint) != "Anonymous":
                raise ValidationError("Invalid anonymous projection.")
            public_id, status = summary["complaint_id"], summary["status"]
    if (not isinstance(public_id, str) or not re.fullmatch(r"SCMS-[0-9]{4}-[0-9]{6}", public_id)
            or public_id != complaint.complaint_id or status not in Complaint.Status.values
            or status != complaint.status):
        raise ValidationError("Invalid notification projection.")
    return public_id, anonymous


@transaction.atomic
def publish_history_event(history):
    """Persist one event and all intended notices/jobs per success-history row.

    Internal API only: callers authorize and perform the action first. B21 calls
    this within its writer transaction. Non-Complaint legacy history stays valid.
    """
    history = ComplaintHistory.objects.get(pk=history.pk)
    kind = _kind(history)
    if kind is None:
        return None
    complaint = Complaint.objects.filter(complaint_id=history.complaint_ref).select_for_update().first()
    if complaint is None:
        return None
    existing = NotificationEvent.objects.filter(history=history).first()
    if existing is not None:
        return existing
    # Locking the aggregate serializes concurrent publication of the same event.
    candidates = User.objects.filter(is_active=True).filter(
        Q(pk=complaint.submitted_by_id) | Q(pk=complaint.assignee_id)
        | Q(role=User.Role.HEAD, department_id=complaint.department_id)
    ).order_by("pk")
    recipients = [user for user in candidates if eligible_recipient(user, complaint, kind)]
    # Even an event with no current recipients is durable and cannot later be
    # replayed to newly-created users. Never retain any caller-supplied text.
    public_id = complaint.complaint_id
    anonymous = complaint.submitted_by_id is None
    for user in recipients:
        public_id, anonymous = _projection(complaint, user)
    status = history.new_state or complaint.status
    if status not in Complaint.Status.values:
        raise ValidationError("Invalid notification state.")
    event = NotificationEvent.objects.create(history=history, complaint=complaint, kind=kind,
                                            public_id=public_id, status=status, anonymous=anonymous)
    for user in recipients:
        notice = Notification.objects.create(event=event, recipient=user)
        if kind in EMAIL_EVENTS and user.email:
            EmailDelivery.objects.create(notice=notice)
    return event


def notifications_for(user):
    """Recipient-only records, additionally scoped by current F1 permissions."""
    current = (User.objects.filter(pk=user.pk).first()
               if user is not None and user.is_authenticated else None)
    if current is None:
        return Notification.objects.none()
    permitted = scope_complaints(current, Complaint.objects.all())
    return Notification.objects.filter(recipient=current, event__complaint__in=permitted).select_related("event")


def get_notification(user, notice_id):
    try:
        return notifications_for(user).get(pk=notice_id)
    except Notification.DoesNotExist:
        raise Http404 from None
