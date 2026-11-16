"""B23 account-owner confirmation. Reference confirmation awaits F2 B13."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from workflow.lifecycle import _account_transition, _apply_locked_transition


def confirm_resolution(*, actor, complaint_id, expected_revision, rating=None):
    """Close once, atomically with history/notices; never authorize by reference.

    The opaque revision must come from get_transition_revision(target_state='CLOSED').
    None is the only absent-rating value at this domain boundary. Reject bools,
    floats and strings rather than silently coercing caller data.
    """
    with _account_transition(actor=actor, complaint_id=complaint_id,
                             target_state="CLOSED", expected_revision=expected_revision) as context:
        complaint, current, _ = context
        if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
            raise ValidationError("Rating must be an integer from 1 to 5.", code="invalid_rating")
        complaint.rating = rating
        complaint.closed_at = timezone.now()
        complaint.save(update_fields=["rating", "closed_at"])
        return _apply_locked_transition(complaint, current, "CLOSED", "")
