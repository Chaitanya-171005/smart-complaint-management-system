
from django.core.exceptions import ValidationError


IN_PROGRESS = "IN_PROGRESS"
RESOLVED = "RESOLVED"


def validate_resolution(current_state, remarks):
    """
    Validate the basic requirements for resolving a complaint.

    This is an independent validation helper. It does not authorize
    the actor, validate evidence, update a complaint, or send notifications.
    """
    if current_state != IN_PROGRESS:
        raise ValidationError(
            "A complaint can only be resolved from IN_PROGRESS."
        )

    if not isinstance(remarks, str) or len(remarks.strip()) < 20:
        raise ValidationError(
            "Resolution remarks must contain at least 20 characters."
        )

    return RESOLVED
