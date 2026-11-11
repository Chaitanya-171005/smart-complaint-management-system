"""B24 owner-only feedback form; references are not authorization."""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django.views.decorators.vary import vary_on_cookie

from workflow.lifecycle import LifecycleError, get_transition_revision
from workflow.reopening_service import reject_resolution


class RejectionForm(forms.Form):
    revision = forms.CharField(min_length=64, max_length=64, widget=forms.HiddenInput)
    reason = forms.CharField(min_length=20, max_length=2000, widget=forms.Textarea)


@never_cache
@vary_on_cookie
@sensitive_post_parameters()
@login_required
@require_http_methods(["GET", "POST"])
def reject(request, complaint_id):
    form = RejectionForm(request.POST if request.method == "POST" else None)
    status = 200
    try:
        revision = get_transition_revision(actor=request.user, complaint_id=complaint_id,
                                           target_state="REOPENED")
        if request.method == "GET":
            form = RejectionForm(initial={"revision":revision})
        elif set(request.POST) - {"csrfmiddlewaretoken", "revision", "reason"} or request.FILES:
            form.add_error(None, "Unsupported feedback fields.")
            status = 400
        elif form.is_valid():
            reject_resolution(actor=request.user, complaint_id=complaint_id,
                              expected_revision=form.cleaned_data["revision"],
                              reason=form.cleaned_data["reason"])
            return redirect("workflow:complaint_detail", complaint_id=complaint_id)
        else:
            status = 400
    except LifecycleError as error:
        form.add_error(None, error)
        status = 409
    except ValidationError as error:
        form.add_error(None, error)
        status = 400
    return render(request, "workflow/reject.html", {"form":form, "complaint_id":complaint_id}, status=status)
