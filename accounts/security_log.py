"""The one way to write a security event (REQ-SEC-08). Policy: docs/SECURITY_LOGGING.md."""

import re

from .models import SecurityEvent

REDACTED = "[redacted]"

# Anything that looks like a secret is replaced, whatever the caller passed: an anonymous
# complaint reference (32 lowercase hex), a Django session key (32 alphanumerics), a SHA-256
# digest (64 hex) or any other long token-like run. Real words and ids are far shorter.
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9_\-]{32,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|session(?:id|_key)?|sessionid|reference)\b\s*[=:]\s*\S+"
)


def scrub(text):
    """Return ``text`` with secret-looking values replaced. Safe to call on any string."""
    text = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}={REDACTED}", text or "")
    return _TOKEN_LIKE.sub(REDACTED, text)


def record_event(event_type, *, user=None, identifier="", target="", detail=""):
    """Append one security event.

    ``user`` is the actor (None when unauthenticated or anonymous). ``identifier`` is the actor's
    sign-in email, or what was typed at login; it is empty for anonymous actors. ``target`` names
    what was acted on as ``Model#id``. Free text is scrubbed, so a secret passed by mistake is
    never stored. An unknown ``event_type`` is a programming error.
    """
    if event_type not in SecurityEvent.EventType.values:
        raise ValueError(f"Unknown security event type {event_type!r}.")
    identifier = identifier or ""
    if "@" not in identifier:  # emails are the one identifier format that is allowed through
        identifier = scrub(identifier)
    return SecurityEvent.objects.create(
        event_type=event_type,
        user=user,
        identifier=identifier[:254],
        target=scrub(target)[:100],
        detail=scrub(detail)[:255],
    )
