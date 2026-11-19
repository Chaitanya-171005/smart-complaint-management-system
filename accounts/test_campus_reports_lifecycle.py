"""B30 against the real F4 lifecycle (not factory-set fields): confirm, reject, reopen.

Needs F4 (workflow.lifecycle, confirmation and reopening services), so it can only be added once
that work is on Main.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from accounts import campus_reports as reports
from workflow.confirmation_service import confirm_resolution
from workflow.lifecycle import get_transition_revision
from workflow.reopening_service import reject_resolution
from workflow.test_confirmation import case  # noqa: F401  (fixture: a RESOLVED complaint, its owner, its Head)

pytestmark = pytest.mark.django_db(transaction=True)
REASON = "Synthetic unresolved problem needs attention."


def report_for(complaint):
    day = complaint.submitted_at.date()
    return reports.build_report(day, day + timedelta(days=1), now=timezone.now())


def stamp_resolution(complaint, hours):
    complaint.resolved_at = complaint.submitted_at + timedelta(hours=hours)
    complaint.save(update_fields=["resolved_at"])


def test_resolved_complaint_is_measured_then_closed_complaint_stays_measured(case):  # noqa: F811
    complaint, owner, _ = case
    stamp_resolution(complaint, 6)
    assert report_for(complaint).mean_hours == Decimal("6.00")

    with patch("workflow.email_delivery.send_mail"):
        confirm_resolution(
            actor=owner, complaint_id=complaint.complaint_id, rating=4,
            expected_revision=get_transition_revision(
                actor=owner, complaint_id=complaint.complaint_id, target_state="CLOSED"),
        )
    report = report_for(complaint)
    assert (report.open_count, report.resolved_measured, report.mean_hours) == (0, 1, Decimal("6.00"))


def test_rejected_resolution_becomes_open_reopened_and_unmeasured(case):  # noqa: F811
    complaint, owner, _ = case
    stamp_resolution(complaint, 6)

    with patch("workflow.email_delivery.send_mail"):
        reject_resolution(
            actor=owner, complaint_id=complaint.complaint_id, reason=REASON,
            expected_revision=get_transition_revision(
                actor=owner, complaint_id=complaint.complaint_id, target_state="REOPENED"),
        )
    complaint.refresh_from_db()
    assert complaint.status == "REOPENED" and complaint.resolved_at is not None  # F4 keeps the old time

    report = report_for(complaint)
    assert report.open_count == 1
    assert (report.reopened_count, report.reopen_total) == (1, 1)
    assert report.resolved_measured == 0 and report.mean_hours is None


def test_rejection_at_the_limit_is_still_resolved_and_counts_each_reopen(case):  # noqa: F811
    complaint, owner, _ = case
    stamp_resolution(complaint, 6)
    complaint.reopen_count = 2
    complaint.save(update_fields=["reopen_count"])

    with patch("workflow.email_delivery.send_mail"):
        reject_resolution(
            actor=owner, complaint_id=complaint.complaint_id, reason=REASON,
            expected_revision=get_transition_revision(
                actor=owner, complaint_id=complaint.complaint_id, target_state="REOPENED"),
        )
    complaint.refresh_from_db()
    report = report_for(complaint)
    # F4 keeps it RESOLVED, adds no reopen, and raises Head review through history (not the overdue flag).
    assert complaint.status == "RESOLVED" and complaint.reopen_count == 2
    assert (report.reopened_count, report.reopen_total) == (1, 2)
    assert report.resolved_measured == 1
    assert report.escalated_count == 0


def test_a_complaint_rejected_worked_again_and_resolved_is_measured_to_its_latest_resolution(case, user_factory):  # noqa: F811
    from workflow.resolution_service import progress_complaint, resolve_complaint

    complaint, owner, _ = case
    staff = user_factory(role="STAFF", department=complaint.department)
    complaint.assignee = staff
    complaint.save(update_fields=["assignee"])
    # Submitted ten hours ago and first resolved after two, so the second resolution (now) is clearly later.
    past = timezone.now() - timedelta(hours=10)
    type(complaint).objects.filter(pk=complaint.pk).update(submitted_at=past, due_at=past + timedelta(hours=24))
    complaint.refresh_from_db()
    stamp_resolution(complaint, 2)
    first_resolution = complaint.resolved_at

    with patch("workflow.email_delivery.send_mail"):
        reject_resolution(
            actor=owner, complaint_id=complaint.complaint_id, reason=REASON,
            expected_revision=get_transition_revision(
                actor=owner, complaint_id=complaint.complaint_id, target_state="REOPENED"),
        )
        assert report_for(complaint).resolved_measured == 0  # not measured while reopened
        progress_complaint(
            actor=staff, complaint_id=complaint.complaint_id, remarks="Working on it again.",
            expected_revision=get_transition_revision(
                actor=staff, complaint_id=complaint.complaint_id, target_state="IN_PROGRESS"),
        )
        resolve_complaint(
            actor=staff, complaint_id=complaint.complaint_id,
            remarks="Replaced the faulty part and tested the light.",
            expected_revision=get_transition_revision(
                actor=staff, complaint_id=complaint.complaint_id, target_state="RESOLVED"),
        )
    complaint.refresh_from_db()
    assert complaint.status == "RESOLVED" and complaint.reopen_count == 1
    # resolved again just now, so the measured time is submission to the second resolution, not the first
    assert complaint.resolved_at > first_resolution
    report = reports.build_report(
        complaint.submitted_at.date(), complaint.submitted_at.date() + timedelta(days=1), now=timezone.now())
    assert (report.resolved_measured, report.reopened_count, report.reopen_total) == (1, 1, 1)
    expected = (complaint.resolved_at - complaint.submitted_at).total_seconds() / 3600
    assert abs(float(report.mean_hours) - expected) < 0.01
