from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from routing.escalation import run_escalation
from routing.models import EscalationRun


@pytest.mark.django_db
def test_outer_transaction_notification_failure_after_run_finalized(
    routing_configuration, complaint_factory, django_capture_on_commit_callbacks,
):
    now = timezone.now()
    complaint = complaint_factory(department=routing_configuration["department"],
                                  due_at=now - timedelta(minutes=1))
    calls = []

    def notify(record, level, department):
        calls.append((record.pk, level, department.pk))
        raise RuntimeError("notification failed")

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with transaction.atomic():
            run = run_escalation(now=now, notify=notify)
            assert run.status == EscalationRun.Status.COMPLETED
            assert run.escalated == 1 and run.failed == 0 and run.error == ""
            assert calls == []
        assert calls == []

    assert len(callbacks) == 1
    assert calls == [(complaint.pk, 1, complaint.department_id)]
    run.refresh_from_db()
    complaint.refresh_from_db()
    assert run.error == "" and run.failed == 0
    assert complaint.is_escalated and complaint.escalation_level == 1
