from .models import SecurityEvent


def record_event(event_type, *, user=None, identifier="", detail=""):
    """Append a security event. Callers must never pass secrets in any argument."""
    return SecurityEvent.objects.create(
        event_type=event_type,
        user=user,
        identifier=(identifier or "")[:254],
        detail=(detail or "")[:255],
    )
