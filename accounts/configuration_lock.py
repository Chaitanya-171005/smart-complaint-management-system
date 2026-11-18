"""Serialize PostgreSQL configuration writers before acquiring any row locks."""

from django.db import connection
from django.db.transaction import TransactionManagementError


# Stable, application-owned two-int advisory-lock namespace: ASCII SCMS, config 1.
CONFIGURATION_LOCK = (0x53434D53, 1)


def lock_configuration():
    """Call first inside the configuration transaction, including nested callers.

    PostgreSQL retains this lock through row writes, deferred FK checks and audit
    commit, and releases it automatically on rollback/commit. All configuration
    entry points share it; SQLite already serializes writers with IMMEDIATE.
    Callers must not acquire unrelated row locks before entering these services.
    Direct ORM writes are outside the configuration-service contract.
    """
    if not connection.in_atomic_block:
        raise TransactionManagementError("Configuration locking requires an atomic block.")
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", CONFIGURATION_LOCK)
