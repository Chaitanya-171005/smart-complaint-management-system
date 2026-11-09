"""Complaint records and intake persistence primitives."""

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Length
from django.db.models.lookups import LessThanOrEqual

from .validators import validate_description, validate_single_line
from .references import hash_reference


class ComplaintIdSequence(models.Model):
    """Internal yearly counter, advanced only inside the caller's intake transaction.

    This row is not a complaint or an acknowledgement. Never reset/delete a live
    year's counter, and never expose it as editable configuration in the admin.
    """

    year = models.PositiveSmallIntegerField(
        primary_key=True, editable=False,
        validators=[MinValueValidator(1), MaxValueValidator(9999)],
    )
    last_value = models.PositiveIntegerField(
        default=0, editable=False, validators=[MaxValueValidator(999999)],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(year__gte=1, year__lte=9999),
                name="complaint_id_year_in_range",
            ),
            models.CheckConstraint(
                condition=Q(last_value__gte=0, last_value__lte=999999),
                name="complaint_id_sequence_in_range",
            ),
        ]


class IntakeReceipt(models.Model):
    """Internal authenticated retry receipt, committed with required intake writes.

    complaint_id retains the accepted external ID. The Complaint FK migration is
    tracked in #15 with the complete intake adapter and legacy receipt backfill.
    A request key authorizes no complaint access.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name="+")
    key_digest = models.CharField(max_length=64, editable=False)
    payload_digest = models.CharField(max_length=64, editable=False)
    complaint_id = models.CharField(max_length=16, unique=True, editable=False)
    submitted_at = models.DateTimeField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "key_digest"],
                                    name="intake_receipt_user_key_unique"),
            models.CheckConstraint(condition=~Q(complaint_id=""),
                                   name="intake_receipt_has_identifier"),
        ]


class Complaint(models.Model):
    """Persist stable reference keys, label snapshots and lifecycle data.

    category_key is str(category.pk), required alongside the category label
    snapshot. routing_rule_key is str(rule.pk), never the mutable rule scope_key.
    Intake must validate the current references before saving these snapshots.
    """

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        RESOLVED = "RESOLVED", "Resolved"
        REOPENED = "REOPENED", "Reopened"
        CLOSED = "CLOSED", "Closed"
        REJECTED = "REJECTED", "Rejected"

    complaint_id = models.CharField(
        max_length=16, unique=True, editable=False,
        validators=[RegexValidator(r"\ASCMS-[0-9]{4}-[0-9]{6}\Z")],
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="submitted_complaints",
    )
    # Store the SHA-256 digest of the anonymous reference so it cannot be displayed again.
    reference_digest = models.CharField(
        max_length=64, unique=True, null=True, blank=True, editable=False,
        validators=[RegexValidator(r"\A[0-9a-f]{64}\Z")],
    )
    category_key = models.CharField(
        max_length=100, validators=[RegexValidator(r"\A[1-9][0-9]*\Z")],
    )
    category = models.CharField(max_length=50)
    sub_category = models.CharField(max_length=50, blank=True, validators=[validate_single_line])
    location_code = models.CharField(max_length=100)
    block = models.CharField(max_length=20)
    floor = models.CharField(max_length=10, blank=True)
    room_area = models.CharField(max_length=30)
    title = models.CharField(max_length=120, validators=[validate_single_line])
    description = models.TextField(max_length=2000, validators=[validate_description])
    priority = models.CharField(max_length=8, choices=Priority.choices)
    department = models.ForeignKey("accounts.Department", on_delete=models.PROTECT)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="assigned_complaints",
    )
    status = models.CharField(max_length=11, choices=Status.choices, default=Status.SUBMITTED)
    submitted_at = models.DateTimeField(editable=False)
    due_at = models.DateTimeField()
    # None means a routing decision has not yet been recorded.
    unrouted = models.BooleanField(null=True, default=None)
    routing_rule_key = models.CharField(max_length=100, blank=True)
    is_escalated = models.BooleanField(default=False)
    escalation_level = models.PositiveSmallIntegerField(default=0)
    reopen_count = models.PositiveSmallIntegerField(default=0)
    resolution_remarks = models.TextField(max_length=2000, blank=True)
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(category_key__regex=r"\A[1-9][0-9]*\Z"),
                name="complaint_category_key_format",
            ),
            models.CheckConstraint(
                condition=Q(complaint_id__regex=r"\ASCMS-[0-9]{4}-[0-9]{6}\Z"),
                name="complaint_identifier_format",
            ),
            models.CheckConstraint(
                condition=(
                    Q(submitted_by__isnull=False, reference_digest__isnull=True)
                    | Q(submitted_by__isnull=True, reference_digest__isnull=False,
                        reference_digest__regex=r"\A[0-9a-f]{64}\Z")
                ),
                name="complaint_submitter_or_reference_digest",
            ),
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5),
                name="complaint_rating_in_range",
            ),
            models.CheckConstraint(
                condition=(Q(is_escalated=False, escalation_level=0)
                           | Q(is_escalated=True, escalation_level__gt=0)),
                name="complaint_escalation_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    (Q(unrouted__isnull=False, unrouted=False) & ~Q(routing_rule_key=""))
                    | Q(unrouted=True, routing_rule_key="")
                    | Q(unrouted__isnull=True, routing_rule_key="")
                ),
                name="complaint_routing_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    LessThanOrEqual(Length("category_key"), 100)
                    & LessThanOrEqual(Length("category"), 50)
                    & LessThanOrEqual(Length("sub_category"), 50)
                    & LessThanOrEqual(Length("location_code"), 100)
                    & LessThanOrEqual(Length("block"), 20)
                    & LessThanOrEqual(Length("floor"), 10)
                    & LessThanOrEqual(Length("room_area"), 30)
                    & LessThanOrEqual(Length("title"), 120)
                    & LessThanOrEqual(Length("description"), 2000)
                    & LessThanOrEqual(Length("routing_rule_key"), 100)
                    & LessThanOrEqual(Length("resolution_remarks"), 2000)
                ),
                name="complaint_text_within_limits",
            ),
        ]
        indexes = [
            models.Index(fields=["department", "status", "due_at"], name="complaint_department_queue"),
            models.Index(fields=["submitted_by", "submitted_at"], name="complaint_submitter_list"),
        ]

    def issue_anonymous_reference(self):
        """Generate one 128-bit reference for a new anonymous complaint.

        Return the raw reference to the trusted intake caller and retain only its
        digest. The caller displays it only after the full intake transaction
        commits, with a loss warning and private, no-store response headers.
        """
        if not self._state.adding or self.submitted_by_id is not None or self.reference_digest is not None:
            raise ValidationError("A reference can be issued once for a new anonymous complaint.")
        reference = secrets.token_hex(16)
        self.reference_digest = hash_reference(reference)
        return reference

    def __str__(self):
        return self.complaint_id
