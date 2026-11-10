"""Explicit PostgreSQL settings for isolated recovery tests, never deployment."""
import os
from .settings import *  # noqa: F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['RECOVERY_POSTGRES_NAME'],
        'USER': os.environ['RECOVERY_POSTGRES_USER'],
        'PASSWORD': os.environ['RECOVERY_POSTGRES_PASSWORD'],
        'HOST': os.environ['RECOVERY_POSTGRES_HOST'],
        'PORT': os.environ['RECOVERY_POSTGRES_PORT'],
        'CONN_MAX_AGE': 0,
    },
}
