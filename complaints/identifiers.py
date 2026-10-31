"""B08: transaction-bound SCMS-YYYY-NNNNNN allocation; no acceptance side effects."""

from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, IntegrityError, connections, transaction
from django.db.models import F
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from .models import ComplaintIdSequence

MAX_YEARLY_SEQUENCE = 999999


class ComplaintIdExhausted(RuntimeError):
    """No six-digit complaint numbers remain for the submission's year."""


def allocate_complaint_id(*, submitted_at, using=DEFAULT_DB_ALIAS):
    """Reserve a number inside an existing transaction using a trusted timestamp.

    SQLite's IMMEDIATE transaction mode is configured in scms/settings.py, so
    master-data reads may precede allocation. Keep the outer transaction short.
    The caller must create the complaint and all required operations
    on the SAME database. A rollback undoes the reservation. The returned string
    is provisional until that entire transaction commits; never acknowledge it
    early. This helper does not implement complaint immutability or retry keys.
    """
    if not isinstance(submitted_at, datetime) or timezone.is_naive(submitted_at):
        raise ValueError("submitted_at must be a server-supplied aware datetime.")
    if not connections[using].in_atomic_block:
        raise TransactionManagementError(
            "Complaint ID allocation requires the caller's intake transaction."
        )

    # The configured project timezone defines the year, not a user's active zone.
    year = timezone.localtime(submitted_at, timezone.get_default_timezone()).year
    sequence = ComplaintIdSequence.objects.using(using).filter(year=year)

    # Keep the increment atomic. SQLite reserves the writer at outer transaction
    # entry (IMMEDIATE), so this need not be the transaction's first database query.
    if not sequence.filter(last_value__lt=MAX_YEARLY_SEQUENCE).update(last_value=F("last_value") + 1):
        try:
            # A new-year insert can race on databases with row-level locking.
            # Catch outside this savepoint so the outer transaction stays usable.
            with transaction.atomic(using=using):
                ComplaintIdSequence.objects.using(using).create(year=year, last_value=1)
        except IntegrityError:
            if not sequence.filter(last_value__lt=MAX_YEARLY_SEQUENCE).update(last_value=F("last_value") + 1):
                if sequence.exists():
                    raise ComplaintIdExhausted(
                        "No complaint identifiers remain for this year."
                    ) from None
                raise  # Unexpected integrity error: do not hide or acknowledge it.

    number = sequence.values_list("last_value", flat=True).get()
    return f"SCMS-{year:04d}-{number:06d}"
