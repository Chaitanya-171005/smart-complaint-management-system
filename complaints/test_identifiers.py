"""B08 allocator checks with real transactions and concurrent DB connections."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as dt_timezone
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from complaints.identifiers import ComplaintIdExhausted, allocate_complaint_id
from complaints.models import ComplaintIdSequence

pytestmark = pytest.mark.django_db(transaction=True)
SUBMITTED_AT = datetime(2026, 10, 29, 10, 0, tzinfo=dt_timezone.utc)


def allocate(at=SUBMITTED_AT):
    with transaction.atomic():
        return allocate_complaint_id(submitted_at=at)


def test_first_identifier_has_exact_format_and_padding():
    identifier = allocate()
    assert identifier == "SCMS-2026-000001"
    assert re.fullmatch(r"SCMS-\d{4}-\d{6}", identifier)
    assert ComplaintIdSequence.objects.get(year=2026).last_value == 1


def test_identifiers_increment_across_committed_transactions():
    assert [allocate() for _ in range(3)] == [
        "SCMS-2026-000001", "SCMS-2026-000002", "SCMS-2026-000003"
    ]
    assert ComplaintIdSequence.objects.count() == 1


def test_multiple_reservations_in_one_transaction_are_distinct():
    with transaction.atomic():
        first = allocate_complaint_id(submitted_at=SUBMITTED_AT)
        second = allocate_complaint_id(submitted_at=SUBMITTED_AT)
    assert first != second
    assert second == "SCMS-2026-000002"


def test_year_rollover_keeps_separate_counters():
    assert allocate() == "SCMS-2026-000001"
    next_year = SUBMITTED_AT.replace(year=2027)
    assert allocate(next_year) == "SCMS-2027-000001"
    assert allocate() == "SCMS-2026-000002"
    assert ComplaintIdSequence.objects.count() == 2


def test_project_timezone_defines_year_not_active_user_timezone(settings):
    settings.TIME_ZONE = "Asia/Kolkata"
    instant = datetime(2026, 12, 31, 20, 0, tzinfo=dt_timezone.utc)
    with timezone.override("America/Los_Angeles"):
        assert allocate(instant) == "SCMS-2027-000001"


@pytest.mark.parametrize("value", [None, "2026-10-29", 2026, datetime(2026, 10, 29)])
def test_invalid_timestamp_cannot_advance_counter(value):
    with transaction.atomic(), pytest.raises(ValueError, match="aware datetime"):
        allocate_complaint_id(submitted_at=value)
    assert not ComplaintIdSequence.objects.exists()


def test_autocommit_allocation_is_refused_without_writing():
    assert not connection.in_atomic_block
    with pytest.raises(TransactionManagementError, match="intake transaction"):
        allocate_complaint_id(submitted_at=SUBMITTED_AT)
    assert not ComplaintIdSequence.objects.exists()


@pytest.mark.parametrize("starting_value", [None, 7])
def test_failed_outer_transaction_rolls_back_reservation(starting_value):
    if starting_value is not None:
        ComplaintIdSequence.objects.create(year=2026, last_value=starting_value)
    with pytest.raises(RuntimeError, match="required operation failed"):
        with transaction.atomic():
            allocate_complaint_id(submitted_at=SUBMITTED_AT)
            raise RuntimeError("Synthetic required operation failed")
    if starting_value is None:
        assert not ComplaintIdSequence.objects.exists()
    else:
        assert ComplaintIdSequence.objects.get(year=2026).last_value == starting_value
    assert allocate() == f"SCMS-2026-{(starting_value or 0) + 1:06d}"


def test_savepoint_rollback_does_not_undo_earlier_reservation():
    with transaction.atomic():
        assert allocate_complaint_id(submitted_at=SUBMITTED_AT) == "SCMS-2026-000001"
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                assert allocate_complaint_id(submitted_at=SUBMITTED_AT) == "SCMS-2026-000002"
                raise RuntimeError("Synthetic nested failure")
        assert allocate_complaint_id(submitted_at=SUBMITTED_AT) == "SCMS-2026-000002"


def test_counter_persists_across_connection_replacement():
    assert allocate() == "SCMS-2026-000001"
    connection.close()
    assert allocate() == "SCMS-2026-000002"


def test_last_six_digit_identifier_is_allowed_then_year_is_exhausted():
    ComplaintIdSequence.objects.create(year=2026, last_value=999998)
    assert allocate() == "SCMS-2026-999999"
    with pytest.raises(ComplaintIdExhausted):
        allocate()
    assert ComplaintIdSequence.objects.get(year=2026).last_value == 999999
    assert allocate(SUBMITTED_AT.replace(year=2027)) == "SCMS-2027-000001"


@pytest.mark.parametrize("year,last_value", [(0, 0), (10000, 0), (2026, -1), (2026, 1000000)])
def test_database_rejects_out_of_range_counters(year, last_value):
    with pytest.raises(IntegrityError), transaction.atomic():
        ComplaintIdSequence.objects.create(year=year, last_value=last_value)


def test_database_rejects_duplicate_year_rows():
    ComplaintIdSequence.objects.create(year=2026, last_value=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        ComplaintIdSequence.objects.create(year=2026, last_value=2)
    assert ComplaintIdSequence.objects.get(year=2026).last_value == 1


def test_unexpected_insert_integrity_error_is_not_hidden():
    with patch("django.db.models.query.QuerySet.create", side_effect=IntegrityError("Synthetic storage failure")):
        with pytest.raises(IntegrityError, match="Synthetic storage failure"):
            allocate()
    assert not ComplaintIdSequence.objects.exists()


@pytest.mark.parametrize("starting_value", [None, 41])
def test_concurrent_connections_allocate_unique_numbers(starting_value):
    if starting_value is not None:
        ComplaintIdSequence.objects.create(year=2026, last_value=starting_value)
    workers = 8
    barrier = Barrier(workers)

    def submit(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return allocate()
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        identifiers = list(pool.map(submit, range(workers)))
    base = starting_value or 0
    assert set(identifiers) == {
        f"SCMS-2026-{number:06d}" for number in range(base + 1, base + workers + 1)
    }
    assert len(identifiers) == len(set(identifiers))
    assert ComplaintIdSequence.objects.get(year=2026).last_value == base + workers
