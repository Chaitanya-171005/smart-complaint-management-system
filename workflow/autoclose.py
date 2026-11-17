"""B25 scheduled closure. D05 equality/feedback policy is PROPOSED."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from complaints.models import Complaint
from workflow.lifecycle import TRANSITIONS, _persist_locked_transition
from workflow.models import ComplaintHistory


def auto_close_duration():
    value = getattr(settings, 'COMPLAINT_AUTO_CLOSE_DAYS', 7)
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 1 <= value <= 36500:
        raise ImproperlyConfigured('COMPLAINT_AUTO_CLOSE_DAYS must be an integer from 1 to 36500.')
    return timedelta(days=value)


def auto_close_complaint(complaint_id, *, now=None):
    """Trusted scheduler entry point; returns result or None for ineligible rows.

    Serialize with B23/B24 on the same row. Feedback that leaves RESOLVED at the
    reopen maximum requires Head review and must not be silently auto-closed.
    No HTTP handler exposes this system capability or accepts a system flag.
    """
    duration = auto_close_duration()
    now = timezone.now() if now is None else now
    if timezone.is_naive(now):
        raise ValidationError('Auto-close time must be timezone-aware.')
    with transaction.atomic():
        complaint = Complaint.objects.select_for_update().filter(complaint_id=complaint_id).first()
        if (complaint is None or complaint.status != 'RESOLVED' or complaint.resolved_at is None
                or complaint.resolved_at > now - duration):
            return None
        if ComplaintHistory.objects.filter(
            complaint_ref=complaint.complaint_id, event_type='ESCALATED',
            actor_kind__in=['COMPLAINANT', 'ANONYMOUS'], previous_state='RESOLVED',
            new_state='RESOLVED', occurred_at__gte=complaint.resolved_at,
        ).exists():
            return None
        rule = TRANSITIONS.get(('RESOLVED', 'CLOSED'))
        if rule is None or 'AUTO_CLOSE' not in rule.external_actors:
            raise ValidationError('Automatic closure is not permitted by lifecycle policy.')
        complaint.closed_at = now
        # Automatic closure is unconfirmed: never invent a rating or feedback.
        complaint.save(update_fields=['closed_at'])
        return _persist_locked_transition(complaint, None, 'CLOSED',
                                          'Automatic closure; resolution unconfirmed.')


def run_auto_close(*, now=None, limit=100):
    """Bounded batch with one atomic action per row; safe to rerun after failure."""
    duration = auto_close_duration()
    if type(limit) is not int or limit < 1:
        raise ValidationError('Limit must be a positive integer.')
    now = timezone.now() if now is None else now
    if timezone.is_naive(now):
        raise ValidationError('Auto-close time must be timezone-aware.')
    # Exclude Head-review feedback before slicing, so it cannot starve later rows.
    review = ComplaintHistory.objects.filter(
        complaint_ref=OuterRef('complaint_id'),
        event_type='ESCALATED', actor_kind__in=['COMPLAINANT','ANONYMOUS'],
        previous_state='RESOLVED', new_state='RESOLVED',
        occurred_at__gte=OuterRef('resolved_at'))
    ids = list(Complaint.objects.filter(status='RESOLVED', resolved_at__lte=now-duration)
               .annotate(head_review=Exists(review)).filter(head_review=False)
               .order_by('resolved_at','pk').values_list('complaint_id', flat=True)[:limit])
    return sum(auto_close_complaint(pk, now=now) is not None for pk in ids)
