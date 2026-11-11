"""Atomic assignment and reassignment of department complaints."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.db import transaction

from accounts.models import User
from accounts.permissions import _refuse, can_allocate_complaint
from complaints.models import Complaint
from routing.queue import OPEN_QUEUE_STATUSES
from workflow.history_service import record_history
from workflow.models import ComplaintHistory

ALLOCATABLE_STATUSES = OPEN_QUEUE_STATUSES
MAX_REASON_LENGTH = 500


class AllocationError(ValidationError):
    """A complaint cannot be allocated with the supplied values."""


class StaleAllocation(AllocationError):
    def __init__(self):
        super().__init__("The assignment has changed.", code="modified_record")


class _AllocationDenied(Exception):
    def __init__(self, actor, complaint, concealed):
        self.actor, self.complaint, self.concealed = actor, complaint, concealed


def allocate_complaint(*, actor, complaint_id, assignee, expected_assignee_id, reason=""):
    try:
        return _allocate_complaint(actor=actor, complaint_id=complaint_id, assignee=assignee,
                                   expected_assignee_id=expected_assignee_id, reason=reason)
    except _AllocationDenied as denial:
        # Record after the mutation savepoint has rolled back. An enclosing
        # caller transaction, if any, still controls this audit write's commit.
        _refuse(denial.actor, can_allocate_complaint.__name__, denial.complaint)
        if denial.concealed:
            raise Http404 from None
        raise PermissionDenied from None


@transaction.atomic
def _allocate_complaint(*, actor, complaint_id, assignee, expected_assignee_id, reason=""):
    actor_id = getattr(actor, "pk", None)
    actor = User.objects.select_for_update().filter(pk=actor_id).first()
    complaint = Complaint.objects.select_for_update().filter(complaint_id=complaint_id).first()
    if complaint is None:
        raise Http404
    if not can_allocate_complaint(actor, complaint):
        raise _AllocationDenied(actor, complaint, concealed=True)
    target_id = getattr(assignee, "pk", assignee)
    target = User.objects.select_for_update().filter(pk=target_id).first()
    if not can_allocate_complaint(actor, complaint,
                                  target if target is not None else User(is_active=False)):
        raise _AllocationDenied(actor, complaint, concealed=False)
    if complaint.status not in ALLOCATABLE_STATUSES:
        raise AllocationError("The complaint cannot be allocated in its current state.",
                              code="not_allocatable")
    if complaint.assignee_id != expected_assignee_id:
        raise StaleAllocation()
    reason = (reason or "").strip()
    if expected_assignee_id is not None:
        if not reason:
            raise AllocationError("A reassignment reason is required.", code="reason_required")
        if len(reason) > MAX_REASON_LENGTH:
            raise AllocationError("The reassignment reason is too long.", code="reason_too_long")
        if target.pk == complaint.assignee_id:
            raise AllocationError("The assignee is unchanged.", code="same_assignee")
    complaint.assignee = target
    complaint.save(update_fields=["assignee"])
    record_history(
        complaint.complaint_id,
        ComplaintHistory.EventType.ALLOCATED if expected_assignee_id is None
        else ComplaintHistory.EventType.REASSIGNED,
        ComplaintHistory.ActorKind.HEAD,
        previous_state=complaint.status, new_state=complaint.status, remarks=reason,
        actor=actor, assignee=target,
    )
    return complaint
