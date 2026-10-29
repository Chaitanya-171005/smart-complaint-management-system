"""B07 form construction; persistence is handled by the later intake transaction."""

from accounts.permissions import can_submit_complaint, require_permission

from .forms import ComplaintForm


def build_complaint_form(user, data=None, *, categories, locations):
    """Use the current request.user and fresh, trusted F1/F3 reference options.

    This validates input only. It neither creates an accepted complaint nor
    performs routing, evidence storage, acknowledgement or history operations.
    """
    require_permission(can_submit_complaint, user)
    return ComplaintForm(data, categories=categories, locations=locations)
