import hashlib
import re
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Complaint


@pytest.fixture
def complaint_fields(department_factory):
    submitted_at = timezone.now()
    return {
        "complaint_id": "SCMS-2026-000001",
        "category_key": "synthetic-category-1",
        "category": "Maintenance",
        "location_code": "TEST-BLOCK",
        "block": "Test block",
        "room_area": "Test room",
        "title": "Faulty light",
        "description": "The light in the test room no longer turns on.",
        "priority": Complaint.Priority.LOW,
        "department": department_factory(),
        "submitted_at": submitted_at,
        "due_at": submitted_at + timedelta(days=1),
    }


@pytest.mark.parametrize("authenticated", [True, False])
def test_complaint_stores_only_the_applicable_submitter_or_digest(complaint_fields, authenticated, user_factory):
    user = user_factory() if authenticated else None
    digest = None if authenticated else "a" * 64
    complaint = Complaint.objects.create(
        **complaint_fields, submitted_by=user, reference_digest=digest,
    )
    complaint.refresh_from_db()
    assert complaint.submitted_by == user
    assert complaint.reference_digest == digest


@pytest.mark.parametrize(
    ("authenticated", "digest"), [(False, None), (False, "a" * 32), (False, "A" * 64), (False, "g" * 64), (True, "a" * 64)],
    ids=["missing-anonymous-digest", "raw-reference", "uppercase", "non-hex", "authenticated-with-digest"],
)
def test_database_rejects_invalid_identity_and_reference_combinations(
    complaint_fields, authenticated, digest, user_factory,
):
    user = user_factory() if authenticated else None
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(
            **complaint_fields, submitted_by=user, reference_digest=digest,
        )


@pytest.mark.parametrize("field", ["reference_digest", "complaint_id"])
def test_database_rejects_duplicate_reference_digests_and_identifiers(complaint_fields, field):
    Complaint.objects.create(**complaint_fields, reference_digest="a" * 64)
    duplicate = dict(complaint_fields, complaint_id="SCMS-2026-000002", reference_digest="b" * 64)
    duplicate[field] = "a" * 64 if field == "reference_digest" else complaint_fields["complaint_id"]
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**duplicate)


@pytest.mark.parametrize("identifier", ["bad", "SCMS-2026-000001x", "SCMS-2026-ABCDEF"])
def test_database_rejects_malformed_identifiers(complaint_fields, identifier):
    complaint_fields["complaint_id"] = identifier
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64)


@pytest.mark.parametrize(
    ("field", "limit"),
    [("category_key", 100), ("category", 50), ("sub_category", 50),
     ("location_code", 100), ("block", 20), ("floor", 10), ("room_area", 30),
     ("title", 120), ("description", 2000), ("routing_rule_key", 100),
     ("resolution_remarks", 2000)],
)
def test_database_enforces_text_limits_on_sqlite_too(complaint_fields, field, limit):
    complaint_fields[field] = "x" * (limit + 1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64)


@pytest.mark.parametrize("rating", [0, 6])
def test_database_enforces_rating_range(complaint_fields, rating):
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64, rating=rating)


def test_anonymous_reference_uses_secrets_with_128_bits_and_stores_only_a_digest(complaint_fields):
    complaint = Complaint(**complaint_fields)
    with patch("complaints.models.secrets.token_hex", return_value="b" * 32) as token_hex:
        reference = complaint.issue_anonymous_reference()
    token_hex.assert_called_once_with(16)
    assert re.fullmatch(r"[0-9a-f]{32}", reference)
    assert complaint.reference_digest == hashlib.sha256(reference.encode("ascii")).hexdigest()
    assert reference not in vars(complaint).values()
    complaint.save()
    complaint.refresh_from_db()
    assert complaint.submitted_by_id is None
    with pytest.raises(ValidationError):
        complaint.issue_anonymous_reference()


def test_unsaved_anonymous_reference_cannot_be_reissued(complaint_fields):
    complaint = Complaint(**complaint_fields)
    first = complaint.issue_anonymous_reference()
    with pytest.raises(ValidationError):
        complaint.issue_anonymous_reference()
    assert complaint.reference_digest == hashlib.sha256(first.encode("ascii")).hexdigest()


def test_authenticated_complaint_cannot_issue_an_anonymous_reference(complaint_fields, user_factory):
    complaint = Complaint(**complaint_fields, submitted_by=user_factory())
    with pytest.raises(ValidationError):
        complaint.issue_anonymous_reference()


def test_complaint_and_form_priorities_match():
    from .forms import ComplaintForm
    assert Complaint.Priority.choices == list(ComplaintForm.Priority.CHOICES)


def test_complaint_and_routing_priorities_match():
    from django.apps import apps
    try:
        routing_priority = apps.get_model("routing", "Category")._meta.get_field("minimum_priority")
    except LookupError:
        pytest.skip("B17 PR #53 must merge before the routing priority contract can run.")
    assert Complaint.Priority.choices == list(routing_priority.choices)


def test_permissions_on_real_authenticated_and_anonymous_records(complaint_fields, user_factory):
    from django.contrib.auth.models import AnonymousUser
    from accounts.permissions import can_view_complaint, can_view_evidence

    owner = user_factory()
    other = user_factory()
    complaint = Complaint.objects.create(**complaint_fields, submitted_by=owner)
    assert can_view_complaint(owner, complaint)
    assert can_view_evidence(owner, complaint)
    assert not can_view_complaint(other, complaint)
    assert not can_view_evidence(other, complaint)
    assert not can_view_complaint(AnonymousUser(), complaint)

    anonymous_fields = dict(complaint_fields, complaint_id="SCMS-2026-000002")
    anonymous = Complaint(**anonymous_fields)
    anonymous.issue_anonymous_reference()
    anonymous.save()
    assert not can_view_complaint(owner, anonymous)
    assert not can_view_evidence(owner, anonymous)
    assert not can_view_complaint(AnonymousUser(), anonymous)
