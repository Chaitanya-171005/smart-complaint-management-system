"""B07 form construction; persistence is handled by the later intake transaction."""

from accounts.models import User
from accounts.permissions import has_role, require_permission

from .forms import ComplaintForm


def can_submit_complaint(user):
    return has_role(user, User.Role.COMPLAINANT)


def build_complaint_form(user, data=None, *, categories, locations):
    """Use the current request.user and fresh, trusted F1/F3 reference options.

    This validates input only. It neither creates an accepted complaint nor
    performs routing, evidence storage, acknowledgement or history operations.
    """
    require_permission(can_submit_complaint, user)
    return ComplaintForm(data, categories=categories, locations=locations)
