from django.db import transaction

from workflow.models import ComplaintHistory


@transaction.atomic
def record_history(
    complaint_ref,
    event_type,
    actor_kind,
    previous_state="",
    new_state="",
    remarks="",
    *,
    actor=None,
    assignee=None,
):
    """
    Append one complaint history event after a successful operation.

    Call inside the SAME transaction as the corresponding complaint operation,
    after its authorization and validation. This savepoint is not a substitute
    for the caller's transaction. Never defer history to an on_commit callback.
    Do not include identifying information in anonymous event remarks.
    """
    if actor_kind == ComplaintHistory.ActorKind.ANONYMOUS:
        remarks = ""
        actor = None
        assignee = None

    event = ComplaintHistory.objects.create(
        complaint_ref="" if complaint_ref is None else str(complaint_ref),
        event_type=event_type,
        actor_kind=actor_kind,
        previous_state=previous_state or "",
        new_state=new_state or "",
        remarks=remarks or "",
        actor=actor,
        assignee=assignee,
    )
    # B26: required durable writes share the action/history transaction. No SMTP
    # or lossy on_commit enqueue; existing F2/F3 callers need no second hook.
    from workflow.notifications import publish_history_event

    publish_history_event(event)
    return event


def get_complaint_history(complaint_ref):
    """Trusted internal lookup; callers must authorize before exposing results."""
    return ComplaintHistory.objects.filter(
        complaint_ref=str(complaint_ref)
    ).order_by("occurred_at", "pk")


def get_authorized_complaint_history(user, complaint_id):
    """Read history by public complaint ID using current F1 permissions.

    Anonymous reference tracking must use F2's restricted projection instead.
    The low-level lookup remains compatible with trusted existing callers.
    """
    from accounts.models import User
    from accounts.permissions import authorize_or_404, can_view_complaint
    from complaints.models import Complaint

    current_user = None
    if user is not None and user.is_authenticated:
        current_user = User.objects.filter(pk=user.pk).first()
    complaint = Complaint.objects.filter(complaint_id=complaint_id).first()
    authorize_or_404(can_view_complaint, current_user, complaint)
    return get_complaint_history(complaint.complaint_id)
