"""Validated Django 6.1 MAILERS configuration; never opens a connection."""

import math

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email


def mail_config(env):
    mode = env.get("DJANGO_MAIL_BACKEND", "console").strip()
    if mode not in {"console", "smtp"}:
        raise ImproperlyConfigured("DJANGO_MAIL_BACKEND must be console or smtp.")

    def boolean(name, default):
        value = env.get(name, default).strip().lower()
        if value not in {"true", "false"}:
            raise ImproperlyConfigured(f"{name} must be True or False.")
        return value == "true"

    tls = boolean("DJANGO_SMTP_USE_TLS", "True")
    ssl = boolean("DJANGO_SMTP_USE_SSL", "False")
    if tls and ssl:
        raise ImproperlyConfigured("SMTP TLS and SSL are mutually exclusive.")
    try:
        port = int(env.get("DJANGO_SMTP_PORT") or ("465" if ssl else "587"))
        timeout = float(env.get("DJANGO_SMTP_TIMEOUT", "10"))
        if not 1 <= port <= 65535 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ImproperlyConfigured("SMTP requires a valid port and a finite positive timeout.") from None

    sender = env.get("DJANGO_DEFAULT_FROM_EMAIL", "").strip() or "webmaster@localhost"
    if mode == "smtp":
        host = env.get("DJANGO_SMTP_HOST", "").strip()
        if not host or any(c.isspace() for c in host) or "://" in host:
            raise ImproperlyConfigured("DJANGO_SMTP_HOST must be a hostname, without a URL scheme.")
        if not (tls or ssl):
            raise ImproperlyConfigured("SMTP requires STARTTLS or implicit TLS (SSL).")
        if (tls and port == 465) or (ssl and port == 587):
            raise ImproperlyConfigured("SMTP port contradicts the selected TLS mode.")
        try:
            validate_email(sender)
        except ValidationError:
            raise ImproperlyConfigured("DJANGO_DEFAULT_FROM_EMAIL must be a valid sender address.") from None
        if not env.get("DJANGO_DEFAULT_FROM_EMAIL", "").strip():
            raise ImproperlyConfigured("DJANGO_DEFAULT_FROM_EMAIL is required for SMTP.")
        username = env.get("DJANGO_SMTP_USERNAME", "")
        password = env.get("DJANGO_SMTP_PASSWORD", "")
        if bool(username) != bool(password) or (username and not username.strip()):
            raise ImproperlyConfigured("SMTP username and password must be supplied together.")
        backend = {"BACKEND": "django.core.mail.backends.smtp.EmailBackend", "OPTIONS": {
            "host": host, "port": port, "username": username, "password": password,
            "use_tls": tls, "use_ssl": ssl, "timeout": timeout, "fail_silently": False,
        }}
    else:
        backend = {"BACKEND": "django.core.mail.backends.console.EmailBackend"}
    return {"default": backend}, sender
