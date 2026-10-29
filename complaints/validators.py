"""Text validation for complaint intake, before persistence or notifications."""

import unicodedata

from django.core.exceptions import ValidationError

# Unicode Bidi_Control characters, plus deprecated directional formatting codes.
# Ordinary Arabic/Hebrew letters and joiners are not direction-control characters.
BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u2066\u2067\u2068\u2069\u206a\u206b\u206c\u206d\u206e\u206f"
)


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
    if any(char in BIDI_CONTROLS for char in value):
        raise ValidationError(
            "Remove bidirectional formatting controls from the description.",
            code="invalid_bidi_control",
        )
    # Interior spaces count toward the SRS character minimum. Invisible control/
    # format characters and combining-mark padding cannot supply missing text.
    length = sum(
        unicodedata.category(char)[0] in "LNPS" or unicodedata.category(char) == "Zs"
        for char in value
    )
    if length < 20 or not visible_length(value):
        raise ValidationError(
            "Enter at least 20 characters; spaces count, invisible padding does not.",
            code="min_visible_length",
        )
