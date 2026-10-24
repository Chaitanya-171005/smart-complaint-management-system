
from django.core.exceptions import ValidationError
from django.db import models


class ComplaintHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Complaint history entries cannot be edited.")

    def delete(self):
        raise ValidationError("Complaint history entries cannot be deleted.")

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        if update_conflicts:
            raise ValidationError(
                "Complaint history entries cannot be overwritten."
            )

        raise ValidationError(
            "Bulk creation of complaint history entries is not allowed. "
            "Use record_history() instead."
        )


class ComplaintHistory(models.Model):
    class ActorKind(models.TextChoices):
        COMPLAINANT = "COMPLAINANT", "Complainant"
        STAFF = "STAFF", "Staff"
        ADMIN = "ADMIN", "Admin"
        HEAD = "HEAD", "Department Head"
        SYSTEM = "SYSTEM", "System"
        ANONYMOUS = "ANONYMOUS", "Anonymous"

    class EventType(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        ALLOCATED = "ALLOCATED", "Allocated"
        REASSIGNED = "REASSIGNED", "Reassigned"
        ESCALATED = "ESCALATED", "Escalated"
        RESOLVED = "RESOLVED", "Resolved"
        STATUS_CHANGED = "STATUS_CHANGED", "Status changed"

    complaint_ref = models.CharField(max_length=100, db_index=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    actor_kind = models.CharField(max_length=20, choices=ActorKind.choices)
    previous_state = models.CharField(max_length=50, blank=True)
    new_state = models.CharField(max_length=50, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    remarks = models.TextField(blank=True)

    objects = ComplaintHistoryQuerySet.as_manager()

    class Meta:
        ordering = ["occurred_at", "pk"]
        verbose_name = "Complaint history entry"
        verbose_name_plural = "Complaint history entries"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Complaint history entries cannot be edited.")

        if self.event_type not in self.EventType.values:
            raise ValidationError("Invalid complaint history event type.")

        if self.actor_kind not in self.ActorKind.values:
            raise ValidationError("Invalid complaint history actor kind.")

        if self.actor_kind == self.ActorKind.ANONYMOUS:
            self.remarks = ""

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Complaint history entries cannot be deleted.")

    def __str__(self):
        return f"{self.complaint_ref}: {self.event_type}"
