"""B24 owner rejection; D04 due-time and F2 reference integration remain open."""
from django.core.exceptions import ValidationError

from workflow.history_service import record_history
from workflow.lifecycle import (
    MAX_REASON_LENGTH, TransitionResult, _account_transition,
    _apply_locked_transition, _revision,
)
from workflow.models import ComplaintHistory

DEFAULT_MAX_REOPENS = 2


def reject_resolution(*, actor, complaint_id, expected_revision, reason):
    """Reject RESOLVED work under the aggregate lock; never terminally reject it.

    D04 is unresolved: preserve the stored due timestamp, never compute/reset it.
    At the limit, record same-state escalation for Head review using B26's
    existing ESCALATED event. F3 overdue flags/levels and assignment stay intact.
    """
    with _account_transition(actor=actor, complaint_id=complaint_id,
                             target_state="REOPENED", expected_revision=expected_revision) as context:
        complaint, current, _ = context
        if (not isinstance(reason, str) or not 20 <= len(reason.strip()) <= MAX_REASON_LENGTH
                or "\x00" in reason):
            raise ValidationError("A rejection reason of 20 to 2000 valid characters is required.",
                                  code="invalid_reason")
        reason = reason.strip()
        if complaint.reopen_count < DEFAULT_MAX_REOPENS:
            complaint.reopen_count += 1
            complaint.save(update_fields=["reopen_count"])
            return _apply_locked_transition(complaint, current, "REOPENED", reason)
        # A feedback escalation is not an overdue escalation or a state change.
        account = ({"actor": current} if any(field.name == "actor"
                   for field in ComplaintHistory._meta.fields) else {})
        history = record_history(complaint.complaint_id, "ESCALATED", current.role,
                                 previous_state="RESOLVED", new_state="RESOLVED",
                                 remarks=reason, **account)
        return TransitionResult(complaint.complaint_id, "RESOLVED", "RESOLVED",
                                history.pk, _revision(complaint))
