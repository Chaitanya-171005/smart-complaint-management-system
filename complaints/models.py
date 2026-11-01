"""F2 persistence primitives; the Complaint aggregate is still pending."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


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
