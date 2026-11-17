"""F3 boundary for F4's durable publisher; never sends SMTP.

F4 owns NotificationEvent/history uniqueness, recipient authorization, empty
recipient events, outbox retries and delivery fencing. Without F4, only the
existing immutable history is durable; None means publication is unavailable,
not delivered. Do not replay old history to new recipients automatically.
"""

from importlib import import_module

from django.core.exceptions import ValidationError
from django.db import connection

from workflow.models import ComplaintHistory


def publish_escalation_history(history):
    """Trusted internal API, inside the locked complaint transition transaction.

    Pass only a persisted success-history identity to F4, never caller-supplied
    recipients, complaint text, references or evidence. Installed publisher
    failures must propagate so transition/history/outbox share one commit.
    F4's record_history also publishes: its idempotent API makes this explicit
    handoff safe when both callers are present after eventual integration.
    """
    if not connection.in_atomic_block:
        raise ValidationError("Notification publication requires the transition transaction.")
    event = ComplaintHistory.objects.get(pk=history.pk)
    if event.event_type != "ESCALATED" or event.actor_kind != "SYSTEM":
        raise ValidationError("A system escalation history event is required.")
    try:
        publisher = import_module("workflow.notifications")
    except ModuleNotFoundError as error:
        if error.name != "workflow.notifications":
            raise
        return None
    return publisher.publish_history_event(event)
