"""Configuration audit contract (REQ-ADM-04, B29): who changed what, from what, to what.

F1 and F3 call ``record_change`` from inside the same transaction as the change, so a change
and its audit record are saved together or not at all. Sensitive values are replaced, never
stored. This is not complaint history and offers no way to edit or delete a record.
"""

from .models import ConfigAuditEvent, User

# The shared vocabulary: ``entity_type`` is the Django model's class name. F1 and F3 audit ONLY these entities, so the Administrator can read one
# consistent trail (REQ-ADM-04). Adding an entity is a deliberate, reviewed change to this list.
ENTITY_TYPES = {
    # F1: administration of reference data and users
    "Department": "Department",
    "Location": "Location",
    "User": "User role and membership",
    # F3: routing, SLA and escalation configuration
    "Category": "Category",
    "RoutingRule": "Routing rule",
    "SLAConfiguration": "SLA configuration",
    "EscalationPolicy": "Escalation policy",
}

# Field names that must never reach the audit table, whatever the caller passes.
SENSITIVE_FIELDS = frozenset(
    {"password", "passwd", "token", "secret", "session", "session_key", "reference", "tracking_reference"}
)
REDACTED = "[redacted]"


def _is_sensitive(key):
    return any(part in str(key).lower() for part in SENSITIVE_FIELDS)


def _clean_value(value):
    """Redact sensitive keys at every depth; leave only JSON-safe values."""
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _is_sensitive(key) else _clean_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_clean_value(item) for item in value]
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def _clean(values):
    return _clean_value(values or {})


def record_change(*, actor, entity_type, entity_id, action, old=None, new=None):
    """Append one audit record. ``actor`` must be the acting (authenticated) user.

    Raises ``ValueError`` for an unknown entity or action: that is a programming error in the
    calling module, caught in tests, never something a user can trigger.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"Unknown configuration entity {entity_type!r}; see ENTITY_TYPES.")
    if action not in ConfigAuditEvent.Action.values:
        raise ValueError(f"Unknown configuration action {action!r}.")
    for label, values in (("old", old), ("new", new)):
        if values is not None and not isinstance(values, dict):
            raise ValueError(f"{label} must be a dict of field values or None, not {type(values).__name__}.")
    if not isinstance(actor, User) or actor.pk is None:
        raise ValueError("A configuration change must be recorded against a saved user.")
    return ConfigAuditEvent.objects.create(
        actor=actor,
        actor_identifier=getattr(actor, "email", "") or "",
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        old_values=_clean(old),
        new_values=_clean(new),
    )
