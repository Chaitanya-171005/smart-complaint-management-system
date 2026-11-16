"""B12 privacy regressions for the F3 queue and allocation surfaces."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from complaints.anonymous import submit_anonymous_complaint
from complaints.intake import new_intake_key
from complaints.models import Complaint
from complaints.references import hash_reference
from routing.models import RoutingDecision, SLAConfiguration
from workflow.models import ComplaintHistory


pytestmark = pytest.mark.django_db


def test_anonymous_queue_uses_safe_projection_without_title_or_reference(
    client, staff_user, department, complaint_factory, location_factory,
):
    private_title = "B12_PRIVATE_TITLE_SENTINEL_2026"
    private_description = "B12_PRIVATE_DESCRIPTION_SENTINEL_2026"
    private_reference = "b12a" + "7" * 28
    private_reference_digest = hash_reference(private_reference)
    private_block = "B12_PRIVATE_BLOCK"
    private_room = "B12_PRIVATE_ROOM_SENTINEL"
    location = location_factory(block=private_block, room_area=private_room)
    complaint = complaint_factory(
        anonymous=True, department=department, location_record=location,
        title=private_title, description=private_description,
    )
    Complaint.objects.filter(pk=complaint.pk).update(
        reference_digest=private_reference_digest,
    )

    client.force_login(staff_user)
    response = client.get(reverse("routing:queue"))
    body = response.content.decode()

    assert response.status_code == 200
    assert complaint.complaint_id in body
    assert "Anonymous" in body and "Anonymous complaint" in body
    assert private_title not in body
    assert private_description not in body
    assert private_reference not in body
    assert private_reference_digest not in body
    assert private_block not in body and private_room not in body
    assert location.code in body
    complaint.refresh_from_db()
    assert complaint.reference_digest == private_reference_digest
    item = response.context["queue_items"][0]
    assert item["summary"]["complainant"] == "Anonymous"
    assert {"title", "description", "reference_digest", "submitted_by", "block", "room_area"}.isdisjoint(item["summary"])


def test_authenticated_queue_keeps_existing_title_and_complainant_display(
    client, staff_user, department, complaint_factory,
):
    complaint = complaint_factory(department=department, title="Synthetic authenticated title")
    client.force_login(staff_user)
    response = client.get(reverse("routing:queue"))
    body = response.content.decode()

    assert response.status_code == 200
    assert complaint.title in body
    assert complaint.submitted_by.full_name in body
    assert "Anonymous complaint" not in body


def test_other_department_staff_cannot_read_anonymous_queue_row(
    user_factory, department_factory, complaint_factory,
):
    private_title = "B12_CROSS_DEPARTMENT_SENTINEL"
    other_department = department_factory()
    complaint = complaint_factory(anonymous=True, department=other_department, title=private_title)
    client = Client()
    client.force_login(user_factory(role=User.Role.STAFF, department=department_factory()))

    response = client.get(reverse("routing:queue"))

    # Staff can open only their own (empty) queue; the other department's row
    # is never projected into their response.
    assert response.status_code == 200
    assert complaint.complaint_id not in response.content.decode()
    assert private_title not in response.content.decode()


def test_anonymous_allocation_error_does_not_echo_private_complaint_values(
    client, head_user, staff_user, department, complaint_factory,
):
    private_title = "B12_ALLOCATION_ERROR_TITLE_SENTINEL"
    private_reference = "b12c" + "8" * 28
    private_reference_digest = hash_reference(private_reference)
    complaint = complaint_factory(
        anonymous=True, department=department, status=Complaint.Status.CLOSED,
        title=private_title,
    )
    Complaint.objects.filter(pk=complaint.pk).update(
        reference_digest=private_reference_digest,
    )
    client.force_login(head_user)

    response = client.post(reverse("assign_complaint", args=[complaint.complaint_id]), {
        "assignee": staff_user.pk,
    })
    body = response.content.decode()

    assert response.status_code == 400
    assert "cannot be allocated" in body
    for secret in (private_title, private_reference, private_reference_digest):
        assert secret not in body
    complaint.refresh_from_db()
    assert complaint.reference_digest == private_reference_digest
    assert complaint.status == Complaint.Status.CLOSED and complaint.assignee_id is None
    assert not ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id).exists()


@pytest.mark.django_db(transaction=True)
def test_anonymous_intake_routes_gets_sla_and_can_be_allocated_reassigned_and_escalated(
    client, settings, tmp_path, routing_configuration, head_user, staff_user, user_factory,
):
    from routing.escalation import run_escalation

    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private-evidence"
    config = routing_configuration
    config["category"].minimum_priority = Complaint.Priority.HIGH
    config["category"].save(update_fields=["minimum_priority"])
    SLAConfiguration.objects.create(category=config["category"], priority="HIGH", duration_minutes=45)

    private_title = "B12_END_TO_END_PRIVATE_TITLE_SENTINEL"
    private_description = "B12_END_TO_END_PRIVATE_DESCRIPTION_SENTINEL"
    accepted = submit_anonymous_complaint(key=new_intake_key(), data={
        "category": str(config["category"].pk), "location": config["location"].code,
        "title": private_title, "priority": "LOW", "description": private_description,
    })
    complaint = Complaint.objects.get(complaint_id=accepted.complaint_id)
    assert complaint.submitted_by_id is None
    assert complaint.status == Complaint.Status.ASSIGNED
    assert complaint.department_id == config["department"].pk
    assert complaint.priority == Complaint.Priority.HIGH
    assert complaint.due_at == complaint.submitted_at + timedelta(minutes=45)
    decision = RoutingDecision.objects.get(complaint_id=complaint.complaint_id)
    assert decision.department_id == complaint.department_id
    assert decision.reason and private_title not in decision.reason and private_description not in decision.reason

    client.force_login(head_user)
    queue = client.get(reverse("routing:queue"))
    body = queue.content.decode()
    assert accepted.complaint_id in body and "Anonymous" in body
    assert private_title not in body and private_description not in body
    assert accepted.reference not in body and complaint.reference_digest not in body

    allocation_url = reverse("assign_complaint", args=[complaint.complaint_id])
    assert client.post(allocation_url, {"assignee": staff_user.pk}).status_code == 302
    reassignee = user_factory(role=User.Role.STAFF, department=config["department"])
    assert client.post(allocation_url, {
        "assignee": reassignee.pk, "expected_assignee": staff_user.pk,
        "reason": "Synthetic shift coverage",
    }).status_code == 302
    complaint.refresh_from_db()
    assert complaint.assignee_id == reassignee.pk and complaint.submitted_by_id is None
    allocation_events = list(ComplaintHistory.objects.filter(
        complaint_ref=complaint.complaint_id,
    ).order_by("pk"))
    assert [(event.event_type, event.actor_id, event.assignee_id, event.remarks)
            for event in allocation_events] == [
        ("SUBMITTED", None, None, ""),
        ("ALLOCATED", None, None, ""),
        ("ALLOCATED", head_user.pk, staff_user.pk, ""),
        ("REASSIGNED", head_user.pk, reassignee.pk, "Synthetic shift coverage"),
    ]

    now = timezone.now()
    Complaint.objects.filter(pk=complaint.pk).update(due_at=now - timedelta(minutes=1))
    run = run_escalation(now=now)
    complaint.refresh_from_db()
    assert (run.status, run.examined, run.escalated, run.failed) == ("COMPLETED", 1, 1, 0)
    assert complaint.submitted_by_id is None and complaint.is_escalated
    escalation_event = ComplaintHistory.objects.get(
        complaint_ref=complaint.complaint_id, event_type=ComplaintHistory.EventType.ESCALATED,
    )
    assert escalation_event.actor_kind == ComplaintHistory.ActorKind.SYSTEM
    assert private_title not in escalation_event.remarks and private_description not in escalation_event.remarks
    assert accepted.reference not in escalation_event.remarks


@pytest.mark.django_db(transaction=True)
def test_anonymous_escalation_failure_keeps_console_and_run_error_private(
    settings, tmp_path, routing_configuration, complaint_factory, monkeypatch, capsys, caplog,
):
    from routing import escalation
    from routing.models import EscalationRun

    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private-evidence"
    private_title = "B12_ESCALATION_PRIVATE_TITLE_SENTINEL"
    private_reference = "b12f" + "2" * 28
    private_reference_digest = hash_reference(private_reference)
    complaint = complaint_factory(
        anonymous=True, title=private_title,
        due_at=timezone.now() - timedelta(minutes=5),
    )
    Complaint.objects.filter(pk=complaint.pk).update(
        reference_digest=private_reference_digest,
    )
    monkeypatch.setattr(
        escalation, "record_history",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(
            f"{private_title} {private_reference} B12_EXCEPTION_SENTINEL"
        )),
    )

    with pytest.raises(CommandError, match="Escalation run failed"):
        call_command("run_escalation")

    output = capsys.readouterr().out + caplog.text
    run = EscalationRun.objects.get()
    assert run.status == EscalationRun.Status.FAILED
    assert (run.examined, run.escalated, run.skipped, run.failed) == (1, 0, 0, 1)
    assert run.finished_at is not None
    assert run.error == "One or more complaints could not be processed."
    for secret in (private_title, private_reference, "B12_EXCEPTION_SENTINEL", private_reference_digest):
        assert secret not in output
        assert secret not in run.error
    complaint.refresh_from_db()
    assert complaint.reference_digest == private_reference_digest
    assert not complaint.is_escalated and complaint.escalation_level == 0
    assert not ComplaintHistory.objects.filter(
        complaint_ref=complaint.complaint_id, event_type=ComplaintHistory.EventType.ESCALATED,
    ).exists()
