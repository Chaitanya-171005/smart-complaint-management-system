
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import connection
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from complaints.evidence import staged_evidence, validate_evidence
from complaints.models import Attachment
from workflow.lifecycle import _account_transition, _apply_locked_transition, transition_complaint


IN_PROGRESS = "IN_PROGRESS"
RESOLVED = "RESOLVED"


def validate_resolution(current_state, remarks):
    """
    Validate the basic requirements for resolving a complaint.

    Retains PR #49's state/minimum contract; adds the SRS 2000-character cap.
    This helper alone does not authorize an actor or persist a resolution.
    """
    if current_state != IN_PROGRESS:
        raise ValidationError(
            "A complaint can only be resolved from IN_PROGRESS."
        )

    if not isinstance(remarks, str) or len(remarks.strip()) < 20:
        raise ValidationError(
            "Resolution remarks must contain at least 20 characters."
        )

    if len(remarks.strip()) > 2000 or "\x00" in remarks:
        raise ValidationError("Resolution remarks must contain 20 to 2000 valid characters.")

    return RESOLVED


def progress_complaint(*, actor, complaint_id, expected_revision, remarks=""):
    """Commence ASSIGNED/REOPENED work using the SRS/F1 progress authority."""
    return transition_complaint(actor=actor, complaint_id=complaint_id,
                                target_state=IN_PROGRESS, expected_revision=expected_revision,
                                reason=remarks)


def resolve_complaint(*, actor, complaint_id, expected_revision, remarks, files=()):
    """Resolve once with a complete optional evidence batch; never close work.

    Own the outermost transaction so storage sees commit failures. Authorize
    before parsing files, then recheck the same revision/actor after staging.
    No client-provided status, uploader, storage key or callback is accepted.
    """
    if connection.in_atomic_block:
        raise TransactionManagementError("Resolution must own its outermost transaction.")
    with _account_transition(actor=actor, complaint_id=complaint_id, target_state=RESOLVED,
                              expected_revision=expected_revision) as context:
        complaint, _, _ = context
        validate_resolution(complaint.status, remarks)
        anonymous = complaint.submitted_by_id is None
    clean_remarks = remarks.strip()
    validated = validate_evidence(files)
    # Validate/stage immutable snapshots, never mutable caller-owned streams.
    with staged_evidence([ContentFile(item.data, name=item.original_name) for item in validated],
                         anonymous=anonymous) as stored:
        with _account_transition(actor=actor, complaint_id=complaint_id, target_state=RESOLVED,
                                  expected_revision=expected_revision) as context:
            complaint, current, _ = context
            validate_resolution(complaint.status, clean_remarks)
            complaint.resolution_remarks = clean_remarks
            complaint.resolved_at = timezone.now()
            complaint.save(update_fields=["resolution_remarks", "resolved_at"])
            for item in stored:
                Attachment.objects.create(
                    complaint=complaint, storage_name=item.storage_name,
                    original_name=item.original_name, content_type=item.content_type,
                    size=item.size, sha256=item.sha256, stage=Attachment.Stage.RESOLUTION,
                    uploaded_by=current,
                )
            result = _apply_locked_transition(complaint, current, RESOLVED, clean_remarks)
    return result
