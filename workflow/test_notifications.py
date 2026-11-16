"""B26 recipient, durability, access and #75 privacy acceptance tests."""

import hashlib
import json
from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.transaction import TransactionManagementError
from django.http import Http404

from accounts.models import User
from complaints.intake import new_intake_key
from complaints.models import Complaint
from complaints.submission import submit_authenticated_complaint
from workflow.email_delivery import deliver_email
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent
from workflow.notifications import get_notification, notifications_for, publish_history_event
from workflow.history_service import record_history

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def graph(complaint_factory, user_factory, department_factory):
    complaint = complaint_factory()
    staff = user_factory(role="STAFF", department=complaint.department)
    heads = [user_factory(role="HEAD", department=complaint.department) for _ in range(2)]
    user_factory(role="STAFF", department=complaint.department)  # unassigned
    user_factory(role="HEAD", department=complaint.department, is_active=False)
    user_factory(role="HEAD", department=department_factory())
    user_factory(role="ADMIN")
    complaint.assignee = staff
    complaint.save(update_fields=["assignee"])
    return complaint, staff, heads


CASES = [
    ("SUBMITTED", "COMPLAINANT", "", "SUBMITTED", "SUBMITTED", True),
    ("ALLOCATED", "SYSTEM", "SUBMITTED", "ASSIGNED", "DEPARTMENT_ASSIGNED", True),
    ("ALLOCATED", "HEAD", "ASSIGNED", "ASSIGNED", "STAFF_ASSIGNED", True),
    ("REASSIGNED", "HEAD", "ASSIGNED", "ASSIGNED", "STAFF_ASSIGNED", True),
    ("STATUS_CHANGED", "STAFF", "ASSIGNED", "IN_PROGRESS", "STARTED", False),
    ("RESOLVED", "STAFF", "IN_PROGRESS", "RESOLVED", "RESOLVED", True),
    ("ESCALATED", "SYSTEM", "IN_PROGRESS", "IN_PROGRESS", "ESCALATED", True),
    ("STATUS_CHANGED", "COMPLAINANT", "RESOLVED", "REOPENED", "REOPENED", False),
    ("STATUS_CHANGED", "COMPLAINANT", "RESOLVED", "CLOSED", "CLOSED", True),
    ("STATUS_CHANGED", "STAFF", "IN_PROGRESS", "RESOLVED", "RESOLVED", True),
]


@pytest.mark.parametrize("event_type,actor,old,new,kind,email", CASES)
def test_required_event_recipients_and_channels(graph, event_type, actor, old, new, kind, email):
    complaint, staff, heads = graph
    with patch("workflow.email_delivery.send_mail") as send:
        history = record_history(complaint.complaint_id, event_type, actor, old, new)
    send.assert_not_called()
    event = NotificationEvent.objects.get(history=history)
    expected = {complaint.submitted_by_id}
    if kind != "SUBMITTED":
        expected.update([staff.pk, *(head.pk for head in heads)])
    assert event.kind == kind and event.status == new
    assert set(event.notices.values_list("recipient_id", flat=True)) == expected
    jobs = EmailDelivery.objects.filter(notice__event=event)
    assert set(jobs.values_list("notice__recipient_id", flat=True)) == (expected if email else set())


def test_republication_is_idempotent_and_recipient_snapshot_is_stable(graph, user_factory):
    complaint, _, _ = graph
    history = record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    event = NotificationEvent.objects.get()
    original = list(event.notices.values_list("pk", flat=True))
    user_factory(role="HEAD", department=complaint.department)
    assert publish_history_event(history).pk == event.pk
    assert list(event.notices.values_list("pk", flat=True)) == original
    assert NotificationEvent.objects.count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        Notification.objects.create(event=event, recipient=complaint.submitted_by)
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailDelivery.objects.create(notice=event.notices.first())


def test_unsupported_and_legacy_history_do_not_invent_notifications(graph):
    complaint, _, _ = graph
    record_history("legacy-only", "SUBMITTED", "SYSTEM")
    record_history(complaint.complaint_id, "STATUS_CHANGED", "SYSTEM", "SUBMITTED", "REJECTED")
    record_history(complaint.complaint_id, "STATUS_CHANGED", "SYSTEM", "ASSIGNED", "ASSIGNED")
    assert ComplaintHistory.objects.count() == 3 and not NotificationEvent.objects.exists()


