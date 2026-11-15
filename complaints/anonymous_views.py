"""Anonymous form and one-response reference issuance; never a recovery route."""

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from .anonymous import AnonymousIntakeUnavailable, submit_anonymous_complaint
from .checks import anonymous_release_ready
from .forms import ComplaintForm
from .intake import HEX_DIGEST, IdempotencyConflict, new_intake_key
from .views import _form

# Django signing salts are public domain-separation values; SECRET_KEY authenticates signatures.
TOKEN_SALT = "complaints.anonymous-intake"  # nosec B105


def new_token():
    return signing.dumps({"key": new_intake_key()}, salt=TOKEN_SALT)


def request_key(token):
    if not isinstance(token, str) or len(token) > 1000:
        raise signing.BadSignature
    payload = signing.loads(token, salt=TOKEN_SALT)
    if (not isinstance(payload, dict) or set(payload) != {"key"}
            or not isinstance(payload["key"], str) or not HEX_DIGEST.fullmatch(payload["key"])):
        raise signing.BadSignature
    return payload["key"]


@transaction.non_atomic_requests
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def anonymous_submission(request):
    # Fail closed if the privacy middleware is missing or deployment checks have
    # not been attested. No request.user/account lookup is performed here.
    if (not getattr(request, "anonymous_intake", False)
            or not getattr(request, "anonymous_privacy_isolated", False)
            or not request.is_secure() or not anonymous_release_ready()):
        return render(request, "complaints/unavailable.html", status=503)
    if request.method == "GET":
        form, token, status = _form(), new_token(), 200
        if form.configuration_unavailable:
            status = 503
    else:
        # Identity-looking extras have no effect and are never passed to service.
        data = {name: request.POST.get(name, "") for name in ComplaintForm.base_fields}
        token = request.POST.get("request_token", "")
        try:
            key = request_key(token)
        except signing.BadSignature:
            form, token, status = _form(data), "", 400
            form.is_valid()
            form.add_error(None, "Reload the anonymous form before trying again.")
        else:
            try:
                result = submit_anonymous_complaint(
                    key=key, data=data, files=request.FILES.getlist("evidence"),
                )
            except IdempotencyConflict:
                form, token, status = _form(data), "", 409
                form.is_valid()
                form.add_error(None, "This form was already accepted with different details. "
                                     "Reload the anonymous form to start a new submission.")
            except ValidationError as error:
                form, status = _form(data), 400
                form.is_valid()
                if hasattr(error, "error_dict"):
                    for name, errors in error.error_dict.items():
                        form.add_error(name if name in form.fields else None, errors)
                else:
                    form.add_error(None, error)
            except AnonymousIntakeUnavailable:
                form, status = _form(data), 503
                form.is_valid()
                form.add_error(None, "Submission could not be completed. Keep this form and retry the same details and files.")
            else:
                # Only one newly committed operation returns a raw reference.
                # No redirect URL, session, cookie or recoverable receipt stores it.
                return render(request, "complaints/anonymous_accepted.html", {
                    "complaint_id": result.complaint_id, "reference": result.reference,
                    "replayed": result.replayed,
                })
    return render(request, "complaints/anonymous_submit.html", {
        "form": form, "request_token": token,
        "emergency_notice": settings.COMPLAINT_EMERGENCY_NOTICE,
    }, status=status)
