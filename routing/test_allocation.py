import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404

from accounts.models import User
from routing.allocation import AllocationError, StaleAllocation, allocate_complaint
from workflow.history_service import record_history
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_allocation(department, head_user, staff_user, complaint_factory):
    return head_user, staff_user, complaint_factory(department=department)


def allocate(actor, complaint, target, expected=None, reason=""):
    return allocate_complaint(actor=actor, complaint_id=complaint.complaint_id,
                              assignee=target, expected_assignee_id=expected, reason=reason)


def test_first_allocation_changes_only_assignee_and_records_history(setup_allocation):
    head, staff, complaint = setup_allocation
    before = type(complaint).objects.filter(pk=complaint.pk).values().get()
    result = allocate(head, complaint, staff)
    after = type(complaint).objects.filter(pk=complaint.pk).values().get()
    assert result.assignee == staff
    assert {key: value for key, value in after.items() if key != "assignee_id"} == {key: value for key, value in before.items() if key != "assignee_id"}
    event = ComplaintHistory.objects.get(complaint_ref=complaint.complaint_id)
    assert (event.event_type, event.actor_kind, event.actor, event.assignee) == ("ALLOCATED", "HEAD", head, staff)
    assert event.previous_state == event.new_state == complaint.status


def test_reassignments_preserve_history(setup_allocation, user_factory, department):
    head, staff, complaint = setup_allocation
    earlier = record_history(complaint.complaint_id, "SUBMITTED", "SYSTEM")
    original = ComplaintHistory.objects.filter(pk=earlier.pk).values().get()
    allocate(head, complaint, staff)
    other = user_factory(role=User.Role.STAFF, department=department)
    allocate(head, complaint, other.pk, staff.pk, "  coverage needed  ")
    event = ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id, event_type="REASSIGNED").get()
    assert event.remarks == "coverage needed" and event.actor == head and event.assignee == other
    allocate(head, complaint, staff, other.pk, "return")
    assert ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id, event_type="REASSIGNED").count() == 2
    assert ComplaintHistory.objects.filter(pk=earlier.pk).values().get() == original


@pytest.mark.parametrize("reason,same,code", [("", False, "reason_required"), ("   ", False, "reason_required"),
                                            ("x" * 501, False, "reason_too_long"), ("reason", True, "same_assignee")])
def test_reassignment_validation(setup_allocation, user_factory, department, reason, same, code):
    head, staff, complaint = setup_allocation
    complaint.assignee = staff
    complaint.save(update_fields=["assignee"])
    target = staff if same else user_factory(role=User.Role.STAFF, department=department)
    with pytest.raises(AllocationError) as exc:
        allocate(head, complaint, target, staff.pk, reason)
    assert exc.value.code == code
    complaint.refresh_from_db()
    assert complaint.assignee == staff and not ComplaintHistory.objects.exists()


@pytest.mark.parametrize("kind", ["cross", "inactive", "nonstaff", "missing"])
def test_invalid_targets_refused(setup_allocation, user_factory, department, department_factory, kind):
    head, _, complaint = setup_allocation
    if kind == "missing":
        target = 99999999
    else:
        target = user_factory(role=User.Role.COMPLAINANT if kind == "nonstaff" else User.Role.STAFF,
                              department=department_factory() if kind == "cross" else department,
                              is_active=kind != "inactive")
    with pytest.raises(PermissionDenied):
        allocate(head, complaint, target)
    complaint.refresh_from_db()
    assert complaint.assignee is None and not ComplaintHistory.objects.exists()


@pytest.mark.parametrize("role", ["HEAD", "STAFF", "COMPLAINANT", "ADMIN"])
def test_unauthorized_actor_refused(setup_allocation, user_factory, department_factory, role):
    _, staff, complaint = setup_allocation
    actor = user_factory(role=role, department=department_factory() if role in ("HEAD", "STAFF") else None)
    with pytest.raises(Http404):
        allocate(actor, complaint, staff)
    complaint.refresh_from_db()
    assert complaint.assignee is None and not ComplaintHistory.objects.exists()


@pytest.mark.parametrize("status", ["RESOLVED", "CLOSED", "REJECTED"])
def test_closed_status_refused(setup_allocation, status):
    head, staff, complaint = setup_allocation
    complaint.status = status
    complaint.save(update_fields=["status"])
    with pytest.raises(AllocationError) as exc:
        allocate(head, complaint, staff)
    assert exc.value.code == "not_allocatable"
    complaint.refresh_from_db()
    assert complaint.assignee is None and not ComplaintHistory.objects.exists()


def test_stale_allocation_preserves_first_change(setup_allocation, user_factory, department):
    head, staff, complaint = setup_allocation
    allocate(head, complaint, staff)
    other = user_factory(role=User.Role.STAFF, department=department)
    with pytest.raises(StaleAllocation) as exc:
        allocate(head, complaint, other)
    assert exc.value.code == "modified_record"
    complaint.refresh_from_db()
    assert complaint.assignee == staff and ComplaintHistory.objects.count() == 1


def test_history_failure_rolls_back(setup_allocation, monkeypatch):
    head, staff, complaint = setup_allocation
    def fail(*args, **kwargs):
        raise RuntimeError("history unavailable")
    monkeypatch.setattr("routing.allocation.record_history", fail)
    with pytest.raises(RuntimeError, match="history unavailable"):
        allocate(head, complaint, staff)
    complaint.refresh_from_db()
    assert complaint.assignee is None and not ComplaintHistory.objects.exists()


def test_missing_complaint_refused(setup_allocation):
    head, staff, _ = setup_allocation
    with pytest.raises(Http404):
        allocate_complaint(actor=head, complaint_id="SCMS-2000-999999", assignee=staff, expected_assignee_id=None)