@pytest.mark.parametrize("fail_at", ["notice", "delivery", "later_action"])
def test_required_failure_rolls_back_action_history_and_outbox(graph, fail_at):
    complaint, _, _ = graph
    target = ("workflow.notifications.Notification.objects.create" if fail_at == "notice"
              else "workflow.notifications.EmailDelivery.objects.create")
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            complaint.status = "IN_PROGRESS"
            complaint.save(update_fields=["status"])
            if fail_at == "later_action":
                record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
                raise RuntimeError("controlled later action failure")
            with patch(target, side_effect=RuntimeError("controlled persistence failure")):
                record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    complaint.refresh_from_db()
    assert complaint.status == "ASSIGNED"
    for model in (ComplaintHistory, NotificationEvent, Notification, EmailDelivery):
        assert not model.objects.exists()


def test_recipient_access_rechecks_current_role_and_department(graph, user_factory, department_factory):
    complaint, staff, heads = graph
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    notice = Notification.objects.get(recipient=heads[0])
    assert get_notification(heads[0], notice.pk) == notice
    assert notifications_for(staff).count() == 1
    for user in (None, AnonymousUser(), user_factory(), user_factory(role="ADMIN"), heads[1]):
        with pytest.raises(Http404):
            get_notification(user, notice.pk)
    User.objects.filter(pk=heads[0].pk).update(department=department_factory())
    assert not notifications_for(heads[0]).exists()
    User.objects.filter(pk=staff.pk).update(is_active=False)
    assert not notifications_for(staff).exists()
    with pytest.raises(Http404):
        get_notification(complaint.submitted_by, 999999)


@pytest.fixture
def intake_args(complainant_user, routing_configuration, settings, tmp_path):
    settings.PRIVATE_EVIDENCE_ROOT = tmp_path / "private"
    config = routing_configuration
    return dict(user=complainant_user, key=new_intake_key(), data={
        "category": str(config["category"].pk), "location": config["location"].code,
        "title": "Synthetic complaint", "description": "A synthetic complaint for notification integration.",
        "priority": "LOW", "sub_category": "",
    })


def test_real_intake_commits_notices_and_replay_does_not_duplicate(intake_args):
    first = submit_authenticated_complaint(**intake_args)
    assert list(NotificationEvent.objects.order_by("pk").values_list("kind", "status")) == [
        ("SUBMITTED", "SUBMITTED"), ("DEPARTMENT_ASSIGNED", "ASSIGNED")]
    assert Notification.objects.count() == EmailDelivery.objects.count() == 2
    second = submit_authenticated_complaint(**intake_args)
    assert first.complaint_id == second.complaint_id and second.replayed
    assert NotificationEvent.objects.count() == Notification.objects.count() == EmailDelivery.objects.count() == 2


def test_real_intake_cannot_commit_without_required_notice(intake_args):
    with patch("workflow.notifications.Notification.objects.create", side_effect=RuntimeError("controlled")):
        with pytest.raises(RuntimeError):
            submit_authenticated_complaint(**intake_args)
    for model in (Complaint, ComplaintHistory, NotificationEvent, Notification, EmailDelivery):
        assert not model.objects.exists()


def test_email_failure_does_not_reverse_business_or_expose_exception(graph, settings):
    complaint, _, _ = graph
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    job = EmailDelivery.objects.first()
    with patch("workflow.email_delivery.send_mail", side_effect=RuntimeError("secret@example.test token=SECRET")):
        assert deliver_email(job.pk) == "FAILED"
    job.refresh_from_db()
    assert job.failure_code == "delivery_unknown" and job.sent_at is None
    assert Notification.objects.filter(pk=job.notice_id).exists()
    complaint.refresh_from_db()
    assert complaint.status == "ASSIGNED" and ComplaintHistory.objects.count() == 1
    assert "SECRET" not in json.dumps(list(EmailDelivery.objects.values()), default=str)
    with patch("workflow.email_delivery.send_mail") as send:
        assert deliver_email(job.pk) == "FAILED"
    send.assert_not_called()  # Unknown acceptance must not be blindly retried.


