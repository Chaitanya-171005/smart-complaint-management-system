from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from routing.escalation import run_escalation
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db


@pytest.fixture
def policy(routing_configuration):
    policy = routing_configuration["policy"]
    policy.interval_minutes = 60
    policy.maximum_level = 2
    policy.save(update_fields=["interval_minutes", "maximum_level"])
    return policy


def run_at(now):
    with patch("django.utils.timezone.now", return_value=now):
        return run_escalation(now=now)


def history(complaint):
    return ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id, event_type="ESCALATED")


@pytest.mark.parametrize("offset,expected", [(-1, True), (0, True), (1, False)])
def test_due_boundary(policy, complaint_factory, offset, expected):
    now = timezone.now()
    complaint = complaint_factory(due_at=now + timedelta(seconds=offset))
    run = run_at(now)
    complaint.refresh_from_db()
    assert complaint.is_escalated is expected
    assert complaint.escalation_level == int(expected)
    assert history(complaint).count() == int(expected)
    assert run.escalated == int(expected)


@pytest.mark.parametrize("status,expected", [
    ("RESOLVED", False), ("CLOSED", False), ("REJECTED", False),
    ("SUBMITTED", True), ("ASSIGNED", True), ("IN_PROGRESS", True), ("REOPENED", True),
])
def test_status_eligibility(policy, complaint_factory, status, expected):
    now = timezone.now()
    complaint = complaint_factory(status=status, due_at=now - timedelta(seconds=1))
    run_at(now)
    complaint.refresh_from_db()
    assert complaint.is_escalated is expected
    assert complaint.escalation_level == int(expected)
    assert history(complaint).count() == int(expected)


def test_repeated_runs_preserve_fields_and_record_each_level(policy, complaint_factory, staff_user):
    now = timezone.now()
    complaint = complaint_factory(due_at=now - timedelta(seconds=1), assignee=staff_user,
                                  department=staff_user.department, priority="HIGH", status="IN_PROGRESS")
    fields = ("assignee_id", "department_id", "status", "due_at", "priority")
    before = tuple(getattr(complaint, field) for field in fields)
    first = run_at(now)
    complaint.refresh_from_db()
    assert first.escalated == 1 and complaint.is_escalated and complaint.escalation_level == 1
    event = history(complaint).get()
    assert (event.actor_kind, event.previous_state, event.new_state, event.remarks) == (
        "SYSTEM", "IN_PROGRESS", "IN_PROGRESS", "Past due; escalated to level 1 of 2")
    second = run_at(now + timedelta(minutes=59, seconds=59))
    complaint.refresh_from_db()
    assert second.escalated == 0 and complaint.escalation_level == 1 and history(complaint).count() == 1
    third = run_at(now + timedelta(minutes=60))
    complaint.refresh_from_db()
    assert third.escalated == 1 and complaint.escalation_level == 2
    events = list(history(complaint).order_by("occurred_at", "pk"))
    assert len(events) == 2
    assert events[1].actor_kind == "SYSTEM" and events[1].remarks == "Past due; escalated to level 2 of 2"
    assert tuple(getattr(complaint, field) for field in fields) == before
    last = run_at(now + timedelta(days=1))
    complaint.refresh_from_db()
    assert last.escalated == 0 and complaint.escalation_level == 2 and history(complaint).count() == 2


def test_changed_policy_applies_next_run_without_changing_due(policy, complaint_factory):
    now = timezone.now()
    complaint = complaint_factory(due_at=now - timedelta(seconds=1))
    due = complaint.due_at
    run_at(now)
    policy.interval_minutes = 10
    policy.maximum_level = 3
    policy.save(update_fields=["interval_minutes", "maximum_level"])
    run_at(now + timedelta(minutes=9))
    complaint.refresh_from_db()
    assert complaint.escalation_level == 1 and complaint.due_at == due
    run_at(now + timedelta(minutes=10))
    complaint.refresh_from_db()
    assert complaint.escalation_level == 2 and complaint.due_at == due
    run_at(now + timedelta(minutes=20))
    complaint.refresh_from_db()
    assert complaint.escalation_level == 3 and complaint.due_at == due
    assert list(history(complaint).order_by("occurred_at").values_list("remarks", flat=True)) == [
        "Past due; escalated to level 1 of 2", "Past due; escalated to level 2 of 3",
        "Past due; escalated to level 3 of 3",
    ]


