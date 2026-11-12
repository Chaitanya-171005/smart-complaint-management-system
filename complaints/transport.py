"""Static anonymous HTTPS prerequisites; ingress trust still needs E03 review."""

from django.conf import settings


def anonymous_transport_ready():
    mode = getattr(settings, "SCMS_HTTPS_MODE", "")
    proxy_header = settings.SECURE_PROXY_SSL_HEADER
    return bool(
        getattr(settings, "ANONYMOUS_TRANSPORT_VERIFIED", False)
        and settings.SECURE_HSTS_SECONDS > 0
        and settings.SECURE_SSL_REDIRECT and settings.CSRF_COOKIE_SECURE
        and settings.SESSION_COOKIE_SECURE
        and "django.middleware.security.SecurityMiddleware" in settings.MIDDLEWARE
        and ((mode == "direct" and proxy_header is None)
             or (mode == "proxy" and proxy_header == ("HTTP_X_FORWARDED_PROTO", "https")))
    )
