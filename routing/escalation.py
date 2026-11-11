"""Scheduled escalation, with a no-op notification hook until F4 supplies one."""

from datetime import timedelta
import sys

from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from complaints.models import Complaint
from routing.models import EscalationPolicy, EscalationRun
from routing.resolver import RoutingConfigurationError
from workflow.history_service import record_history
from workflow.models import ComplaintHistory

ELIGIBLE_STATUSES = (
    Complaint.Status.SUBMITTED, Complaint.Status.ASSIGNED,
    Complaint.Status.IN_PROGRESS, Complaint.Status.REOPENED,
)


def _no_notification(complaint, new_level, department):
    """Placeholder: F4 owns delivery of Head notifications."""


def _eligible(now, policy):
    latest = ComplaintHistory.objects.filter(
        complaint_ref=OuterRef("complaint_id"), event_type=ComplaintHistory.EventType.ESCALATED,
    ).order_by("-occurred_at", "-pk").values("occurred_at")[:1]
    return Complaint.objects.annotate(last_escalated_at=Subquery(latest)).filter(
        status__in=ELIGIBLE_STATUSES, due_at__lte=now,
        escalation_level__lt=policy.maximum_level,
    ).filter(Q(escalation_level=0) | Q(last_escalated_at__lte=now - timedelta(minutes=policy.interval_minutes)))


def run_escalation(*, now=None, notify=None):
    """Run one escalation pass; notify is invoked after each complaint commits."""
    now = timezone.now() if now is None else now
    notify = _no_notification if notify is None else notify
    run = EscalationRun.objects.create(started_at=now)
    notification_failures = 0

    def notify_safely(complaint, level, department):
        nonlocal notification_failures
        try:
            notify(complaint, level, department)
        except Exception:
            notification_failures += 1

    try:
        policy = EscalationPolicy.objects.filter(key="default").first()
        if policy is None:
            raise RoutingConfigurationError("No escalation policy is configured.")
        candidates = _eligible(now, policy).values_list("pk", flat=True)
        for pk in candidates.iterator(chunk_size=500):
            run.examined += 1
            committed = False

            def after_commit(complaint, department):
                nonlocal committed
                committed = True
                notify_safely(complaint, complaint.escalation_level, department)

            try:
                with transaction.atomic():
                    complaint = Complaint.objects.select_for_update().filter(pk=pk).first()
                    if complaint is None or not _eligible(now, policy).filter(pk=pk).exists():
                        run.skipped += 1
                        continue
                    complaint.is_escalated = True
                    complaint.escalation_level += 1
                    complaint.save(update_fields=["is_escalated", "escalation_level"])
                    record_history(
                        complaint.complaint_id, "ESCALATED", "SYSTEM",
                        previous_state=complaint.status, new_state=complaint.status,
                        remarks=f"Past due; escalated to level {complaint.escalation_level} of {policy.maximum_level}",
                    )
                    department = complaint.department
                    transaction.on_commit(lambda complaint=complaint, department=department:
                                          after_commit(complaint, department))
                run.escalated += 1
            except BaseException as exc:
                # A callback may interrupt after the transaction has committed.
                if committed:
                    run.escalated += 1
                else:
                    run.failed += 1
                if not isinstance(exc, Exception):
                    raise
        run.status = EscalationRun.Status.FAILED if run.failed else EscalationRun.Status.COMPLETED
        if run.failed:
            run.error = "One or more complaints could not be processed."
    except BaseException as exc:
        run.status = EscalationRun.Status.FAILED
        run.error = ("Escalation interrupted." if not isinstance(exc, Exception)
                     else "Escalation setup failed.")
        exc.escalation_run = run
        raise
    finally:
        if notification_failures:
            run.error = f"{run.error} notification_failed={notification_failures}".strip()
        run.finished_at = timezone.now()
        pending = sys.exc_info()[1]
        try:
            run.save(update_fields=["status", "finished_at", "examined", "escalated", "skipped", "failed", "error"])
        except BaseException:
            if pending is None:
                raise
            pending.add_note("Escalation run finalization also failed.")
    return run