def test_anonymous_head_notices_and_email_are_minimal(complaint_factory, user_factory, settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    raw_reference = "a" * 32
    marker = "SECRET-IDENTITY-SESSION-CREDENTIAL"
    complaint = complaint_factory(anonymous=True, title=marker, description=marker * 2)
    complaint.reference_digest = hashlib.sha256(raw_reference.encode()).hexdigest()
    complaint.save(update_fields=["reference_digest"])
    head = user_factory(role="HEAD", department=complaint.department)
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM", remarks=marker)
    event = NotificationEvent.objects.get()
    assert event.anonymous and list(event.notices.values_list("recipient_id", flat=True)) == [head.pk]
    notice = get_notification(head, event.notices.get().pk)
    job = notice.email_delivery
    assert deliver_email(job.pk) == "SENT"
    assert mail.outbox[0].to == [head.email] and not mail.outbox[0].cc and not mail.outbox[0].bcc
    assert "Anonymous" in mail.outbox[0].body
    output = json.dumps(list(NotificationEvent.objects.values()), default=str) + mail.outbox[0].message().as_string()
    for forbidden in (marker, raw_reference, complaint.reference_digest, "submitted_by", "source_ip", "session"):
        assert forbidden not in output
    assert complaint.complaint_id in output and complaint.status in output
    with patch("workflow.email_delivery.send_mail") as send:
        assert deliver_email(job.pk) == "SENT"
    send.assert_not_called()


@pytest.mark.parametrize("change", ["inactive", "other_department", "admin", "unassigned", "no_email"])
def test_delivery_suppresses_no_longer_eligible_recipients(graph, department_factory, change):
    complaint, staff, _ = graph
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    job = EmailDelivery.objects.get(notice__recipient=staff)
    if change == "inactive":
        User.objects.filter(pk=staff.pk).update(is_active=False)
    elif change == "other_department":
        User.objects.filter(pk=staff.pk).update(department=department_factory())
    elif change == "admin":
        User.objects.filter(pk=staff.pk).update(role="ADMIN")
    elif change == "unassigned":
        Complaint.objects.filter(pk=complaint.pk).update(assignee=None)
    else:
        User.objects.filter(pk=staff.pk).update(email="")
    with patch("workflow.email_delivery.send_mail") as send:
        assert deliver_email(job.pk) == "SUPPRESSED"
    send.assert_not_called()


def test_worker_refuses_business_transaction_and_command_is_bounded(graph, settings):
    settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
    complaint, _, _ = graph
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    job = EmailDelivery.objects.first()
    with transaction.atomic(), pytest.raises(TransactionManagementError):
        deliver_email(job.pk)
    job.refresh_from_db()
    assert job.status == "PENDING"
    output = StringIO()
    call_command("deliver_notifications", limit=1, stdout=output)
    assert len(mail.outbox) == 1 and EmailDelivery.objects.filter(status="PENDING").count() == 3
    assert "Processed 1" in output.getvalue()


@pytest.mark.parametrize("result", [0, "invalid_address"])
def test_nonacceptance_and_invalid_addresses_are_recorded_safely(graph, result):
    complaint, staff, _ = graph
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    job = EmailDelivery.objects.get(notice__recipient=staff)
    if result == "invalid_address":
        User.objects.filter(pk=staff.pk).update(email="invalid\nBcc: leak@example.test")
    with patch("workflow.email_delivery.send_mail", return_value=0) as send:
        assert deliver_email(job.pk) == ("FAILED" if result == "invalid_address" else "RETRY_WAIT")
    if result == "invalid_address":
        send.assert_not_called()
    job.refresh_from_db()
    assert job.failure_code == ("invalid_address" if result == "invalid_address" else "not_accepted")


def test_duplicate_workers_claim_only_once(graph):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    from django.db import close_old_connections

    complaint, _, _ = graph
    record_history(complaint.complaint_id, "SUBMITTED", "COMPLAINANT")
    job = EmailDelivery.objects.get()
    barrier, lock, calls = Barrier(2), Lock(), []

    def send(*args, **kwargs):
        assert not transaction.get_connection().in_atomic_block
        with lock:
            calls.append(kwargs)
        return 1

    def work(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return deliver_email(job.pk)
        finally:
            close_old_connections()

    with patch("workflow.email_delivery.send_mail", side_effect=send), ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, range(2)))
    assert len(calls) == 1 and set(results) <= {"SENDING", "SENT"}
    job.refresh_from_db()
    assert job.status == "SENT"


