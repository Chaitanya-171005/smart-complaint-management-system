"""B22 server-rendered work forms; all mutations go through domain services."""

import logging
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe
from django.views.decorators.vary import vary_on_cookie

from accounts.models import User
from accounts.permissions import (
    authorize_or_404, can_progress_complaint, can_resolve_complaint, can_view_complaint,
    has_role, require_permission,
)
from complaints.models import Attachment, Complaint
from workflow.forms import ProgressForm, ResolutionForm
from workflow.lifecycle import LifecycleError, get_transition_revision
from workflow.resolution_service import progress_complaint, resolve_complaint
from workflow.history_service import get_authorized_complaint_history
from workflow.services import filter_complaints, get_owned_complaints, paginate_complaints

logger = logging.getLogger(__name__)


def _is_tracking_complainant(user):
    return has_role(user, User.Role.COMPLAINANT)


def _tracking_user(request):
    current = User.objects.filter(pk=request.user.pk).first()
    require_permission(_is_tracking_complainant, current)
    return current


@never_cache
@vary_on_cookie
@login_required
@require_safe
def complaint_list(request):
    current = _tracking_user(request)
    owned = get_owned_complaints(current, Complaint.objects.all())
    status = request.GET.get("status", "")
    category = request.GET.get("category", "")
    filtered = filter_complaints(owned, status=status, category=category).order_by("-submitted_at", "-pk")
    return render(request, "workflow/complaint_list.html", {
        "page": paginate_complaints(filtered, request.GET.get("page", 1)),
        "statuses": Complaint.Status.choices,
        "categories": owned.order_by("category").values_list("category", flat=True).distinct(),
        "selected_status": status, "selected_category": category,
        "filter_query": urlencode({"status": status, "category": category}),
    })


@never_cache
@vary_on_cookie
@login_required
@require_safe
def complaint_detail(request, complaint_id):
    current = _tracking_user(request)
    owned = get_owned_complaints(current, Complaint.objects.select_related("department", "assignee"))
    complaint = get_object_or_404(owned, complaint_id=complaint_id)
    authorize_or_404(can_view_complaint, current, complaint)
    history = get_authorized_complaint_history(current, complaint.complaint_id)
    return render(request, "workflow/complaint_detail.html", {
        "complaint": complaint,
        "history_page": paginate_complaints(history, request.GET.get("history_page", 1)),
        "evidence": Attachment.objects.filter(complaint=complaint).order_by("created_at", "pk"),
    })


def _action(request, complaint_id, *, resolution):
    form_class = ResolutionForm if resolution else ProgressForm
    target = Complaint.Status.RESOLVED if resolution else Complaint.Status.IN_PROGRESS
    form = form_class(request.POST if request.method == "POST" else None)
    status = 200
    try:
        revision = get_transition_revision(actor=request.user, complaint_id=complaint_id, target_state=target)
    except LifecycleError as error:
        if request.method == "GET":
            return render(request, "workflow/unavailable.html", {"complaint_id": complaint_id,
                                                                 "errors": error.messages}, status=409)
        form.add_error(None, error)
        status = 409
    else:
        if request.method == "GET":
            form = form_class(initial={"revision": revision})
        else:
            valid = form.is_valid()
            if (set(request.POST) - {"csrfmiddlewaretoken", "revision", "remarks"}
                    or set(request.FILES) - ({"evidence"} if resolution else set())):
                form.add_error(None, "Unsupported action fields.")
                valid = False
            if valid:
                try:
                    arguments = dict(actor=request.user, complaint_id=complaint_id,
                                     expected_revision=form.cleaned_data["revision"],
                                     remarks=form.cleaned_data["remarks"])
                    if resolution:
                        resolve_complaint(**arguments, files=request.FILES.getlist("evidence"))
                    else:
                        progress_complaint(**arguments)
                except LifecycleError as error:
                    form.add_error(None, error)
                    status = 409
                except ValidationError as error:
                    form.add_error(None, error)
                    status = 400
                except (PermissionDenied, Http404):
                    raise
                except Exception:
                    logger.error("Complaint work action outcome could not be confirmed")
                    form.add_error(None, "The action outcome could not be confirmed. Refresh before retrying.")
                    status = 503
                else:
                    return redirect("workflow:work_status", complaint_id=complaint_id)
            else:
                status = 400
    return render(request, "workflow/action.html", {"form": form, "complaint_id": complaint_id,
                                                   "resolution": resolution}, status=status)


@transaction.non_atomic_requests
@never_cache
@vary_on_cookie
@sensitive_post_parameters()
@login_required
@require_http_methods(["GET", "POST"])
def progress(request, complaint_id):
    return _action(request, complaint_id, resolution=False)


@transaction.non_atomic_requests
@never_cache
@vary_on_cookie
@sensitive_post_parameters()
@login_required
@require_http_methods(["GET", "POST"])
def resolve(request, complaint_id):
    return _action(request, complaint_id, resolution=True)


@never_cache
@vary_on_cookie
@login_required
@require_safe
def work_status(request, complaint_id):
    complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
    current = User.objects.filter(pk=request.user.pk).first()
    authorize_or_404(can_view_complaint, current, complaint)
    evidence = Attachment.objects.filter(complaint=complaint, stage=Attachment.Stage.RESOLUTION).order_by("created_at", "pk")
    return render(request, "workflow/work_status.html", {
        "complaint": complaint, "evidence": evidence,
        "can_start": complaint.status in (Complaint.Status.ASSIGNED, Complaint.Status.REOPENED)
                     and can_progress_complaint(current, complaint),
        "can_resolve": complaint.status == Complaint.Status.IN_PROGRESS
                       and can_resolve_complaint(current, complaint),
    })