def test_interrupted_complaint_rolls_back_and_retry_finishes(policy, complaint_factory, monkeypatch):
    from routing import escalation
    now = timezone.now()
    complaints = [complaint_factory(due_at=now - timedelta(seconds=1)) for _ in range(3)]
    original = escalation.record_history

    def intermittent(complaint_id, *args, **kwargs):
        if complaint_id == complaints[1].complaint_id:
            raise RuntimeError("history unavailable")
        return original(complaint_id, *args, **kwargs)

    monkeypatch.setattr(escalation, "record_history", intermittent)
    run = run_at(now)
    assert (run.examined, run.escalated, run.skipped, run.failed, run.status) == (3, 2, 0, 1, "FAILED")
    assert run.finished_at is not None
    for index, complaint in enumerate(complaints):
        complaint.refresh_from_db()
        assert complaint.escalation_level == (0 if index == 1 else 1)
        assert complaint.is_escalated == (index != 1)
        assert history(complaint).count() == (0 if index == 1 else 1)
    monkeypatch.setattr(escalation, "record_history", original)
    retry = run_at(now + timedelta(minutes=1))
    assert (retry.examined, retry.escalated, retry.failed) == (1, 1, 0)
    for complaint in complaints:
        complaint.refresh_from_db()
        assert complaint.escalation_level == 1 and history(complaint).count() == 1


@pytest.mark.parametrize("change", ["resolved", "already_escalated"])
def test_stale_candidate_is_rechecked(policy, complaint_factory, monkeypatch, change):
    from complaints.models import Complaint
    from workflow.history_service import record_history
    now = timezone.now()
    complaint = complaint_factory(due_at=now - timedelta(seconds=1))
    original = Complaint.objects.select_for_update

    def change_before_lock(*args, **kwargs):
        if change == "resolved":
            Complaint.objects.filter(pk=complaint.pk).update(status="RESOLVED")
        else:
            Complaint.objects.filter(pk=complaint.pk).update(is_escalated=True, escalation_level=1)
            record_history(complaint.complaint_id, "ESCALATED", "SYSTEM", "ASSIGNED", "ASSIGNED", "other run")
        return original(*args, **kwargs)

    monkeypatch.setattr(Complaint.objects, "select_for_update", change_before_lock)
    run = run_at(now)
    complaint.refresh_from_db()
    assert (run.examined, run.skipped, run.escalated, run.failed) == (1, 1, 0, 0)
    assert complaint.escalation_level == (1 if change == "already_escalated" else 0)
    assert history(complaint).count() == (1 if change == "already_escalated" else 0)


def test_notify_after_commit_and_failure_isolated(policy, complaint_factory, django_capture_on_commit_callbacks):
    now = timezone.now()
    complaint = complaint_factory(due_at=now - timedelta(seconds=1))
    calls = []

    def notify(record, level, department):
        calls.append((record.pk, level, department.pk))
        raise RuntimeError("notification error")

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        run = run_escalation(now=now, notify=notify)
        assert calls == []
        assert run.escalated == 1 and run.failed == 0
    assert len(callbacks) == 1
    assert calls == [(complaint.pk, 1, complaint.department_id)]
    complaint.refresh_from_db()
    assert complaint.is_escalated and complaint.escalation_level == 1
    assert history(complaint).count() == 1


def test_missing_policy_records_failed_run(policy):
    from routing.models import EscalationRun
    from routing.resolver import RoutingConfigurationError
    policy.delete()
    with pytest.raises(RoutingConfigurationError):
        run_at(timezone.now())
    run = EscalationRun.objects.get()
    assert run.status == "FAILED" and run.finished_at is not None
    assert (run.examined, run.escalated, run.skipped, run.failed) == (0, 0, 0, 0)
    assert run.error == "Escalation setup failed."


