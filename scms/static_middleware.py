"""Collected public assets with a fail-closed private-storage boundary."""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from whitenoise.middleware import WhiteNoiseMiddleware


class PublicStaticMiddleware(WhiteNoiseMiddleware):
    def __init__(self, get_response):
        public = Path(settings.STATIC_ROOT).resolve()
        private = Path(settings.PRIVATE_EVIDENCE_ROOT).resolve()
        if public == private or public in private.parents or private in public.parents:
            raise ImproperlyConfigured(
                "Public static and private evidence roots must be separate."
            )
        super().__init__(get_response)
