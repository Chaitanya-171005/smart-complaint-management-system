
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from workflow.resolution_service import (
    IN_PROGRESS,
    RESOLVED,
    validate_resolution,
)


class ResolutionValidationTests(SimpleTestCase):
    def test_valid_resolution(self):
        result = validate_resolution(
            IN_PROGRESS,
            "The reported issue has been inspected and repaired.",
        )
        self.assertEqual(result, RESOLVED)

    def test_rejects_wrong_state(self):
        with self.assertRaises(ValidationError):
            validate_resolution(
                "SUBMITTED",
                "The reported issue has been inspected and repaired.",
            )

    def test_rejects_short_remarks(self):
        with self.assertRaises(ValidationError):
            validate_resolution(IN_PROGRESS, "Fixed it.")

    def test_rejects_whitespace_only_remarks(self):
        with self.assertRaises(ValidationError):
            validate_resolution(IN_PROGRESS, " " * 25)

    def test_accepts_exactly_twenty_characters(self):
        result = validate_resolution(IN_PROGRESS, "12345678901234567890")
        self.assertEqual(result, RESOLVED)

    def test_rejects_non_string_remarks(self):
        with self.assertRaises(ValidationError):
            validate_resolution(IN_PROGRESS, None)
