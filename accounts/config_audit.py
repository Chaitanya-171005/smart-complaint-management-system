"""Configuration audit contract (REQ-ADM-04, B29): who changed what, from what, to what.

F1 and F3 call ``record_change`` from inside the same transaction as the change, so a change
and its audit record are saved together or not at all. Sensitive values are replaced, never
stored. This is not complaint history and offers no way to edit or delete a record.
"""

from .models import ConfigAuditEvent

# Field names that must never reach the audit table, whatever the caller passes.
SENSITIVE_FIELDS = frozenset(
    {"password", "passwd", "token", "secret", "session", "session_key", "reference", "tracking_reference"}
)
REDACTED = "[redacted]"


def _clean(values):
    cleaned = {}
    for key, value in (values or {}).items():
        if any(part in key.lower() for part in SENSITIVE_FIELDS):
            cleaned[key] = REDACTED
        else:
            cleaned[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
    return cleaned


def record_change(*, actor, entity_type, entity_id, action, old=None, new=None):
    """Append one audit record. ``actor`` must be the acting (authenticated) user."""
    return ConfigAuditEvent.objects.create(
        actor=actor,
        actor_identifier=getattr(actor, "email", "") or "",
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        old_values=_clean(old),
        new_values=_clean(new),
    )