@pytest.mark.parametrize("values", [
    {"status": "RUNNING", "finished_at": "present"},
    {"status": "COMPLETED", "finished_at": None},
    {"status": "FAILED", "finished_at": None},
    {"status": "RUNNING", "examined": -1},
    {"status": "RUNNING", "escalated": -1},
    {"status": "RUNNING", "skipped": -1},
    {"status": "RUNNING", "failed": -1},
])
def test_run_database_constraints(values):
    from django.db import IntegrityError, transaction
    from routing.models import EscalationRun
    values = values.copy()
    if values.get("finished_at") == "present":
        values["finished_at"] = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        EscalationRun.objects.create(started_at=timezone.now(), **values)


def test_management_command_summary_and_failed_exit(policy, capsys):
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from routing.models import EscalationRun
    call_command("run_escalation")
    run = EscalationRun.objects.get()
    assert capsys.readouterr().out.strip() == (
        f"run={run.pk} status=COMPLETED examined=0 escalated=0 skipped=0 failed=0")
    policy.delete()
    with pytest.raises(CommandError):
        call_command("run_escalation")
    failed = EscalationRun.objects.get(status="FAILED")
    assert capsys.readouterr().out.strip() == (
        f"run={failed.pk} status=FAILED examined=0 escalated=0 skipped=0 failed=0")


def test_volume_candidate_query_uses_subquery(policy, complaint_factory):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from routing.escalation import _eligible
    now = timezone.now()
    for _ in range(5):
        complaint_factory(due_at=now - timedelta(seconds=1))
    with CaptureQueriesContext(connection) as small_queries:
        small = list(_eligible(now, policy).values_list("pk", flat=True))
    for _ in range(495):
        complaint_factory(due_at=now - timedelta(seconds=1))
    with CaptureQueriesContext(connection) as large_queries:
        large = list(_eligible(now, policy).values_list("pk", flat=True))
    assert len(small) == 5 and len(large) == 500
    assert len(small_queries) == len(large_queries) <= 2
    run = run_at(now)
    assert (run.examined, run.escalated, run.failed) == (500, 500, 0)


@pytest.mark.django_db(transaction=True)
def test_notification_failure_does_not_block_later_notification(policy, complaint_factory):
    now = timezone.now()
    first = complaint_factory(due_at=now - timedelta(seconds=1))
    second = complaint_factory(due_at=now - timedelta(seconds=1))
    succeeded = []

    def notify(complaint, level, department):
        if complaint.pk == first.pk:
            raise RuntimeError("private-notification-detail")
        succeeded.append((complaint.pk, level, department.pk))

    run = run_escalation(now=now, notify=notify)
    assert run.status == "COMPLETED" and run.failed == 0 and run.escalated == 2
    assert "notification_failed=1" in run.error
    assert "private-notification-detail" not in run.error
    assert first.submitted_by.email not in run.error and second.submitted_by.email not in run.error
    assert first.complaint_id not in run.error and second.complaint_id not in run.error
    assert succeeded == [(second.pk, 1, second.department_id)]
    for complaint in (first, second):
        complaint.refresh_from_db()
        assert complaint.is_escalated and complaint.escalation_level == 1
        assert history(complaint).count() == 1


