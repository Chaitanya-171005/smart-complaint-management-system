"""#75 real B11/B12 + B18 + B26 integration, explicitly invoked.

Requires the unmerged F2 anonymous and F3 escalation sources. No skip guard:
missing dependencies must fail instead of appearing as passing acceptance.
Run: python -m pytest integration_checks/anonymous_escalation.py --no-cov -q
"""

import json
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from complaints.anonymous import submit_anonymous_complaint
from complaints.intake import new_intake_key
from complaints.models import Complaint
from workflow.email_delivery import deliver_email
from workflow.models import EmailDelivery, Notification, NotificationEvent
from workflow.notifications import get_notification


@pytest.mark.django_db(transaction=True)
def test_anonymous_escalation_persists_and_delivers_safe_head_notice(
        routing_configuration, user_factory, settings, tmp_path):
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
    Complaint.objects.filter(pk=complaint.pk).update(due_at=timezone.now() - timedelta(minutes=1))
    # No spy notification hook: the real B21 writer publishes B26 atomically.
    result = run_escalation()
    assert result.escalated == 1 and result.failed == 0
    notice = Notification.objects.get(recipient=head, event__kind="ESCALATED")
    assert get_notification(head, notice.pk) == notice
    assert notice.event.anonymous
    assert deliver_email(notice.email_delivery.pk) == "SENT"
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [head.email]
    assert not EmailDelivery.objects.filter(notice__recipient__role="COMPLAINANT").exists()
    serialized = json.dumps(list(NotificationEvent.objects.values()), default=str) + mail.outbox[0].message().as_string()
    assert "Anonymous" in serialized
    for forbidden in (accepted.reference, complaint.reference_digest, "submitted_by", "source_ip", "session"):
        assert forbidden not in serialized
    # The pending department-assignment job is distinct from escalation.
    assert Notification.objects.filter(recipient=head).count() == 2
