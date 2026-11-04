from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Department, User

from .models import Complaint


@pytest.fixture
def complaint_fields(db):
    submitted_at = timezone.now()
    return {
        "complaint_id": "SCMS-2026-000001",
        "category": "Maintenance",
        "location_code": "TEST-BLOCK",
        "block": "Test block",
        "room_area": "Test room",
        "title": "Faulty light",
        "description": "The light in the test room no longer turns on.",
        "priority": Complaint.Priority.LOW,
        "department": Department.objects.create(name="Test department"),
        "submitted_at": submitted_at,
        "due_at": submitted_at + timedelta(days=1),
    }


@pytest.mark.parametrize("authenticated", [True, False])
def test_complaint_stores_only_the_applicable_submitter_or_digest(complaint_fields, authenticated):
    user = User.objects.create_user(email="reporter@example.com") if authenticated else None
    digest = None if authenticated else "a" * 64
    complaint = Complaint.objects.create(
        **complaint_fields, submitted_by=user, reference_digest=digest,
    )
    complaint.refresh_from_db()
    assert complaint.submitted_by == user
    assert complaint.reference_digest == digest


@pytest.mark.parametrize(
    ("authenticated", "digest"), [(False, None), (False, "a" * 32), (True, "a" * 64)],
    ids=["missing-anonymous-digest", "raw-reference", "authenticated-with-digest"],
)
def test_database_rejects_invalid_identity_and_reference_combinations(
    complaint_fields, authenticated, digest,
):
    user = User.objects.create_user(email="reporter@example.com") if authenticated else None
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(
            **complaint_fields, submitted_by=user, reference_digest=digest,
        )
