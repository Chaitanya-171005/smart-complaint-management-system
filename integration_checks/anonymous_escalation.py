"""Explicit B11/B12 + B18 hook compatibility check, not F4 delivery acceptance.

Run only in a checkout containing both #71 and #70:
    python -m pytest integration_checks/anonymous_escalation.py --no-cov -q

The filename deliberately does not match the default pytest collection pattern:
B18 is not yet merged. Explicit execution fails if that dependency is missing;
it never reports a missing module as a passing or skipped integration.
"""

import json
from datetime import timedelta

import pytest
from django.core import mail
from django.core.mail import send_mail
from django.utils import timezone

from accounts.permissions import can_view_complaint
from complaints.anonymous import submit_anonymous_complaint
from complaints.intake import new_intake_key
from complaints.models import Complaint
from complaints.privacy import anonymous_summary, complainant_label
from workflow.models import ComplaintHistory


@pytest.mark.django_db(transaction=True)
def test_anonymous_escalation_safe_head_notice_contract(routing_configuration, user_factory, settings, tmp_path):
    from routing.escalation import run_escalation
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    config = routing_configuration
    head = user_factory(role="HEAD", department=config["department"])
    accepted = submit_anonymous_complaint(key=new_intake_key(), data={
        "category": str(config["category"].pk), "location": config["location"].code,
        "title": "Synthetic privacy check", "priority": "LOW",
        "description": "The light is not working in this synthetic test room.",
    })
    complaint = Complaint.objects.get(complaint_id=accepted.complaint_id)
    Complaint.objects.filter(pk=complaint.pk).update(due_at=timezone.now()-timedelta(minutes=1))
    notices = []

    def safe_head_hook(record, level, department):
        # This is the contract that F3/F4 consumers must implement. It deliberately
        # exercises real B18 delivery timing with a spy/locmem Head notification,
        # not an unimplemented production F4 notification/outbox service.
        assert can_view_complaint(head, record) and head.department_id == department.pk
        assert record.submitted_by_id is None and complainant_label(record) == "Anonymous"
        payload = anonymous_summary(record)
        notices.append(payload)
        send_mail("SCMS escalation", json.dumps(payload), "scms@example.test", [head.email], using="default")

    run = run_escalation(notify=safe_head_hook)
    complaint.refresh_from_db()
    assert run.escalated == 1 and run.failed == 0 and run.error == ""
    assert complaint.submitted_by_id is None and complaint.is_escalated and complaint.escalation_level == 1
    assert ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id, event_type="ESCALATED").count() == 1
    assert len(notices) == len(mail.outbox) == 1 and mail.outbox[0].to == [head.email]
    serialized = json.dumps(notices) + mail.outbox[0].message().as_string()
    assert accepted.reference not in serialized and complaint.reference_digest not in serialized
    assert "Anonymous" in serialized and "submitted_by" not in serialized
