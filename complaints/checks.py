"""B09 configuration diagnostics run by Django check/runserver commands."""

from django.conf import settings
from django.core.checks import Error, Tags, register

from .transport import anonymous_transport_ready

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


def anonymous_release_ready():
    middleware = getattr(settings, "MIDDLEWARE", [])
    notice = getattr(settings, "COMPLAINT_EMERGENCY_NOTICE", "")
    return bool(
        middleware and middleware[0] == "complaints.privacy_middleware.AnonymousPrivacyMiddleware"
        and not settings.DEBUG and not settings.CSRF_USE_SESSIONS
        and settings.COMPLAINT_INTAKE_ENABLED and settings.ANONYMOUS_INTAKE_ENABLED
        and settings.ANONYMOUS_PRIVACY_READY and isinstance(notice, str) and notice.strip()
        and anonymous_transport_ready()
    )


@register(Tags.security, deploy=True)
def check_anonymous_privacy(app_configs, **kwargs):
    if not settings.ANONYMOUS_INTAKE_ENABLED or anonymous_release_ready():
        return []
    return [Error(
        "Anonymous intake is enabled without its complete privacy/release configuration.",
        hint="Use first-position AnonymousPrivacyMiddleware, DEBUG=False, cookie-based CSRF, "
             "confirmed emergency information, HTTPS mode, secure session/CSRF cookies, "
             "SSL redirection, HSTS, verified transport and both intake/privacy gates. See docs/B12_PRIVACY.md.",
        id="complaints.E002",
    )]


def tracking_release_ready():
    from .tracking_limits import limiter_configured
    from .tracking_source import tracking_source_configured
    middleware = getattr(settings, "MIDDLEWARE", [])
    return bool(
        middleware and middleware[0] == "complaints.privacy_middleware.AnonymousPrivacyMiddleware"
        and not settings.DEBUG and not settings.CSRF_USE_SESSIONS
        and settings.ANONYMOUS_PRIVACY_READY and settings.ANONYMOUS_TRACKING_ENABLED
        and limiter_configured() and anonymous_transport_ready() and tracking_source_configured()
    )


@register(Tags.security, deploy=True)
def check_tracking_privacy(app_configs, **kwargs):
    if not settings.ANONYMOUS_TRACKING_ENABLED or tracking_release_ready():
        return []
    return [Error(
        "Anonymous tracking is enabled without its complete privacy/limiter configuration.",
        hint="Keep tracking disabled until HTTPS/peer-address, memory-only Redis and privacy "
             "checks are verified. See docs/B13_TRACKING.md.",
        id="complaints.E003",
    )]
