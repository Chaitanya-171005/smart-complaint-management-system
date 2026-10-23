from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.history_service import (
    get_complaint_history,
    record_history,
)
from workflow.models import ComplaintHistory


class ComplaintHistoryTests(TestCase):
    def test_record_history_creates_event(self):
        event = record_history(
            complaint_ref="TEST-001",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.COMPLAINANT,
            new_state="SUBMITTED",
            remarks="Complaint submitted",
        )

        self.assertEqual(event.complaint_ref, "TEST-001")
        self.assertEqual(event.new_state, "SUBMITTED")
        self.assertTrue(event.occurred_at)

    def test_anonymous_remarks_are_cleared(self):
        event = record_history(
            complaint_ref="TEST-002",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.ANONYMOUS,
            remarks="Potentially identifying information",
        )

        self.assertEqual(event.remarks, "")

    def test_history_is_retrieved_for_one_complaint(self):
        record_history(
            complaint_ref="TEST-003",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.SYSTEM,
            new_state="SUBMITTED",
        )
        record_history(
            complaint_ref="TEST-004",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.SYSTEM,
            new_state="SUBMITTED",
        )

        history = get_complaint_history("TEST-003")

        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().complaint_ref, "TEST-003")

    def test_existing_history_cannot_be_edited(self):
        event = record_history(
            complaint_ref="TEST-005",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.SYSTEM,
        )

        event.remarks = "Changed"
        with self.assertRaises(ValidationError):
            event.save()

    def test_history_cannot_be_deleted(self):
        event = record_history(
            complaint_ref="TEST-006",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.SYSTEM,
        )

        with self.assertRaises(ValidationError):
            event.delete()

        self.assertTrue(
            ComplaintHistory.objects.filter(pk=event.pk).exists()
        )


    def test_bulk_update_is_blocked(self):
        event = record_history(
            complaint_ref="TEST-007",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.SYSTEM,
        )

        with self.assertRaises(ValidationError):
            ComplaintHistory.objects.filter(pk=event.pk).update(
                remarks="Tampered"
            )

        event.refresh_from_db()
        self.assertEqual(event.remarks, "")

    def test_bulk_delete_is_blocked(self):
        event = record_history(
            complaint_ref="TEST-008",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.SYSTEM,
        )

        with self.assertRaises(ValidationError):
            ComplaintHistory.objects.filter(pk=event.pk).delete()

        self.assertTrue(
            ComplaintHistory.objects.filter(pk=event.pk).exists()
        )
    def test_history_is_returned_chronologically(self):
        first = record_history(
            complaint_ref="TEST-009",
            event_type=ComplaintHistory.EventType.SUBMITTED,
            actor_kind=ComplaintHistory.ActorKind.SYSTEM,
            new_state="SUBMITTED",
        )
        second = record_history(
            complaint_ref="TEST-009",
            event_type=ComplaintHistory.EventType.STATUS_CHANGED,
            actor_kind=ComplaintHistory.ActorKind.STAFF,
            previous_state="SUBMITTED",
            new_state="IN_PROGRESS",
        )

        history = list(get_complaint_history("TEST-009"))

        self.assertEqual(
            [event.pk for event in history],
            [first.pk, second.pk],
        )