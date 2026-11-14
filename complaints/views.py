"""Authenticated HTTP intake and private downloads; anonymous intake is separate."""

import logging
import unicodedata

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe
from django.views.decorators.vary import vary_on_cookie

from accounts.permissions import can_submit_complaint, require_permission
from accounts.reference_adapters import location_options
from routing.adapters import category_options
from routing.resolver import RoutingConfigurationError
from routing.sla import SLAConfigurationError

from .evidence import evidence_download_response
from .forms import ComplaintForm
from .intake import HEX_DIGEST, IdempotencyConflict, IntakeReconciliationRequired, new_intake_key
from .models import Attachment, IntakeReceipt
from .submission import submit_authenticated_complaint

# Django signing salts are public domain-separation values; SECRET_KEY authenticates signatures.
TOKEN_SALT = "complaints.authenticated-intake"  # nosec B105
logger = logging.getLogger(__name__)


def _new_token(user):
    return signing.dumps({"user": user.pk, "key": new_intake_key()}, salt=TOKEN_SALT)


def _request_key(token, user):
    if not isinstance(token, str) or len(token) > 1000:
        raise signing.BadSignature("Invalid intake token.")
    payload = signing.loads(token, salt=TOKEN_SALT)
    if (not isinstance(payload, dict) or payload.get("user") != user.pk
            or not isinstance(payload.get("key"), str)
            or not HEX_DIGEST.fullmatch(payload["key"])):
        raise signing.BadSignature("Invalid intake token.")
    return payload["key"]


def _form(data=None):
    return ComplaintForm(data, categories=category_options(), locations=location_options())


def _submission_response(request, form, token, *, status=200):
    return render(request, "complaints/submit.html", {
        "form": form, "request_token": token,
        "emergency_notice": settings.COMPLAINT_EMERGENCY_NOTICE,
        "evidence_errors": getattr(form, "evidence_errors", ()),
    }, status=status)


@transaction.non_atomic_requests
@never_cache
@vary_on_cookie
@sensitive_post_parameters()
@login_required
@require_http_methods(["GET", "POST"])
def submit_complaint(request):
    require_permission(can_submit_complaint, request.user)
    notice = settings.COMPLAINT_EMERGENCY_NOTICE
    if not settings.COMPLAINT_INTAKE_ENABLED or not isinstance(notice, str) or not notice.strip():
        return render(request, "complaints/unavailable.html", status=503)
    if request.method == "GET":
        form = _form()
        return _submission_response(request, form, _new_token(request.user),
                                    status=503 if form.configuration_unavailable else 200)

    # Only declared fields enter the service; CSRF/token fields and forged
    # derived values (status, department, actor, etc.) never become model values.
    data = {name: unicodedata.normalize("NFC", request.POST.get(name, ""))
            for name in ComplaintForm.base_fields}
    token = request.POST.get("request_token", "")
    try:
        key = _request_key(token, request.user)
    except signing.BadSignature:
        form = _form(data)
        form.is_valid()
        form.add_error(None, "Reload the submission page before trying again.")
        return _submission_response(request, form, "", status=400)

    # Accepted retries reach the service before mutable choices are consulted.
    try:
        result = submit_authenticated_complaint(
            user=request.user, key=key, data=data, files=request.FILES.getlist("evidence"),
        )
    except (IdempotencyConflict, IntakeReconciliationRequired) as error:
        message = ("This request was already accepted with different data."
                   if isinstance(error, IdempotencyConflict)
                   else "This earlier submission needs administrator reconciliation. Keep the original request.")
        form, status = _form(data), 409
        form.is_valid()
        form.add_error(None, message)
    except ValidationError as error:
        form, status = _form(data), 400
        form.is_valid()
        evidence_codes = {"unreadable", "too_many", "filename", "type", "size", "content", "mismatch"}
        form.evidence_errors = []
        if hasattr(error, "error_dict"):
            for name, errors in error.error_dict.items():
                if name == "evidence":
                    form.evidence_errors.extend(message for item in errors for message in item.messages)
                else:
                    form.add_error(name if name in form.fields else None, errors)
        else:
            for item in error.error_list:
                if item.code in evidence_codes:
                    form.evidence_errors.extend(item.messages)
                else:
                    form.add_error(None, item)
    except (RoutingConfigurationError, SLAConfigurationError, DatabaseError, OSError):
        logger.warning("Complaint intake could not complete a required operation.")
        form, status = _form(data), 503
        form.is_valid()
        form.add_error(None, "Your submission could not be completed. Keep this form and retry with the same details and files.")
    else:
        response = redirect("complaints:acknowledgement", complaint_id=result.complaint_id)
        response.status_code = 303
        return response
    return _submission_response(request, form, token, status=status)


@never_cache
@vary_on_cookie
@login_required
@require_safe
def acknowledgement(request, complaint_id):
    require_permission(can_submit_complaint, request.user)
    receipt = get_object_or_404(
        IntakeReceipt.objects.select_related("accepted_complaint"),
        complaint_id=complaint_id, user=request.user,
        accepted_complaint__submitted_by=request.user,
    )
    complaint = receipt.accepted_complaint
    if complaint is None or complaint.submitted_at != receipt.submitted_at:
        raise Http404
    return render(request, "complaints/acknowledgement.html", {
        "complaint": complaint, "submitted_at": receipt.submitted_at,
        "attachments": complaint.attachments.filter(stage=Attachment.Stage.INTAKE).order_by("pk"),
    })


@never_cache
@vary_on_cookie
@require_safe
def download_evidence(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related("complaint"), pk=pk)
    return evidence_download_response(user=request.user, attachment=attachment)
