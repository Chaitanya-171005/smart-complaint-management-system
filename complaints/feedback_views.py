"""No-login feedback; never bind or echo the secret reference into a response."""
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from complaints.checks import feedback_release_ready
from workflow.lifecycle import LifecycleError
from workflow.reference_feedback import reference_feedback_summary, submit_reference_feedback


class FeedbackForm(forms.Form):
    action = forms.ChoiceField(choices=[("confirm", "Confirm"), ("reject", "Reject")])
    revision = forms.RegexField(regex=r"\A[0-9a-f]{64}\Z")
    rating = forms.RegexField(regex=r"\A[1-5]\Z", required=False)
    reason = forms.CharField(max_length=2000, required=False)


def _render(request, context, status=200):
    response = render(request, "complaints/reference_feedback.html", context, status=status)
    if not context.get("unavailable") and not context.get("result"):
        response._anonymous_feedback_form = True
    return response


@transaction.non_atomic_requests
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def reference_feedback(request):
    if (not getattr(request, "anonymous_feedback", False)
            or not getattr(request, "anonymous_privacy_isolated", False)
            or not request.is_secure() or not feedback_release_ready()):
        return _render(request, {"unavailable": True}, status=503)
    if request.method == "GET":
        return _render(request, {})
    if not getattr(request, "tracking_allowed", False):
        return _render(request, {"unavailable": True}, status=503)
    allowed = {"csrfmiddlewaretoken", "reference", "action", "revision", "rating", "reason"}
    if (set(request.POST) - allowed or request.FILES
            or any(len(request.POST.getlist(key)) != 1 for key in request.POST)):
        return _render(request, {"error": "Unsupported or repeated feedback fields. Check the status again."}, status=400)
    reference = request.POST.get("reference")
    action = request.POST.get("action", "lookup")
    try:
        if action == "lookup":
            if set(request.POST) - {"csrfmiddlewaretoken", "reference", "action"}:
                return _render(request, {"error": "Check the status before submitting feedback."}, status=400)
            summary = reference_feedback_summary(reference)
            return _render(request, {"searched": True, "summary": summary})
        form = FeedbackForm(request.POST)
        if not form.is_valid():
            return _render(request, {"error": "Choose confirm or reject, a valid optional rating (1–5), and check the status again."}, status=400)
        data = form.cleaned_data
        result = submit_reference_feedback(reference=reference, action=data["action"],
            expected_revision=data["revision"], rating=int(data["rating"]) if data["rating"] else None,
            reason=data["reason"])
        return _render(request, {"searched": True, "result": result})
    except LifecycleError:
        return _render(request, {"error": "The complaint changed or is not resolved. Check its current status before trying again."}, status=409)
    except ValidationError:
        return _render(request, {"error": "For rejection, enter 20–2000 valid characters without your reference and leave rating empty. For confirmation, leave the rejection reason empty."}, status=400)
