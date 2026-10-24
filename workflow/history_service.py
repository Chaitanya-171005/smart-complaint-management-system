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
):
    """
    Append one complaint history event after a successful operation.

    Call this only after the corresponding complaint operation succeeds.
    Do not include identifying information in anonymous event remarks.
    """
    if actor_kind == ComplaintHistory.ActorKind.ANONYMOUS:
        remarks = ""

    return ComplaintHistory.objects.create(
        complaint_ref=str(complaint_ref),
        event_type=event_type,
        actor_kind=actor_kind,
        previous_state=previous_state or "",
        new_state=new_state or "",
        remarks=remarks or "",
    )


def get_complaint_history(complaint_ref):
    """Return a complaint's history in chronological order."""
    return ComplaintHistory.objects.filter(
        complaint_ref=str(complaint_ref)
    ).order_by("occurred_at", "pk")
