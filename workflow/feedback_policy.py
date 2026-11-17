"""Shared feedback limits; D04 due-time handling is deliberately unchanged."""
from django.conf import settings
from django.core.exceptions import ValidationError


def maximum_reopens():
    value = getattr(settings, "COMPLAINT_MAX_REOPENS", 2)
    if type(value) is not int or not 0 <= value <= 32767:
        raise ValidationError("The reopen policy is unavailable.", code="invalid_reopen_policy")
    return value
