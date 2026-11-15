import hashlib
import re
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone

from .models import Complaint


@pytest.fixture
def complaint_fields(department_factory):
    submitted_at = timezone.now()
    return {
        "complaint_id": "SCMS-2026-000001",
        "category_key": "1",  # Synthetic positive Category primary key.
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
    # Backends raise different exception types for the same rejection.
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64)


@pytest.mark.parametrize(
    ("field", "limit"),
    [("category_key", 100), ("category", 50), ("sub_category", 50),
     ("location_code", 100), ("block", 20), ("floor", 10), ("room_area", 30),
     ("title", 120), ("description", 2000), ("routing_rule_key", 100),
     ("resolution_remarks", 2000)],
)
def test_database_enforces_text_limits_on_sqlite_too(complaint_fields, field, limit):
    complaint_fields[field] = ("1" if field == "category_key" else "x") * (limit + 1)
    if field == "routing_rule_key":
        complaint_fields["unrouted"] = False
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
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
    from routing.models import Priority
    assert Complaint.Priority.choices == Priority.choices


@pytest.mark.parametrize("key", [None, "", " ", "0", "scope:1"])
def test_database_requires_a_category_primary_key(complaint_fields, key):
    complaint_fields["category_key"] = key
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64)


def test_database_rejects_an_omitted_category_key(complaint_fields):
    complaint_fields.pop("category_key")
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64)


@pytest.mark.parametrize(("escalated", "level"), [(True, 0), (False, 1)])
def test_database_rejects_inconsistent_escalation(complaint_fields, escalated, level):
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64,
                                 is_escalated=escalated, escalation_level=level)


@pytest.mark.parametrize(("escalated", "level"), [(False, 0), (True, 1), (True, 3)])
def test_database_accepts_consistent_escalation(complaint_fields, escalated, level):
    complaint = Complaint.objects.create(**complaint_fields, reference_digest="a" * 64,
                                         is_escalated=escalated, escalation_level=level)
    complaint.refresh_from_db()
    assert complaint.is_escalated == escalated
    assert complaint.escalation_level == level


@pytest.mark.parametrize(("unrouted", "key"), [(False, ""), (True, "1"), (None, "1")])
def test_database_rejects_inconsistent_routing(complaint_fields, unrouted, key):
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.create(**complaint_fields, reference_digest="a" * 64,
                                 unrouted=unrouted, routing_rule_key=key)


@pytest.mark.parametrize(("unrouted", "key"), [(False, "1"), (True, ""), (None, "")])
def test_database_accepts_consistent_routing(complaint_fields, unrouted, key):
    complaint = Complaint.objects.create(**complaint_fields, reference_digest="a" * 64,
                                         unrouted=unrouted, routing_rule_key=key)
    complaint.refresh_from_db()
    assert complaint.unrouted is unrouted
    assert complaint.routing_rule_key == key


def test_reference_hash_matches_the_issuance_encoding():
    from .references import hash_reference
    reference = "0123456789abcdef" * 2
    assert hash_reference(reference) == hashlib.sha256(reference.encode("ascii")).hexdigest()


@pytest.mark.parametrize("reference", [None, 123, b"a" * 32, "a" * 31, "a" * 33,
                                      "A" * 32, "g" * 32, " " + "a" * 32])
def test_reference_hash_rejects_malformed_lookup_values(reference):
    from .references import hash_reference
    with pytest.raises(ValueError):
        hash_reference(reference)


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
