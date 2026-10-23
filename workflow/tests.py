from django.test import TestCase

# Create your tests here.
from django.test import SimpleTestCase
from unittest.mock import Mock

from workflow.services import get_owned_complaints


class OwnComplaintTrackingTests(SimpleTestCase):

    def test_user_can_only_see_own_complaints(self):
        user = Mock()
        user.is_authenticated = True

        complaints = Mock()
        owned_complaints = Mock()
        complaints.filter.return_value = owned_complaints

        result = get_owned_complaints(user, complaints)

        complaints.filter.assert_called_once_with(
            submitted_by=user
        )
        self.assertIs(result, owned_complaints)

    def test_unauthenticated_user_gets_no_complaints(self):
        user = Mock()
        user.is_authenticated = False

        complaints = Mock()
        empty_complaints = Mock()
        complaints.none.return_value = empty_complaints

        result = get_owned_complaints(user, complaints)

        complaints.none.assert_called_once_with()
        complaints.filter.assert_not_called()
        self.assertIs(result, empty_complaints)

from workflow.services import filter_complaints


class ComplaintFilteringTests(SimpleTestCase):

    def test_filter_by_status(self):
        complaints = Mock()
        filtered = Mock()
        complaints.filter.return_value = filtered

        result = filter_complaints(complaints, status="RESOLVED")

        complaints.filter.assert_called_once_with(status="RESOLVED")
        self.assertIs(result, filtered)

    def test_filter_by_category(self):
        complaints = Mock()
        filtered = Mock()
        complaints.filter.return_value = filtered

        result = filter_complaints(complaints, category="Electrical")

        complaints.filter.assert_called_once_with(category="Electrical")
        self.assertIs(result, filtered)

    def test_filter_by_status_and_category(self):
        complaints = Mock()
        status_filtered = Mock()
        category_filtered = Mock()

        complaints.filter.return_value = status_filtered
        status_filtered.filter.return_value = category_filtered

        result = filter_complaints(
            complaints,
            status="IN_PROGRESS",
            category="Plumbing",
        )

        complaints.filter.assert_called_once_with(status="IN_PROGRESS")
        status_filtered.filter.assert_called_once_with(category="Plumbing")
        self.assertIs(result, category_filtered)

from workflow.services import paginate_complaints


class ComplaintPaginationTests(SimpleTestCase):

    def test_first_page_contains_25_complaints(self):
        complaints = list(range(60))

        page = paginate_complaints(complaints, 1)

        self.assertEqual(len(page.object_list), 25)
        self.assertEqual(page.number, 1)
        self.assertEqual(page.paginator.num_pages, 3)

    def test_last_page_contains_remaining_complaints(self):
        complaints = list(range(60))

        page = paginate_complaints(complaints, 3)

        self.assertEqual(len(page.object_list), 10)
        self.assertEqual(page.number, 3)

    def test_invalid_page_returns_last_page(self):
        complaints = list(range(60))

        page = paginate_complaints(complaints, 999)

        self.assertEqual(page.number, 3)

from django.core.exceptions import PermissionDenied
from workflow.services import get_owned_complaint


class ComplaintDetailAccessTests(SimpleTestCase):

    def test_user_can_get_their_own_complaint(self):
        user = Mock()
        user.is_authenticated = True

        complaint = Mock()
        complaints = Mock()
        owned_queryset = Mock()
        owned_queryset.get.return_value = complaint
        complaints.filter.return_value = owned_queryset

        result = get_owned_complaint(user, complaints, 123)

        complaints.filter.assert_called_once_with(
            submitted_by=user
        )
        owned_queryset.get.assert_called_once_with(pk=123)
        self.assertIs(result, complaint)

    def test_anonymous_user_is_denied(self):
        user = Mock()
        user.is_authenticated = False

        with self.assertRaises(PermissionDenied):
            get_owned_complaint(user, Mock(), 123)

