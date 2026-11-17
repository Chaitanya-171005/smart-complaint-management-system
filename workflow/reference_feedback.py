"""Reference-authorized B23/B24 actions, independent of account authentication.

HTTP callers must first enforce the shared source limiter, release gates and
CSRF. No public complaint identifier, actor or system flag grants this authority.
"""
import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_variables

from complaints.models import Complaint
from complaints.references import hash_reference
from complaints.validators import validate_description
from workflow.feedback_policy import maximum_reopens
from workflow.history_service import record_history
from workflow.lifecycle import LifecycleError, ModifiedRecord, _revision
from workflow.models import AnonymousResolutionFeedback


@sensitive_variables()
def _record(reference):
    try:
        digest = hash_reference(reference)
        valid = True
    except ValueError:
        digest, valid = hashlib.sha256(b"invalid-reference").hexdigest(), False
    complaint = Complaint.objects.select_for_update().filter(
        submitted_by__isnull=True, reference_digest=digest,
    ).first()
    return complaint if valid else None


def _summary(complaint):
    return {"complaint_id": complaint.complaint_id, "category": complaint.category,
            "location": complaint.location_code, "status": complaint.get_status_display()}


def authorized_feedback_history(*, actor, complaint_id):
    """Account-only reader for department work/detail and future scoped reports."""
    from accounts.models import User
    from accounts.permissions import authorize_or_404, can_view_complaint
    current = User.objects.filter(pk=actor.pk).first() if actor is not None and actor.is_authenticated else None
    complaint = Complaint.objects.filter(complaint_id=complaint_id, submitted_by__isnull=True).first()
    authorize_or_404(can_view_complaint, current, complaint)
    return complaint, AnonymousResolutionFeedback.objects.filter(complaint=complaint).select_related("history")


@sensitive_variables()
def reference_feedback_summary(reference):
    with transaction.atomic():
        complaint = _record(reference)
        if complaint is None:
            return None
        return {**_summary(complaint), "revision": _revision(complaint)
                if complaint.status == "RESOLVED" else None}


@sensitive_variables()
def submit_reference_feedback(*, reference, expected_revision, action, rating=None, reason=""):
    """Lock, validate and commit the complete feedback/history/notice graph.

The reference is re-entered for every action, never returned in a token or form.
Opaque state revisions are useless without the corresponding secret reference.
D04 is unresolved: assignment, due time and overdue escalation are preserved.
"""
    with transaction.atomic():
        complaint = _record(reference)
        if complaint is None:
            return None
        if (not isinstance(expected_revision, str) or len(expected_revision) != 64
                or not constant_time_compare(expected_revision, _revision(complaint))):
            raise ModifiedRecord()
        if complaint.status != "RESOLVED":
            raise LifecycleError("Feedback requires a resolved complaint.", code="invalid_transition")
        if action not in ("confirm", "reject"):
            raise ValidationError("Choose a permitted feedback action.", code="invalid_action")
        if action == "confirm":
            if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
                raise ValidationError("Choose a rating from 1 to 5.", code="invalid_rating")
            if reason:
                raise ValidationError("Confirmation does not accept a rejection reason.", code="invalid_reason")
            target, decision, event = "CLOSED", "CONFIRM", "STATUS_CHANGED"
            complaint.rating, complaint.closed_at = rating, timezone.now()
            complaint.save(update_fields=["rating", "closed_at"])
        else:
            if not isinstance(reason, str):
                raise ValidationError("Supply a valid rejection reason.", code="invalid_reason")
            reason = reason.strip()
            if len(reason) > 2000 or "\x00" in reason:
                raise ValidationError("Supply a valid rejection reason.", code="invalid_reason")
            validate_description(reason)
            # Free-text privacy checks cover case variants; reference lookup
            # still requires the original canonical, case-sensitive credential.
            folded_reason = reason.casefold()
            if (reference.casefold() in folded_reason
                    or complaint.reference_digest.casefold() in folded_reason or rating is not None):
                raise ValidationError("Do not include the private reference or a rating in a rejection.", code="invalid_reason")
            if complaint.reopen_count < maximum_reopens():
                complaint.reopen_count += 1
                complaint.save(update_fields=["reopen_count"])
                target, decision, event = "REOPENED", "REOPEN", "STATUS_CHANGED"
            else:
                target, decision, event = "RESOLVED", "HEAD_REVIEW", "ESCALATED"
        previous = complaint.status
        complaint.status = target
        complaint.save(update_fields=["status"])
        history = record_history(complaint.complaint_id, event, "ANONYMOUS",
                                 previous_state=previous, new_state=target)
        AnonymousResolutionFeedback.objects.create(complaint=complaint, history=history,
            decision=decision, reason=reason, rating=rating)
        return {**_summary(complaint), "decision": decision}
