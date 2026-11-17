"""B21 contract tests using real records, permissions and admin requests."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from workflow.history_service import (
    get_authorized_complaint_history, get_complaint_history, record_history,
)
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("event_type", ComplaintHistory.EventType.values)
def test_event_contract(event_type, complaint_factory):
    complaint = complaint_factory()
    before = timezone.now()
    event = record_history(complaint.complaint_id, event_type, "SYSTEM",
                           "ASSIGNED", "IN_PROGRESS", "Synthetic operation")
    event.refresh_from_db()
    assert event.actor_kind == "SYSTEM" and event.event_type == event_type
    assert (event.previous_state, event.new_state, event.remarks) == (
        "ASSIGNED", "IN_PROGRESS", "Synthetic operation")
    assert before <= event.occurred_at <= timezone.now()


@pytest.mark.parametrize("field,value", [
    ("complaint_ref", None), ("complaint_ref", ""), ("complaint_ref", "   "),
    ("complaint_ref", "x" * 101), ("previous_state", "x" * 51),
    ("new_state", "x" * 51), ("event_type", "UNKNOWN"), ("actor_kind", "UNKNOWN"),
])
def test_invalid_event_leaves_no_history(field, value):
    values = dict(complaint_ref="synthetic", event_type="SUBMITTED", actor_kind="SYSTEM")
    values[field] = value
    with pytest.raises(ValidationError):
        record_history(**values)
    assert not ComplaintHistory.objects.exists()


def test_direct_model_creation_cannot_bypass_validation():
    with pytest.raises(ValidationError):
        ComplaintHistory.objects.create(complaint_ref="x" * 101,
                                       event_type="SUBMITTED", actor_kind="SYSTEM")


def test_ordering_uses_timestamp_then_primary_key_and_is_scoped():
    now = timezone.now()
    with patch("django.utils.timezone.now", return_value=now + timedelta(minutes=1)):
        later_time = record_history("one", "RESOLVED", "STAFF")
    with patch("django.utils.timezone.now", return_value=now):
        first = record_history("one", "SUBMITTED", "SYSTEM")
        second = record_history("one", "ALLOCATED", "SYSTEM")
        record_history("other", "SUBMITTED", "SYSTEM")
    assert list(get_complaint_history("one")) == [first, second, later_time]


@pytest.mark.parametrize("failure", ["operation", "history"])
def test_operation_and_history_roll_back_together(complaint_factory, failure):
    complaint = complaint_factory()
    with pytest.raises(ValidationError if failure == "history" else RuntimeError):
        with transaction.atomic():
            complaint.status = "IN_PROGRESS"
            complaint.save(update_fields=["status"])
            record_history(complaint.complaint_id, "STATUS_CHANGED", "STAFF",
                           "ASSIGNED", "IN_PROGRESS")
            if failure == "history":
                record_history(complaint.complaint_id, "INVALID", "SYSTEM")
            else:
                raise RuntimeError("controlled operation failure")
    complaint.refresh_from_db()
    assert complaint.status == "ASSIGNED"
    assert not ComplaintHistory.objects.exists()


def test_nested_savepoint_failure_preserves_prior_committed_history(complaint_factory):
    complaint = complaint_factory()
    earlier = record_history(complaint.complaint_id, "SUBMITTED", "SYSTEM")
    with transaction.atomic():
        with pytest.raises(ValidationError):
            record_history(complaint.complaint_id, "INVALID", "SYSTEM")
        later = record_history(complaint.complaint_id, "ALLOCATED", "SYSTEM")
    assert list(get_complaint_history(complaint.complaint_id)) == [earlier, later]


def test_anonymous_remarks_are_removed_in_service_and_model():
    for create in (record_history, lambda **kw: ComplaintHistory.objects.create(**kw)):
        event = create(complaint_ref="public-id", event_type="SUBMITTED",
                       actor_kind="ANONYMOUS", remarks="Synthetic identifying data")
        event.refresh_from_db()
        assert event.remarks == "" and event.actor_kind == "ANONYMOUS"


def test_authorized_read_uses_real_owner_department_and_current_account(
        complaint_factory, user_factory, department_factory):
    complaint = complaint_factory()
    event = record_history(complaint.complaint_id, "SUBMITTED", "SYSTEM")
    head = user_factory(role="HEAD", department=complaint.department)
    staff = user_factory(role="STAFF", department=complaint.department)
    for user in (complaint.submitted_by, head, staff):
        assert list(get_authorized_complaint_history(user, complaint.complaint_id)) == [event]
    outsiders = [AnonymousUser(), None, user_factory(), user_factory(role="ADMIN"),
                 user_factory(role="HEAD", department=department_factory())]
    for user in outsiders:
        with pytest.raises(Http404):
            get_authorized_complaint_history(user, complaint.complaint_id)
    User.objects.filter(pk=head.pk).update(is_active=False)
    with pytest.raises(Http404):
        get_authorized_complaint_history(head, complaint.complaint_id)
    User.objects.filter(pk=staff.pk).update(department=department_factory())
    with pytest.raises(Http404):
        get_authorized_complaint_history(staff, complaint.complaint_id)
    User.objects.filter(pk=complaint.submitted_by_id).update(role="ADMIN")
    with pytest.raises(Http404):
        get_authorized_complaint_history(complaint.submitted_by, complaint.complaint_id)
    with pytest.raises(Http404):
        get_authorized_complaint_history(complaint.submitted_by, "missing")
    assert list(get_complaint_history(complaint.complaint_id)) == [event]


def test_reference_is_not_full_history_authorization(complaint_factory, user_factory):
    complaint = complaint_factory(anonymous=True)
    record_history(complaint.complaint_id, "SUBMITTED", "ANONYMOUS")
    with pytest.raises(Http404):
        get_authorized_complaint_history(user_factory(), complaint.complaint_id)
    with pytest.raises(Http404):
        get_authorized_complaint_history(AnonymousUser(), complaint.reference_digest)


def test_superuser_admin_has_no_mutation_interface(client, user_factory):
    admin = user_factory(role="ADMIN", is_staff=True, is_superuser=True)
    client.force_login(admin)
    event = record_history("synthetic", "SUBMITTED", "SYSTEM", remarks="original")
    base = "admin:workflow_complainthistory_"
    change = reverse(base + "change", args=[event.pk])
    response = client.get(change)
    assert response.status_code == 200
    for control in (b'name="_save"', b'class="deletelink"', b'name="remarks"'):
        assert control not in response.content
    assert client.post(change, {"remarks": "changed", "_save": "Save"}).status_code == 403
    for suffix, args in (("add", []), ("delete", [event.pk])):
        url = reverse(base + suffix, args=args)
        assert client.get(url).status_code == 403
        assert client.post(url, {"post": "yes"}).status_code == 403
    response = client.post(reverse(base + "changelist"), {
        "action": "delete_selected", "_selected_action": [event.pk], "post": "yes"})
    assert response.status_code in (200, 302)
    event.refresh_from_db()
    assert event.remarks == "original" and ComplaintHistory.objects.count() == 1


def test_orm_mutation_shortcuts_are_refused():
    event = record_history("synthetic", "SUBMITTED", "SYSTEM")
    event.remarks = "changed"
    for operation in (
        lambda: ComplaintHistory.objects.bulk_update([event], ["remarks"]),
        lambda: ComplaintHistory.objects.update_or_create(pk=event.pk, defaults={"remarks": "changed"}),
        lambda: ComplaintHistory.objects.bulk_create([ComplaintHistory(
            complaint_ref="new", event_type="SUBMITTED", actor_kind="SYSTEM")]),
    ):
        with pytest.raises(ValidationError), transaction.atomic():
            operation()
    event.refresh_from_db()
    assert event.remarks == ""


@pytest.mark.django_db(transaction=True)
def test_concurrent_appends_preserve_every_event():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    barrier = Barrier(4)

    def append(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return record_history("concurrent", "ESCALATED", "SYSTEM",
                                  remarks=f"Synthetic event {index}").pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(append, range(4)))
    history = list(get_complaint_history("concurrent"))
    assert {event.pk for event in history} == set(ids) and len(history) == 4
    assert {event.remarks for event in history} == {f"Synthetic event {i}" for i in range(4)}
    assert history == sorted(history, key=lambda event: (event.occurred_at, event.pk))