@pytest.mark.django_db(transaction=True)
def test_command_processing_failure_reports_failed_and_keeps_success(policy, complaint_factory, monkeypatch, capsys):
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from routing import escalation
    from routing.models import EscalationRun
    now = timezone.now()
    complaints = [complaint_factory(due_at=now - timedelta(minutes=1)) for _ in range(2)]
    original = escalation.record_history
    def fail_one(complaint_id, *args, **kwargs):
        if complaint_id == complaints[1].complaint_id:
            raise RuntimeError('sensitive detail')
        return original(complaint_id, *args, **kwargs)
    monkeypatch.setattr(escalation, 'record_history', fail_one)
    with pytest.raises(CommandError, match='Escalation run failed'):
        call_command('run_escalation')
    run = EscalationRun.objects.get()
    assert (run.status, run.examined, run.escalated, run.skipped, run.failed) == ('FAILED', 2, 1, 0, 1)
    assert run.finished_at is not None and 'sensitive detail' not in run.error
    assert 'status=FAILED examined=2 escalated=1 skipped=0 failed=1' in capsys.readouterr().out
    for complaint, level in zip(complaints, [1, 0]):
        complaint.refresh_from_db()
        assert complaint.escalation_level == level
        assert history(complaint).count() == level


@pytest.mark.django_db(transaction=True)
def test_keyboard_interrupt_rolls_back_current_complaint_and_retry(policy, complaint_factory, monkeypatch):
    from routing import escalation
    from routing.models import EscalationRun
    now = timezone.now()
    complaints = [complaint_factory(due_at=now - timedelta(minutes=1)) for _ in range(3)]
    original = escalation.record_history
    interruption = KeyboardInterrupt('original interruption')
    def interrupt(complaint_id, *args, **kwargs):
        if complaint_id == complaints[1].complaint_id:
            raise interruption
        return original(complaint_id, *args, **kwargs)
    monkeypatch.setattr(escalation, 'record_history', interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        run_escalation(now=now)
    assert caught.value is interruption
    run = EscalationRun.objects.get()
    assert (run.status, run.examined, run.escalated, run.skipped, run.failed) == ('FAILED', 2, 1, 0, 1)
    assert run.finished_at is not None and run.error == 'Escalation interrupted.'
    for complaint, level in zip(complaints, [1, 0, 0]):
        complaint.refresh_from_db()
        assert complaint.escalation_level == level and history(complaint).count() == level
    monkeypatch.setattr(escalation, 'record_history', original)
    retry = run_escalation(now=now + timedelta(minutes=1))
    assert (retry.status, retry.examined, retry.escalated, retry.failed) == ('COMPLETED', 2, 2, 0)
    assert all(history(complaint).count() == 1 for complaint in complaints)


@pytest.mark.django_db(transaction=True)
def test_interruption_in_notification_counts_committed_complaint(policy, complaint_factory):
    from routing.models import EscalationRun
    now = timezone.now()
    complaint = complaint_factory(due_at=now - timedelta(minutes=1))
    interruption = KeyboardInterrupt('notify interrupted')
    def notify(*args):
        raise interruption
    with pytest.raises(KeyboardInterrupt) as caught:
        run_escalation(now=now, notify=notify)
    assert caught.value is interruption
    run = EscalationRun.objects.get()
    assert (run.status, run.examined, run.escalated, run.failed) == ('FAILED', 1, 1, 0)
    complaint.refresh_from_db()
    assert complaint.escalation_level == 1 and history(complaint).count() == 1


@pytest.mark.django_db(transaction=True)
def test_interruption_survives_finalization_failure(policy, complaint_factory, monkeypatch):
    from routing import escalation
    from routing.models import EscalationRun
    now = timezone.now()
    complaint_factory(due_at=now - timedelta(minutes=1))
    interruption = KeyboardInterrupt('original')
    def interrupt(*args, **kwargs):
        raise interruption
    original_save = EscalationRun.save
    def fail_finalization(self, *args, **kwargs):
        if self.pk:
            from django.core.exceptions import ValidationError
            raise ValidationError('finalization failed')
        return original_save(self, *args, **kwargs)
    monkeypatch.setattr(escalation, 'record_history', interrupt)
    monkeypatch.setattr(EscalationRun, 'save', fail_finalization)
    with pytest.raises(KeyboardInterrupt) as caught:
        run_escalation(now=now)
    assert caught.value is interruption
    assert 'Escalation run finalization also failed.' in caught.value.__notes__
