"""F3 transactional contract tests; no F4 schema or SMTP service required."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from routing import notifications
from routing.escalation import run_escalation
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db(transaction=True)


def overdue(complaint_factory):
    return complaint_factory(anonymous=True, title="PRIVATE_TITLE", description="PRIVATE_DESCRIPTION synthetic complaint details.",
                             due_at=timezone.now() - timedelta(minutes=1))


def publisher(monkeypatch, callback):
    module = SimpleNamespace(publish_history_event=callback)
    monkeypatch.setattr(notifications, "import_module", lambda name: module)


def test_missing_f4_preserves_history_without_claiming_delivery(routing_configuration, complaint_factory):
    complaint = overdue(complaint_factory)
    run = run_escalation()
    event = ComplaintHistory.objects.get(complaint_ref=complaint.complaint_id, event_type="ESCALATED")
    with transaction.atomic():
        assert notifications.publish_escalation_history(event) is None
    assert run.escalated == 1


def test_publisher_receives_only_persisted_history_inside_transaction(
    routing_configuration, complaint_factory, monkeypatch,
):
    complaint = overdue(complaint_factory)
    observed = []

    def publish(event):
        assert transaction.get_connection().in_atomic_block
        assert ComplaintHistory.objects.filter(pk=event.pk).exists()
        assert event.actor_id is None and event.assignee_id is None
        assert event.complaint_ref == complaint.complaint_id
        assert "PRIVATE" not in event.remarks
        assert complaint.reference_digest not in event.remarks
        observed.append(event.pk)

    publisher(monkeypatch, publish)
    now = timezone.now()
    assert run_escalation(now=now).escalated == 1
    assert run_escalation(now=now).escalated == 0
    assert len(observed) == 1


def test_failed_publication_rolls_back_and_retry_uses_one_success_history(
    routing_configuration, complaint_factory, monkeypatch, caplog,
):
    complaint = overdue(complaint_factory)
    callback = Mock(side_effect=RuntimeError(f"{complaint.title} {complaint.reference_digest}"))
    publisher(monkeypatch, callback)
    first = run_escalation()
    assert (first.escalated, first.failed) == (0, 1)
    complaint.refresh_from_db()
    assert complaint.escalation_level == 0
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()
    assert complaint.title not in first.error + caplog.text
    assert complaint.reference_digest not in first.error + caplog.text
    callback.side_effect = None
    assert run_escalation().escalated == 1
    assert ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).count() == 1


def test_outer_rollback_discards_history_and_publisher_database_writes(
    routing_configuration, complaint_factory, monkeypatch,
):
    complaint = overdue(complaint_factory)

    def publish(event):
        # A second real DB row stands in for the publisher's transactional writes.
        ComplaintHistory.objects.create(complaint_ref=event.complaint_ref, event_type="SUBMITTED",
                                        actor_kind="SYSTEM")

    publisher(monkeypatch, publish)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            assert run_escalation().escalated == 1
            raise RuntimeError("Caller rollback")
    complaint.refresh_from_db()
    assert complaint.escalation_level == 0
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


@pytest.mark.parametrize("missing", ["workflow.notification_models", "unrelated_dependency"])
def test_broken_installed_f4_is_not_treated_as_unavailable(
    routing_configuration, complaint_factory, monkeypatch, missing,
):
    def broken(name):
        raise ModuleNotFoundError(name=missing)
    monkeypatch.setattr(notifications, "import_module", broken)
    complaint = overdue(complaint_factory)
    assert run_escalation().failed == 1
    complaint.refresh_from_db()
    assert complaint.escalation_level == 0


def test_wrong_event_and_nontransactional_call_are_refused(complaint_factory):
    complaint = overdue(complaint_factory)
    event = ComplaintHistory.objects.create(complaint_ref=complaint.complaint_id,
                                            event_type="SUBMITTED", actor_kind="SYSTEM")
    with pytest.raises(ValidationError, match="transaction"):
        notifications.publish_escalation_history(event)
    with transaction.atomic(), pytest.raises(ValidationError, match="system escalation"):
        notifications.publish_escalation_history(event)


def test_no_recipients_is_a_successful_durable_publisher_outcome(
    routing_configuration, complaint_factory, monkeypatch,
):
    overdue(complaint_factory)
    callback = Mock(return_value=SimpleNamespace(notices=()))
    publisher(monkeypatch, callback)
    assert run_escalation().escalated == 1
    assert callback.call_count == 1
