from django.core.exceptions import ValidationError


class LetterAndDigitValidator:
    """REQ-AUTH-01: a password needs at least one letter and one digit."""

    def validate(self, password, user=None):
        if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            raise ValidationError(
                "Password must include at least one letter and one digit.",
                code="password_no_letter_or_digit",
            )

    def get_help_text(self):
        return "Your password must be at least 8 characters and include a letter and a digit."
