"""B09 configuration diagnostics run by Django check/runserver commands."""

from django.conf import settings
from django.core.checks import Error, Tags, register

VALID_EVIDENCE_BYTE_LIMITS = (5_000_000, 5 * 1024 * 1024)


def valid_evidence_byte_limit(value):
    # bool is an int subclass, but is not an upload-size policy.
    return type(value) is int and value in VALID_EVIDENCE_BYTE_LIMITS


@register(Tags.files)
def check_evidence_byte_limit(app_configs, **kwargs):
    if valid_evidence_byte_limit(getattr(settings, "EVIDENCE_MAX_BYTES", None)):
        return []
    return [Error(
        "EVIDENCE_MAX_BYTES must be the integer 5000000 or 5242880.",
        hint="Set EVIDENCE_MAX_BYTES to a supported D02 candidate; team confirmation is still pending.",
        obj="EVIDENCE_MAX_BYTES",
        id="complaints.E001",
    )]
