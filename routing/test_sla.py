from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from complaints.identifiers import allocate_complaint_id
from complaints.models import Complaint
from routing.models import Category, Priority, SLAConfiguration
from routing.services import set_sla_configuration, update_category
from routing.sla import (
    PRIORITY_ORDER, PrioritySLA, SLAConfigurationError, compute_due_at,
    derive_priority_and_due, effective_priority, resolve_sla,
)


@pytest.mark.parametrize("indicated", PRIORITY_ORDER)
@pytest.mark.parametrize("minimum", PRIORITY_ORDER)
def test_effective_priority_respects_category_minimum(indicated, minimum):
    category = Category(name="Test", minimum_priority=minimum)
    expected = PRIORITY_ORDER[max(PRIORITY_ORDER.index(indicated), PRIORITY_ORDER.index(minimum))]
    assert effective_priority(indicated, category) == expected


@pytest.mark.parametrize("indicated", PRIORITY_ORDER)
def test_effective_priority_without_category(indicated):
    assert effective_priority(indicated, None) == indicated


@pytest.mark.parametrize("indicated", ["low", "URGENT", None, ""])
def test_effective_priority_rejects_invalid_indicated(indicated):
    with pytest.raises(ValueError):
        effective_priority(indicated, None)


@pytest.mark.django_db
def test_resolve_sla_override_and_fallback():
    category = Category.objects.create(name="SLA test")
    default = SLAConfiguration.objects.get(category=None, priority=Priority.HIGH, active=True)
    assert resolve_sla(category, Priority.HIGH).configuration == default
    assert resolve_sla(None, Priority.HIGH).source == "DEFAULT"
    override = SLAConfiguration.objects.create(category=category, priority=Priority.HIGH, duration_minutes=30)
    result = resolve_sla(category, Priority.HIGH)
    assert (result.configuration, result.duration_minutes, result.source) == (override, 30, "CATEGORY")
    SLAConfiguration.objects.filter(pk=override.pk).update(active=False)
    result = resolve_sla(category, Priority.HIGH)
    assert (result.configuration, result.source) == (default, "DEFAULT")
    SLAConfiguration.objects.filter(pk=default.pk).update(active=False)
    with pytest.raises(SLAConfigurationError):
        resolve_sla(category, Priority.HIGH)
    with pytest.raises(SLAConfigurationError):
        resolve_sla(None, Priority.HIGH)


@pytest.mark.parametrize("submitted", [
    datetime(2026, 3, 8, 1, 30, tzinfo=timezone.utc),
    datetime(2026, 3, 8, 1, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
    datetime(2026, 3, 8, 1, 30, tzinfo=ZoneInfo("America/New_York")),
])
def test_compute_due_at_uses_elapsed_utc_time(submitted):
    due = compute_due_at(submitted, 120)
    assert due.tzinfo is timezone.utc
    assert due == submitted.astimezone(timezone.utc) + timedelta(hours=2)
    if submitted.tzinfo == ZoneInfo("America/New_York"):
        assert due.astimezone(submitted.tzinfo).hour == 4
        assert due.astimezone(submitted.tzinfo).minute == 30


@pytest.mark.parametrize("submitted", [datetime(2026, 1, 1), None])
def test_compute_due_at_rejects_invalid_timestamp(submitted):
    with pytest.raises(ValueError):
        compute_due_at(submitted, 1)


@pytest.mark.parametrize("duration", [0, -1, 1.5, True, False])
def test_compute_due_at_rejects_invalid_duration(duration):
    with pytest.raises(ValueError):
        compute_due_at(datetime.now(timezone.utc), duration)


@pytest.mark.django_db
@pytest.mark.parametrize(("priority", "minutes"), [
    (Priority.LOW, 10080), (Priority.MEDIUM, 4320),
    (Priority.HIGH, 1440), (Priority.CRITICAL, 240),
])
def test_derive_priority_and_due_seeded_defaults(priority, minutes, django_assert_max_num_queries):
    submitted = datetime(2026, 1, 1, tzinfo=timezone.utc)
    category = Category.objects.create(name="Derivation test")
    with django_assert_max_num_queries(2):
        result = derive_priority_and_due(category, priority, submitted)
    assert result == PrioritySLA(priority, submitted + timedelta(minutes=minutes), minutes, "DEFAULT")


@pytest.mark.django_db
def test_derive_priority_and_due_category_override(django_assert_max_num_queries):
    category = Category.objects.create(name="Override test", minimum_priority=Priority.HIGH)
    SLAConfiguration.objects.create(category=category, priority=Priority.HIGH, duration_minutes=45)
    submitted = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with django_assert_max_num_queries(2):
        result = derive_priority_and_due(category, Priority.LOW, submitted)
    assert result == PrioritySLA(Priority.HIGH, submitted + timedelta(minutes=45), 45, "CATEGORY")


@pytest.mark.django_db
def test_stored_priority_and_due_are_not_rewritten(scms_admin_user, complainant_user, department):
    category = Category.objects.create(name="Persistence test", minimum_priority=Priority.HIGH)
    submitted = datetime(2026, 1, 1, tzinfo=timezone.utc)
    set_sla_configuration(scms_admin_user, category=category, priority=Priority.HIGH, duration_minutes=60)
    result = derive_priority_and_due(category, Priority.LOW, submitted)
    with transaction.atomic():
        complaint = Complaint.objects.create(
            complaint_id=allocate_complaint_id(submitted_at=submitted), submitted_by=complainant_user,
            category_key=str(category.pk), category=category.name, location_code="TEST",
            block="Test", room_area="Room", title="Fault", description="A fault occurred.",
            priority=result.priority, department=department, submitted_at=submitted, due_at=result.due_at,
        )
    complaint.refresh_from_db()
    assert (complaint.priority, complaint.due_at) == (Priority.HIGH, submitted + timedelta(minutes=60))
    set_sla_configuration(scms_admin_user, category=category, priority=Priority.CRITICAL, duration_minutes=90)
    update_category(scms_admin_user, category, minimum_priority=Priority.CRITICAL)
    complaint.refresh_from_db()
    assert (complaint.priority, complaint.due_at) == (result.priority, result.due_at)
    assert derive_priority_and_due(category, Priority.LOW, submitted) == PrioritySLA(
        Priority.CRITICAL, submitted + timedelta(minutes=90), 90, "CATEGORY"
    )
