from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.core.paginator import Paginator


def get_owned_complaints(user, complaints_queryset):
    """
    Return only complaints belonging to the authenticated user.

    Args:
        user: The currently authenticated Django user.
        complaints_queryset: A queryset of complaints.

    Returns:
        A queryset containing only complaints owned by the user.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return complaints_queryset.none()

    return complaints_queryset.filter(submitted_by=user)

def filter_complaints(queryset, status=None, category=None):
    """
    Filter complaints by status and category.
    """
    if status:
        queryset = queryset.filter(status=status)

    if category:
        queryset = queryset.filter(category=category)

    return queryset



def paginate_complaints(queryset, page_number=1):
    """
    Return a page containing at most 25 complaints.
    """
    paginator = Paginator(queryset, 25)
    return paginator.get_page(page_number)


def get_owned_complaint(user, complaints_queryset, complaint_id):
    """
    Retrieve a complaint only if it belongs to the logged-in user.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Login required.")

    try:
        return get_owned_complaints(
            user, complaints_queryset
        ).get(pk=complaint_id)
    except complaints_queryset.model.DoesNotExist:
        raise Http404("Complaint not found.")
