"""Complaint records and intake persistence primitives."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from .validators import validate_description, validate_single_line


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

    Not a Complaint: no production intake path exists yet. Never expose this
    table through admin or treat possession of a key as authorization.
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
    """Persist a complaint with its submitted category and location labels."""

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

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(submitted_by__isnull=False, reference_digest__isnull=True)
                    | Q(submitted_by__isnull=True, reference_digest__isnull=False,
                        reference_digest__regex=r"\A[0-9a-f]{64}\Z")
                ),
                name="complaint_submitter_or_reference_digest",
            ),
        ]

    def __str__(self):
        return self.complaint_id
