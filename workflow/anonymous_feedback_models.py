"""Protected anonymous feedback; no account, credential or source metadata."""
from django.core.exceptions import ValidationError
from django.db import models


class FeedbackQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Recorded feedback cannot be edited.")

    def delete(self):
        raise ValidationError("Recorded feedback cannot be deleted.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use the reference feedback service.")


class AnonymousResolutionFeedback(models.Model):
    complaint = models.ForeignKey("complaints.Complaint", on_delete=models.PROTECT,
                                 related_name="anonymous_resolution_feedback")
    history = models.OneToOneField("workflow.ComplaintHistory", on_delete=models.PROTECT,
                                  related_name="anonymous_feedback")
    decision = models.CharField(max_length=11, choices=[
        ("CONFIRM", "Confirmed"), ("REOPEN", "Reopened"), ("HEAD_REVIEW", "Head review"),
    ])
    reason = models.TextField(max_length=2000, blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = FeedbackQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(decision__in=["CONFIRM", "REOPEN", "HEAD_REVIEW"]),
                                   name="anonymous_feedback_valid_decision"),
            models.CheckConstraint(condition=models.Q(rating__isnull=True) | models.Q(rating__gte=1, rating__lte=5),
                                   name="anonymous_feedback_valid_rating"),
            models.CheckConstraint(condition=models.Q(decision="CONFIRM", reason="")
                                   | (~models.Q(decision="CONFIRM") & models.Q(rating__isnull=True)),
                                   name="anonymous_feedback_decision_data"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Recorded feedback cannot be edited.")
        if (self.complaint.submitted_by_id is not None
                or self.history.actor_kind != "ANONYMOUS"
                or self.history.complaint_ref != self.complaint.complaint_id):
            raise ValidationError("Anonymous feedback requires its anonymous action history.")
        if (len(self.reason) > 2000 or (self.decision == "CONFIRM" and self.reason)
                or (self.decision != "CONFIRM" and (len(self.reason.strip()) < 20 or self.rating is not None))):
            raise ValidationError("Invalid feedback data.")
        self.clean_fields(exclude=["created_at"])
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Recorded feedback cannot be deleted.")
