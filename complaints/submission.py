"""Authenticated B10 aggregate service, awaiting the B07 HTTP integration.

Call with raw form fields, a retained request key and the complete file batch.
Clients cannot supply derived fields, fingerprints, actors or operation callbacks.
"""

import hashlib
import unicodedata
from collections.abc import Mapping

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from accounts.models import Location, User
from accounts.permissions import can_submit_complaint, require_permission
from routing.intake import route_and_prioritize
from routing.models import Category
from workflow.history_service import record_history
from workflow.models import ComplaintHistory

from .evidence import staged_evidence, validate_evidence
from .forms import ComplaintForm
from .intake import execute_intake, submission_digest
from .models import Attachment, Complaint
from .reference_data import CategoryOption, LocationOption


def _clean_fields(data):
    """Validate normalized user values before hashing, independently of policy.

    Current reference activation is checked only for a NEW operation, inside the
    transaction. An accepted retry must survive later policy/reference changes.
    """
    allowed = set(ComplaintForm.base_fields)
    if not isinstance(data, Mapping) or set(data) - allowed:
        raise ValidationError("Supply only complaint form fields.", code="submission_fields")
    values, errors = {}, {}
    for name, field in ComplaintForm.base_fields.items():
        value = data.get(name, "")
        if not isinstance(value, str):
            errors[name] = ["Use text for this field."]
            continue
        value = unicodedata.normalize("NFC", value)
        if name == "category":
            field = forms.RegexField(regex=r"\A[1-9][0-9]*\Z", max_length=100)
        elif name == "location":
            value = Location.normalize_code(value)
            field = forms.RegexField(regex=r"\A[A-Z0-9._-]+\Z", max_length=100)
        try:
            values[name] = field.clean(value)
            if name == "category" and int(values[name]) > 9223372036854775807:
                raise ValidationError("Select a valid category.")
        except ValidationError as error:
            errors[name] = error.messages
    if errors:
        raise ValidationError(errors)
    return values


def submit_authenticated_complaint(*, user, key, data, files=()):
    """Persist one real aggregate or return its original accepted retry result.

    This owns the outermost transaction via execute_intake. No HTTP endpoint or
    durable notification/crash-recovery claim is made by this service.
    """
    current_user = (User.objects.filter(pk=user.pk).first()
                    if user is not None and user.is_authenticated and user.pk else None)
    require_permission(can_submit_complaint, current_user)
    fields = _clean_fields(data)
    validated = validate_evidence(files)
    fingerprint = submission_digest(
        fields={**fields, "evidence": [
            {"original_name": item.original_name, "content_type": item.content_type,
             "size": len(item.data), "stage": Attachment.Stage.INTAKE}
            for item in validated
        ]},
        evidence_sha256=[hashlib.sha256(item.data).hexdigest() for item in validated],
    )

    def persist(context):
        category = Category.objects.select_for_update().filter(
            pk=fields["category"], active=True,
        ).first()
        location = Location.objects.select_for_update().filter(
            code=fields["location"], active=True,
        ).first()
        if category is None or location is None:
            raise ValidationError("Select an active category and location.", code="inactive_reference")
        form = ComplaintForm(
            fields,
            categories=[CategoryOption(str(category.pk), category.name)],
            locations=[LocationOption(location.code, location.block, location.room_area, location.floor)],
        )
        # _clean_fields validates user values, but active master-data labels can
        # still contain invalid text from a direct DB write. Refuse that graph.
        if not form.is_valid():
            raise ValidationError(form.errors.as_data())
        outcome = route_and_prioritize(
            complaint_id=context.complaint_id, category=category, location_code=location.code,
            indicated_priority=fields["priority"], submitted_at=context.submitted_at,
        )
        complaint = Complaint(
            complaint_id=context.complaint_id, submitted_by=context.user,
            category_key=str(category.pk), category=category.name,
            sub_category=fields["sub_category"], location_code=location.code,
            block=location.block, floor=location.floor, room_area=location.room_area,
            title=fields["title"], description=fields["description"],
            submitted_at=context.submitted_at, **outcome.as_complaint_fields(),
        )
        complaint.full_clean()
        complaint.save(force_insert=True)
        for item in context.evidence:
            Attachment.objects.create(
                complaint=complaint, storage_name=item.storage_name,
                original_name=item.original_name, content_type=item.content_type,
                size=item.size, sha256=item.sha256, stage=Attachment.Stage.INTAKE,
                uploaded_by=context.user,
            )
        record_history(complaint.complaint_id, ComplaintHistory.EventType.SUBMITTED,
                       ComplaintHistory.ActorKind.COMPLAINANT, new_state=Complaint.Status.SUBMITTED)
        record_history(complaint.complaint_id, ComplaintHistory.EventType.ALLOCATED,
                       ComplaintHistory.ActorKind.SYSTEM, previous_state=Complaint.Status.SUBMITTED,
                       new_state=Complaint.Status.ASSIGNED)
        return complaint

    # Stage immutable validated snapshots, not caller-owned streams that could
    # change between hashing and storage. B09 revalidates those same byte values.
    return execute_intake(
        user=current_user, key=key, payload_digest=fingerprint, operation=persist,
        staging=lambda: staged_evidence([
            ContentFile(item.data, name=item.original_name) for item in validated
        ]),
        require_complaint=True,
    )