def test_concurrent_publication_uses_history_identity(graph):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    complaint, _, _ = graph
    history = ComplaintHistory.objects.create(complaint_ref=complaint.complaint_id,
                                              event_type="ESCALATED", actor_kind="SYSTEM")
    barrier = Barrier(3)

    def publish(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return publish_history_event(history).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(publish, range(3)))
    assert len(set(ids)) == NotificationEvent.objects.count() == 1
    assert Notification.objects.count() == EmailDelivery.objects.count() == 4


def test_no_recipients_is_a_durable_event_without_jobs(complaint_factory):
    complaint = complaint_factory(anonymous=True)
    history = record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    assert NotificationEvent.objects.get(history=history).anonymous
    assert not Notification.objects.exists() and not EmailDelivery.objects.exists()


def test_anonymous_projection_reuses_f2_interface_after_authorization(complaint_factory, user_factory):
    import sys
    from types import ModuleType

    complaint = complaint_factory(anonymous=True)
    head = user_factory(role="HEAD", department=complaint.department)
    module = ModuleType("complaints.privacy")
    with patch.dict(sys.modules, {"complaints.privacy": module}):
        with patch.object(module, "complainant_label", return_value="Anonymous", create=True) as label:
            with patch.object(module, "anonymous_summary", return_value={
                    "complaint_id": complaint.complaint_id, "status": complaint.status,
                    "ignored_extra": "SECRET"}, create=True) as summary:
                record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    label.assert_called_once()
    summary.assert_called_once()
    assert get_notification(head, Notification.objects.get().pk).event.public_id == complaint.complaint_id
    assert "SECRET" not in json.dumps(list(NotificationEvent.objects.values()), default=str)


@pytest.mark.parametrize("invalid", ["label", "identifier", "state", "dependency"])
def test_invalid_f2_privacy_projection_fails_closed(complaint_factory, user_factory, invalid):
    import sys
    from types import ModuleType

    complaint = complaint_factory(anonymous=True)
    user_factory(role="HEAD", department=complaint.department)
    module = ModuleType("complaints.privacy")
    module.complainant_label = lambda complaint: "Identity" if invalid == "label" else "Anonymous"
    def summary(record):
        if invalid == "dependency":
            raise ModuleNotFoundError("Synthetic missing dependency", name="synthetic_dependency")
        return {"complaint_id": "SECRET" if invalid == "identifier" else record.complaint_id,
                "status": "SECRET" if invalid == "state" else record.status}
    module.anonymous_summary = summary
    with patch.dict(sys.modules, {"complaints.privacy": module}):
        with pytest.raises(ModuleNotFoundError if invalid == "dependency" else ValidationError):
            record_history(complaint.complaint_id, "ESCALATED", "SYSTEM")
    assert not ComplaintHistory.objects.exists() and not NotificationEvent.objects.exists()


def test_projection_authorizes_before_calling_f2_helpers(graph, user_factory):
    from workflow.notifications import _projection

    complaint, _, _ = graph
    with pytest.raises(Http404):
        _projection(complaint, user_factory())


def test_invalid_event_snapshot_rolls_back_history(graph):
    complaint, _, _ = graph
    with pytest.raises(ValidationError):
        record_history(complaint.complaint_id, "ESCALATED", "SYSTEM", new_state="UNKNOWN")
    assert not ComplaintHistory.objects.exists() and not NotificationEvent.objects.exists()


def test_command_rejects_invalid_batch_limit():
    with pytest.raises(CommandError, match="positive"):
        call_command("deliver_notifications", limit=0)
