"""Text validation for complaint intake, before persistence or notifications."""

import unicodedata

from django.core.exceptions import ValidationError


def validate_single_line(value):
    if any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value):
        raise ValidationError(
            "Use a single line without control or formatting characters.",
            code="invalid_single_line",
        )


def visible_length(value):
    """Count letters, numbers, punctuation and symbols, excluding spacing/marks.

    Combining marks may accompany letters but cannot inflate this minimum on
    their own. This is a conservative character count, not a grapheme counter.
    """
    return sum(unicodedata.category(char)[0] in "LNPS" for char in value)


def validate_description(value):
    if visible_length(value) < 20:
        raise ValidationError(
            "Enter at least 20 visible characters (excluding spaces and invisible characters).",
            code="min_visible_length",
        )
